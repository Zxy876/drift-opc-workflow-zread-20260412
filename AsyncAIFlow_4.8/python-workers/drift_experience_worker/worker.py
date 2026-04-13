"""
drift_experience_worker/worker.py
===================================
统一体验入口 — capability: drift_experience

将两条断开的链路收敛为一个闭环：

    链路 A（体验生成）
        experiment（Beam Search）→ best_premise / best_level_id

    链路 B（叙事弧编排）
        arc（State Graph）← best_premise

    闭环
        arc 完成 → /story/progress/notify → Drift 侧可查

输入 payload:
    {
        "premise":   str,       # 关卡核心前提（必填）
        "player_id": str,       # 玩家 ID（默认 "demo"）
        "n_variants":   int,    # Beam Search 变体数（默认 3）
        "meta_rounds":  int,    # Beam Search 轮数（默认 2）
        "beam_width":   int,    # 保留路径数（默认 2）
        "arc_levels":   list,   # 覆盖自动叙事弧（可选）
    }

输出 result:
    {
        "schemaVersion":  "v1",
        "exp_result":     { ...drift_experiment result... },
        "arc_result":     { ...drift_arc result... },
        "best_score":     float,
        "best_level_id":  str,
        "state_graph":    [...],
        "summary":        str,
    }

环境变量:
    ASYNCAIFLOW_URL                 = http://localhost:8080
    DRIFT_EXPERIENCE_WORKER_ID      = drift-experience-worker-1
    DRIFT_URL                       = http://localhost:8000
    POLL_INTERVAL_S                 = 2
    HEARTBEAT_INTERVAL_S            = 10
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from typing import Any

import requests

ACTION_TYPE = os.environ.get("DRIFT_EXPERIENCE_ACTION_TYPE", "drift_experience")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-experience-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

ASYNCAIFLOW_URL: str = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
DRIFT_URL: str = os.environ.get("DRIFT_URL", "http://localhost:8000")
WORKER_ID: str = os.environ.get("DRIFT_EXPERIENCE_WORKER_ID", "drift-experience-worker-1")
POLL_INTERVAL_S: float = float(os.environ.get("POLL_INTERVAL_S", "2"))
HEARTBEAT_INTERVAL_S: float = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))

_aaf = requests.Session()
_aaf.trust_env = False
_drift = requests.Session()
_drift.trust_env = False

# ── LLM (optional, mirrors experiment worker) ─────────────────────────────────

def _resolve_llm():
    if os.getenv("OPENAI_API_KEY"):
        return os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", "gpt-4o-mini"), None
    if os.getenv("LLM_API_KEY"):
        return (os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", "glm-4-flash"),
                os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"))
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.getenv("DEEPSEEK_API_KEY", ""), os.getenv("LLM_MODEL", "deepseek-chat"), "https://api.deepseek.com/v1"
    return "", "gpt-4o-mini", None

_LLM_KEY, _LLM_MODEL, _LLM_BASE = _resolve_llm()
_ls = requests.Session()
_ls.trust_env = False

# ── AsyncAIFlow helpers ───────────────────────────────────────────────────────

def _aaf_post(path: str, body: dict) -> dict:
    resp = _aaf.post(f"{ASYNCAIFLOW_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise RuntimeError(f"AsyncAIFlow {path}: {data.get('message', 'error')}")
    return data


def register_worker() -> None:
    _aaf_post("/worker/register", {"workerId": WORKER_ID, "capabilities": [ACTION_TYPE]})
    LOGGER.info("Registered %s capabilities=%s", WORKER_ID, ACTION_TYPE)


def heartbeat() -> None:
    try:
        _aaf_post("/worker/heartbeat", {"workerId": WORKER_ID})
    except Exception as exc:
        LOGGER.warning("Heartbeat failed: %s", exc)


def poll_action() -> dict | None:
    resp = _aaf.get(
        f"{ASYNCAIFLOW_URL}/action/poll",
        params={"workerId": WORKER_ID, "capabilities": ACTION_TYPE},
        timeout=10,
    )
    if resp.status_code == 204 or not resp.text.strip():
        return None
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        return None
    return data.get("data")


def submit_result(action_id: int, status: str, result: dict, error: str | None = None) -> None:
    payload: dict = {
        "workerId": WORKER_ID,
        "actionId": action_id,
        "status": status,
        "result": json.dumps(result, ensure_ascii=False),
    }
    if error:
        payload["errorMessage"] = error
    _aaf_post("/action/result", payload)
    LOGGER.info("action=%s submitted %s", action_id, status)


def renew_lease(action_id) -> None:
    try:
        _aaf_post(f"/action/{action_id}/renew-lease", {"workerId": WORKER_ID})
    except Exception as exc:
        LOGGER.warning("Lease renew failed: %s", exc)


class lease_keeper:
    INTERVAL = 120

    def __init__(self, action_id):
        self._action_id = action_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self.INTERVAL):
            renew_lease(self._action_id)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()


# ── Drift helpers ─────────────────────────────────────────────────────────────

def _safe_id(suffix: str = "") -> str:
    return f"exp_{int(time.time())}{suffix}"


def _inject_level(level_id: str, title: str, text: str, player_id: str) -> dict:
    body = {
        "level_id": level_id,
        "title": title,
        "text": text,
        "player_id": player_id,
        "use_experience_spec": True,
    }
    try:
        resp = _drift.post(f"{DRIFT_URL}/story/inject", json=body, timeout=60)
        data = resp.json() if resp.text.strip() else {}
        exp_sum = data.get("experience_spec_summary") or {}
        return {
            "level_id": level_id,
            "http_status": resp.status_code,
            "status": "ok" if resp.status_code in (200, 201) else "error",
            "beats": exp_sum.get("beat_count", 0),
        }
    except Exception as exc:
        return {"level_id": level_id, "status": "error", "error": str(exc), "beats": 0}


def _request_world_patch(player_id: str, last_level_id: str) -> dict | None:
    """
    Obtain a real world_patch from Drift for MC plugin consumption.

    Strategy (order matters):
      1. Optional rich path: POST /world/story/enter with a STATIC flagship level.
         Only attempted when last_level_id starts with "flagship" (i.e., a real file on disk).
         → returns rich mc patch: title + weather + teleport + sounds
      2. Primary (always attempted): POST /world/apply {"say":"下雨"}
         → guaranteed {"mc": {"weather": "rain"}} — confirmed working, no file lookup.
         → retried up to 3 times with 2s sleep between attempts.

    Root cause of previous failure: injected arc levels (exp_XXXX_N) are memory-only in
    story_engine — load_level_for_player() tries to read a .json file from disk and raises
    FileNotFoundError → HTTP 500. Never call /world/story/enter with injected level IDs.

    Returns the world_patch dict, or None if all attempts fail.
    """
    # ── Optional: rich patch from a static flagship level ────────────────────
    static_id = last_level_id if last_level_id and last_level_id.startswith("flagship") else None
    if static_id:
        try:
            r = _drift.post(
                f"{DRIFT_URL}/world/story/enter",
                json={"player_id": player_id, "level_id": static_id},
                timeout=15,
            )
            if r.status_code in (200, 201):
                wp = r.json().get("world_patch")
                if wp and isinstance(wp, dict):
                    print(
                        f"[WORLD_PATCH] ✓ /world/story/enter level={static_id} "
                        f"mc_keys={list(wp.get('mc',{}).keys())}",
                        flush=True,
                    )
                    return wp
        except Exception as exc:
            LOGGER.warning("_request_world_patch rich-path failed: %s", exc)

    # ── Primary (always attempted with retry): /world/apply weather trigger ──
    # This call is file-lookup-free and always returns {"mc": {"weather": "rain"}}.
    print("[WORLD_PATCH] requesting /world/apply (weather trigger, up to 3 retries)…", flush=True)
    for attempt in range(1, 4):
        try:
            r2 = _drift.post(
                f"{DRIFT_URL}/world/apply",
                json={"action": {"say": "下雨"}, "player_id": player_id},
                timeout=10,
            )
            if r2.status_code in (200, 201):
                wp2 = r2.json().get("world_patch")
                if wp2 and isinstance(wp2, dict):
                    print(f"[WORLD_PATCH] ✓ /world/apply attempt={attempt} → {wp2}", flush=True)
                    return wp2
                print(f"[WORLD_PATCH] /world/apply attempt={attempt} returned empty world_patch", flush=True)
            else:
                print(f"[WORLD_PATCH] /world/apply attempt={attempt} HTTP {r2.status_code}", flush=True)
        except Exception as exc:
            LOGGER.warning("_request_world_patch attempt=%d failed: %s", attempt, exc)
        if attempt < 3:
            time.sleep(2)

    LOGGER.error(
        "[WORLD_PATCH] all attempts failed for player=%s — MC plugin will NOT receive world_patch",
        player_id,
    )
    return None


def _notify_progress(player_id: str, arc_title: str, action_id: Any, result: dict,
                     world_patch: dict | None = None) -> None:
    """
    POST /story/progress/notify with stage="drift_refresh" so the MC plugin poll
    loop (IntentDispatcher2.startProgressPolling) will call world.execute().

    Contract required by MC plugin (IntentDispatcher2.java ~line 340):
      - stage  == "drift_refresh"
      - status == "SUCCEEDED"
      - world_patch != null
    """
    body = {
        "player_id": player_id,
        "stage": "drift_refresh",          # ← MC plugin only acts on this stage
        "message": (
            f"[EXPERIENCE] '{arc_title}' 完成 — "
            f"score={result.get('best_score', 0):.2f} "
            f"levels={result.get('arc_result', {}).get('level_count', 0)}"
        ),
        "workflow_id": str(action_id),
        "status": "SUCCEEDED",
        "world_patch": world_patch,         # ← must be non-null for MC to execute
    }
    wp_present = world_patch is not None and bool(world_patch)
    print(
        f"[NOTIFY] → /story/progress/notify  stage=drift_refresh  "
        f"status=SUCCEEDED  world_patch={'✓ present' if wp_present else '✗ NULL (MC will skip!)'}",
        flush=True,
    )
    try:
        resp = _drift.post(f"{DRIFT_URL}/story/progress/notify", json=body, timeout=10)
        if resp.status_code in (200, 201):
            LOGGER.info("progress/notify accepted for player=%s", player_id)
            print(f"[NOTIFY] ✓ Drift accepted  player={player_id}  workflow={action_id}", flush=True)
        else:
            LOGGER.warning("progress/notify returned %s: %s", resp.status_code, resp.text[:200])
            print(f"[NOTIFY] ✗ Drift returned HTTP {resp.status_code}", flush=True)
    except Exception as exc:
        LOGGER.warning("progress/notify failed (non-fatal): %s", exc)
        print(f"[NOTIFY] ✗ exception: {exc}", flush=True)


# ── Phase 1: Experiment (Beam Search) ────────────────────────────────────────

_DEFAULT_SIM = [
    {"event_type": "quest_event", "payload": {"quest_id": "explore"}},
    {"event_type": "quest_event", "payload": {"quest_id": "collect"}},
]
_AUG = [
    "增加计时器压迫感，玩家必须限时完成。",
    "强调潜行机制，被发现超2次则失败。",
    "加入奖励机制，收集特定物品获额外能力。",
    "多阶段触发：完成目标才解锁下一区域。",
]


def _make_variants(premise: str, n: int) -> list[str]:
    return [premise] + [f"{premise} {_AUG[(i-1) % len(_AUG)]}" for i in range(1, min(n, 5))]


def _simulate(level_id: str, player_id: str, events: list) -> dict:
    sp = f"{player_id}_sim_{int(time.time())}"
    try:
        lr = _drift.post(f"{DRIFT_URL}/story/load/{sp}/{level_id}", json={}, timeout=15)
        if lr.status_code not in (200, 201):
            return {"load_ok": False, "beats_activated": 0, "events_fired": 0}
    except Exception:
        return {"load_ok": False, "beats_activated": 0, "events_fired": 0}
    beats = events_fired = 0
    for ev in events:
        try:
            er = _drift.post(
                f"{DRIFT_URL}/world/story/rule-event",
                json={"player_id": sp, "event_type": ev.get("event_type", "quest_event"),
                      "payload": ev.get("payload") or {}}, timeout=10)
            if er.status_code == 200:
                beats += len(er.json().get("narrative_beats_executed") or [])
                events_fired += 1
        except Exception:
            pass
    return {"load_ok": True, "beats_activated": beats, "events_fired": events_fired}


def _score(meta: dict, sim: dict) -> float:
    beats = meta.get("beats", 0)
    coverage = min(beats / 4.0, 1.0)
    pacing = (min(sim["beats_activated"] / max(sim["events_fired"], 1), 1.0)
              if sim.get("load_ok") and sim.get("events_fired", 0) > 0 else 0.0)
    has_win = meta.get("has_win", False)
    has_lose = meta.get("has_lose", False)
    structure = min((int(has_win) + int(has_lose)) / 2.0, 1.0)
    # No LLM coherence in this worker (keeps it fast); fixed at 0.5
    return round(0.30 * coverage + 0.25 * pacing + 0.30 * 0.5 + 0.15 * structure, 4)


def _run_experiment(premise: str, player_id: str, n_variants: int, meta_rounds: int,
                    beam_width: int, score_threshold: float) -> dict:
    """Inline Beam Search experiment. Returns experiment result dict."""
    print(
        f"[EXP] Start Beam Search — beam_width={beam_width} n_variants={n_variants} "
        f"rounds={meta_rounds} threshold={score_threshold}",
        flush=True,
    )
    beam = [{"premise": premise, "hypothesis": "initial"}]
    history: list = []
    global_best: dict = {}
    global_best_round = 1

    for rnd in range(1, meta_rounds + 1):
        n_each = max(1, n_variants // max(len(beam), 1))
        all_candidates: list[dict] = []

        for bi, node in enumerate(beam):
            variants = _make_variants(node["premise"], n_each + 1)
            for vi, vtext in enumerate(variants):
                idx = len(all_candidates)
                meta = _inject_level(f"{_safe_id()}_{rnd}_{bi}_{vi}", f"实验#{rnd}-{bi}-{vi}", vtext, player_id)
                if not meta.get("status") == "ok":
                    continue
                sim = _simulate(meta["level_id"], player_id, _DEFAULT_SIM)
                sc = _score(meta, sim)
                all_candidates.append({**meta, **sim, "score": sc, "variant_text": vtext[:100], "beam_node": bi})

        all_candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        best = all_candidates[0] if all_candidates else {}
        best_score = best.get("score", 0.0)

        if not global_best or best_score > global_best.get("score", 0.0):
            global_best = best
            global_best_round = rnd

        print(
            f"[EXP] Round {rnd} best score: {best_score:.3f} "
            f"[{'✓ PASS' if best_score >= score_threshold else 'below threshold'}] "
            f"level={best.get('level_id', '?')}",
            flush=True,
        )

        round_summary = {"round": rnd, "candidates_count": len(all_candidates),
                         "best_score": best_score, "best_level_id": best.get("level_id", "")}

        if best_score >= score_threshold or rnd == meta_rounds:
            history.append(round_summary)
            break

        # Build next beam
        new_beam = []
        for c in all_candidates[:beam_width]:
            new_beam.append({"premise": c.get("variant_text", premise), "hypothesis": f"score={c.get('score',0):.3f}"})
        print(f"[EXP] Beam expanded → {len(new_beam)} paths (score {best_score:.3f} < threshold {score_threshold:.2f})", flush=True)
        round_summary["beam_expanded_to"] = len(new_beam)
        history.append(round_summary)
        beam = new_beam

    best_lid = global_best.get("level_id", "")
    best_score_f = global_best.get("score", 0.0)
    best_premise = global_best.get("variant_text", premise)

    return {
        "schemaVersion": "v3",
        "rounds": history,
        "best_level_id": best_lid,
        "best_score": best_score_f,
        "best_premise": best_premise,
        "best_round": global_best_round,
    }


# ── Phase 2: Arc (State Graph) ────────────────────────────────────────────────

_ITEM_PATTERN = re.compile(r"(钥匙|宝石|水晶|符文|卷轴|地图|护符|宝藏|道具|印章|魔法石|圣物|箭矢|火把|药水)")
_FLAG_RULES = [
    (re.compile(r"解锁|开门|打开|门被触发"), "door_unlocked"),
    (re.compile(r"激活传送|传送门开启"),     "portal_activated"),
    (re.compile(r"击败|消灭|boss"),           "enemy_defeated"),
    (re.compile(r"谜题|符文序列|密码"),       "puzzle_solved"),
]
_DEFAULT_ARC_TEMPLATES = [
    ("入口 · {arc}", "玩家进入{arc}，探索初始区域，收集线索和资源，为后续挑战做准备"),
    ("挑战 · {arc}", "玩家在{arc}核心区域面对主要谜题和守卫，需要运用之前获得的资源"),
    ("决战 · {arc}", "玩家到达{arc}最终区域，完成最后挑战，解锁胜利条件"),
]


def _auto_expand_levels(arc_title: str, premise: str) -> list[dict]:
    levels = []
    for t_tpl, tx_tpl in _DEFAULT_ARC_TEMPLATES:
        title = t_tpl.format(arc=arc_title)
        text = tx_tpl.format(arc=arc_title)
        if premise:
            text = f"{text}。背景：{premise[:80]}"
        levels.append({"title": title, "text": text})
    return levels


def _extract_state_obj(inject_result: dict, level_spec: dict) -> dict:
    if inject_result.get("status") != "ok":
        return {"completed_level": "", "inventory": [], "flags": [], "progress": 0.0, "beats_count": 0}
    title = str(level_spec.get("title") or "上一关").strip()
    text = str(level_spec.get("text") or "").strip()
    beats = inject_result.get("beats", 0)
    items = _ITEM_PATTERN.findall(text)
    inventory = list(dict.fromkeys(items))[:4]
    flags: list[str] = []
    for pattern, flag in _FLAG_RULES:
        if pattern.search(text) and flag not in flags:
            flags.append(flag)
    if beats > 0:
        flags.append("level_completed")
    return {"completed_level": title, "inventory": inventory, "flags": flags,
            "progress": round(min(beats / 4.0, 1.0), 2), "beats_count": beats}


def _state_to_context(state_obj: dict) -> str:
    if not state_obj or not state_obj.get("completed_level"):
        return ""
    parts = [f"玩家已完成「{state_obj['completed_level']}」"]
    if state_obj.get("inventory"):
        parts.append(f"持有：{'、'.join(state_obj['inventory'])}")
    readable = {"door_unlocked": "已开门", "portal_activated": "传送门已激活",
                "enemy_defeated": "已击败守卫", "puzzle_solved": "谜题已解"}
    named = [readable.get(f, f) for f in state_obj.get("flags", []) if f != "level_completed"]
    if named:
        parts.append(f"状态：{'、'.join(named)}")
    return "，".join(parts)


def _run_arc(arc_title: str, arc_levels: list, player_id: str, arc_id: str) -> dict:
    """Inline arc execution. Returns arc result dict."""
    inject_results: list[dict] = []
    level_ids: list[str] = []
    state_graph: list[dict] = []
    state_obj: dict = {}

    for idx, lv in enumerate(arc_levels):
        title = str(lv.get("title") or f"第{idx+1}关").strip()
        text = str(lv.get("text") or title).strip()

        if state_obj and state_obj.get("completed_level"):
            ctx = _state_to_context(state_obj)
            if ctx:
                text = f"{text}（前情：{ctx}）"
                # Soft state-graph branch
                if "钥匙" in state_obj.get("inventory", []):
                    text += " 持有的钥匙可直接开启本关锁门。"
                if "portal_activated" in state_obj.get("flags", []):
                    text += " 传送门已激活，任务完成后可传送。"
                if "door_unlocked" in state_obj.get("flags", []):
                    print(f"[ARC]   ↳ door_unlocked → next level gate auto-open hint injected", flush=True)

        level_id = f"{arc_id}_{idx}"
        res = _inject_level(level_id, title, text, player_id)
        new_state = _extract_state_obj(res, lv)
        if state_obj.get("inventory"):
            carried = [i for i in state_obj["inventory"] if i not in new_state["inventory"]]
            new_state["inventory"] = carried + new_state["inventory"]
        state_graph.append(new_state)
        state_obj = new_state
        res["state_obj"] = new_state
        inject_results.append(res)
        level_ids.append(level_id)

        print(
            f"[ARC] Level {idx+1}/{len(arc_levels)} '{title}' → "
            f"beats={res.get('beats', 0)} "
            f"inventory={new_state['inventory']} "
            f"flags={new_state['flags']} "
            f"progress={new_state['progress']:.0%}",
            flush=True,
        )

    succeed_count = sum(1 for r in inject_results if r.get("status") == "ok")
    total_beats = sum(r.get("beats", 0) for r in inject_results)
    has_state_bridge = any(s.get("inventory") or s.get("flags") for s in state_graph)

    return {
        "schemaVersion": "v3",
        "arc_id": arc_id,
        "arc_title": arc_title,
        "level_count": len(level_ids),
        "level_ids": level_ids,
        "inject_results": inject_results,
        "state_graph": state_graph,
        "total_beats": total_beats,
        "succeed_count": succeed_count,
        "summary": (
            f"叙事弧 '{arc_title}' — {succeed_count}/{len(level_ids)} 关注入，"
            f"{total_beats} beats" + ("（state_graph 已激活）" if has_state_bridge else "")
        ),
    }


# ── Master execute ────────────────────────────────────────────────────────────

def execute_experience(action: dict) -> tuple[str, dict, str | None]:
    action_id = action.get("actionId") or action.get("id")
    raw = action.get("payload") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    premise: str = str(raw.get("premise") or "").strip()
    player_id: str = str(raw.get("player_id") or "demo").strip() or "demo"
    n_variants: int = min(int(raw.get("n_variants") or 3), 5)
    meta_rounds: int = min(int(raw.get("meta_rounds") or 2), 3)
    beam_width: int = max(1, min(int(raw.get("beam_width") or 2), n_variants))
    score_threshold: float = float(raw.get("score_threshold") or 0.72)
    arc_levels_override: list = list(raw.get("arc_levels") or [])

    if not premise:
        return "FAILED", {"reason": "premise required"}, "premise required"

    print(f"\n{'='*60}", flush=True)
    print(f"[EXPERIENCE] action_id={action_id} player={player_id}", flush=True)
    print(f"[EXPERIENCE] premise={premise[:80]}", flush=True)
    print(f"{'='*60}", flush=True)

    # ── Phase 1: Experiment ────────────────────────────────────────────────────
    print("\n[EXPERIENCE] ── Phase 1: Experiment (Beam Search) ──", flush=True)
    exp_result = _run_experiment(
        premise=premise,
        player_id=player_id,
        n_variants=n_variants,
        meta_rounds=meta_rounds,
        beam_width=beam_width,
        score_threshold=score_threshold,
    )
    best_score = exp_result.get("best_score", 0.0)
    best_premise = exp_result.get("best_premise") or premise
    best_level_id = exp_result.get("best_level_id", "")

    print(f"\n[EXPERIENCE] Phase 1 complete → best_score={best_score:.3f} level={best_level_id}", flush=True)

    # ── Phase 2: Arc ───────────────────────────────────────────────────────────
    print("\n[EXPERIENCE] ── Phase 2: Arc (State Graph) ──", flush=True)
    arc_title = raw.get("arc_title") or (premise[:20] + "…") if len(premise) > 20 else premise
    arc_id = f"exp_{int(time.time())}"
    arc_levels = arc_levels_override or _auto_expand_levels(arc_title, best_premise)
    arc_result = _run_arc(arc_title, arc_levels, player_id, arc_id)

    state_graph = arc_result.get("state_graph", [])
    arc_succeed = arc_result.get("succeed_count", 0)

    print(f"\n[EXPERIENCE] Phase 2 complete → {arc_succeed}/{arc_result.get('level_count',0)} levels", flush=True)

    # ── Assemble result ────────────────────────────────────────────────────────
    result = {
        "schemaVersion": "v1",
        "worker": WORKER_ID,
        "actionId": action_id,
        "premise": premise[:100],
        "player_id": player_id,
        "exp_result": exp_result,
        "arc_result": arc_result,
        "best_score": best_score,
        "best_level_id": best_level_id,
        "state_graph": state_graph,
        "summary": (
            f"[EXPERIENCE] score={best_score:.3f} "
            f"arc='{arc_title}' {arc_succeed}/{arc_result.get('level_count',0)} 关 "
            f"beats={arc_result.get('total_beats',0)}"
        ),
    }

    # ── Notify Drift (state 回流 → MC plugin contract) ─────────────────────────
    # Get a real world_patch from Drift so MC plugin will execute it.
    # Use the last arc level (if any), else fall back to weather patch.
    last_arc_level_id = (arc_result.get("level_ids") or [None])[-1]
    print(f"\n[EXPERIENCE] ── Phase 3: Request world_patch (last_arc_level={last_arc_level_id}) ──", flush=True)
    world_patch = _request_world_patch(player_id, last_arc_level_id or best_level_id or "")
    result["world_patch_obtained"] = world_patch is not None

    _notify_progress(player_id, arc_title, action_id, result, world_patch=world_patch)

    status = "SUCCEEDED" if (best_level_id or arc_succeed > 0) else "FAILED"
    error = None if status == "SUCCEEDED" else "experiment 和 arc 均未能生成有效关卡"

    print(f"\n{'='*60}", flush=True)
    print(f"[EXPERIENCE] DONE → status={status}", flush=True)
    print(f"[EXPERIENCE] best_score={best_score:.3f}  best_level={best_level_id}", flush=True)
    print(f"[EXPERIENCE] state_graph entries: {len(state_graph)}", flush=True)
    for i, s in enumerate(state_graph):
        print(f"  [{i}] {s.get('completed_level','')} → inv={s.get('inventory',[])} flags={s.get('flags',[])}", flush=True)
    print(f"[EXPERIENCE] summary: {result['summary']}", flush=True)
    print(f"{'='*60}\n", flush=True)

    return status, result, error


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    register_worker()
    last_hb = time.monotonic()

    while True:
        now = time.monotonic()
        if now - last_hb >= HEARTBEAT_INTERVAL_S:
            heartbeat()
            last_hb = now

        try:
            action = poll_action()
        except Exception as exc:
            LOGGER.warning("Poll failed: %s — retrying in %ss", exc, POLL_INTERVAL_S)
            time.sleep(POLL_INTERVAL_S)
            continue

        if action is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        action_id = action.get("actionId") or action.get("id")
        action_type = action.get("actionType") or action.get("type", "")
        LOGGER.info("Claimed action_id=%s type=%s", action_id, action_type)

        if action_type != ACTION_TYPE:
            submit_result(action_id, "FAILED",
                          {"reason": f"unsupported: {action_type}"},
                          error=f"unsupported action type: {action_type}")
            continue

        try:
            with lease_keeper(action_id):
                status, result, error = execute_experience(action)
            submit_result(action_id, status, result, error)
        except Exception as exc:
            LOGGER.exception("execute_experience failed: %s", exc)
            submit_result(action_id, "FAILED", {"reason": str(exc)}, error=str(exc))


if __name__ == "__main__":
    run()
