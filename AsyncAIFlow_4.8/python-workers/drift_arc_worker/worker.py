"""
drift_arc_worker/worker.py v3
==============================
叙事弧编排器 — Level 4: Structured State Graph

核心升级：state_chain(字符串) → state_graph(结构化对象)

stateObject schema:
  {
    "completed_level": "钥匙铸造间",
    "inventory": ["水晶", "钥匙"],     # 可计算，下一关可做条件分支
    "flags": ["door_unlocked"],         # 事件标记，驱动分支逻辑
    "progress": 0.75,                   # beats_count / 4.0
    "beats_count": 3
  }

→ state_graph[i] 可被下一关使用：
   "持有 ['水晶', '钥匙']，已解锁 door_unlocked → 迷宫大门自动开启"

结果包含 state_graph（结构化对象列表），同时保留 narrative_context 字符串供调试。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

import requests

ACTION_TYPE = os.environ.get("DRIFT_ARC_ACTION_TYPE", "drift_arc")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-arc-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

ASYNCAIFLOW_URL: str = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
DRIFT_URL: str = os.environ.get("DRIFT_URL", "http://localhost:8000")
WORKER_ID: str = os.environ.get("DRIFT_ARC_WORKER_ID", "drift-arc-worker-1")
POLL_INTERVAL_S: float = float(os.environ.get("POLL_INTERVAL_S", "2"))
HEARTBEAT_INTERVAL_S: float = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))

_aaf = requests.Session()
_aaf.trust_env = False
_drift = requests.Session()
_drift.trust_env = False

# ─────────────────────────────────────────────────────────────────────────────
# AsyncAIFlow helpers
# ─────────────────────────────────────────────────────────────────────────────

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
    """Renew the action lease to prevent expiry during long processing."""
    try:
        _aaf_post(f"/action/{action_id}/renew-lease", {"workerId": WORKER_ID})
        LOGGER.debug("Lease renewed for action=%s", action_id)
    except Exception as exc:
        LOGGER.warning("Lease renew failed for action=%s: %s", action_id, exc)


class lease_keeper:
    """Context manager: background thread renews action lease every INTERVAL seconds."""
    INTERVAL = 120  # renew every 2 minutes (lease TTL=300s)

    def __init__(self, action_id):
        self._action_id = action_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self.INTERVAL):
            renew_lease(self._action_id)

    def __enter__(self):
        self._thread.start(); return self

    def __exit__(self, *_):
        self._stop.set()


# ─────────────────────────────────────────────────────────────────────────────
# Drift API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_id(raw: str, suffix: str = "") -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:24]
    ts = int(time.time())
    return f"arc_{ts}_{sanitized}{suffix}"


def _inject_level(level_id: str, title: str, text: str, player_id: str) -> dict[str, Any]:
    """调用 Drift /story/inject，返回 {level_id, status, beats, exp_summary}。"""
    body = {
        "level_id": level_id,
        "title": title,
        "text": text,
        "player_id": player_id,
        "use_experience_spec": True,
    }
    LOGGER.info("inject level_id=%s title=%r", level_id, title)
    try:
        resp = _drift.post(f"{DRIFT_URL}/story/inject", json=body, timeout=60)
        data = resp.json() if resp.text.strip() else {}
        exp_sum = data.get("experience_spec_summary") or {}
        return {
            "level_id": level_id,
            "http_status": resp.status_code,
            "status": "ok" if resp.status_code in (200, 201) else "error",
            "beats": exp_sum.get("beat_count", 0),
            "beat_count": exp_sum.get("beat_count", 0),
            "rule_count": exp_sum.get("rule_count", 0),
            "trigger_count": exp_sum.get("trigger_count", 0),
            "has_win": exp_sum.get("has_win_condition", False),
            "has_lose": exp_sum.get("has_lose_condition", False),
        }
    except Exception as exc:
        LOGGER.warning("inject failed level_id=%s: %s", level_id, exc)
        return {"level_id": level_id, "status": "error", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# 自动拆分关卡
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_ARC_TEMPLATES = [
    ("入口 · {arc}", "玩家进入{arc}，探索初始区域，收集线索和资源，为后续挑战做准备"),
    ("挑战 · {arc}", "玩家在{arc}核心区域面对主要谜题和守卫，需要运用之前获得的资源"),
    ("决战 · {arc}", "玩家到达{arc}最终区域，完成最后挑战，解锁胜利条件"),
]


def _auto_expand_levels(arc_title: str, premise: str) -> list[dict[str, str]]:
    levels = []
    for title_tpl, text_tpl in _DEFAULT_ARC_TEMPLATES:
        title = title_tpl.format(arc=arc_title)
        text = text_tpl.format(arc=arc_title)
        if premise:
            text = f"{text}。背景：{premise[:100]}"
        levels.append({"title": title, "text": text})
    return levels


# ─────────────────────────────────────────────────────────────────────────────
# ③ Structured State Graph (升级自 v2 字符串 state_chain)
# ─────────────────────────────────────────────────────────────────────────────

_ITEM_PATTERN = re.compile(r"(钥匙|宝石|水晶|符文|卷轴|地图|护符|宝藏|道具|印章|魔法石|圣物|箭矢|火把|药水)")
_FLAG_RULES = [
    (re.compile(r"解锁|开门|打开|门被触发"), "door_unlocked"),
    (re.compile(r"激活传送|传送门开启"),     "portal_activated"),
    (re.compile(r"击败|消灭|boss"),           "enemy_defeated"),
    (re.compile(r"谜题|符文序列|密码"),       "puzzle_solved"),
]


def _extract_state_obj(inject_result: dict, level_spec: dict) -> dict:
    """
    从注入结果 + 关卡描述提取结构化状态对象。
    返回 stateObject（可计算，可供条件分支），取代原字符串 state_bridge。

    schema: {completed_level, inventory[], flags[], progress, beats_count}
    """
    empty = {"completed_level": "", "inventory": [], "flags": [], "progress": 0.0, "beats_count": 0}
    if inject_result.get("status") != "ok":
        return empty

    title = str(level_spec.get("title") or "上一关").strip()
    text = str(level_spec.get("text") or "").strip()
    beats = inject_result.get("beats", 0)

    # Extract inventory items (deduplicated, max 4)
    items = _ITEM_PATTERN.findall(text)
    inventory = list(dict.fromkeys(items))[:4]

    # Extract flags from text patterns
    flags = []
    for pattern, flag in _FLAG_RULES:
        if pattern.search(text) and flag not in flags:
            flags.append(flag)
    # Add implicit completion flag
    if beats > 0:
        flags.append("level_completed")

    return {
        "completed_level": title,
        "inventory": inventory,
        "flags": flags,
        "progress": round(min(beats / 4.0, 1.0), 2),
        "beats_count": beats,
    }


def _state_to_context(state_obj: dict) -> str:
    """
    Convert structured state_obj → natural language for injection into next level.
    This is the computed string used to prefix next level text.
    """
    if not state_obj or not state_obj.get("completed_level"):
        return ""
    parts = [f"玩家已完成「{state_obj['completed_level']}」"]
    if state_obj.get("inventory"):
        parts.append(f"持有：{'、'.join(state_obj['inventory'])}")
    readable_flags = {
        "door_unlocked": "已开门", "portal_activated": "传送门已激活",
        "enemy_defeated": "已击败守卫", "puzzle_solved": "谜题已解",
        "level_completed": "任务完成",
    }
    named_flags = [readable_flags.get(f, f) for f in state_obj.get("flags", [])
                   if f != "level_completed"]
    if named_flags:
        parts.append(f"状态：{'、'.join(named_flags)}")
    if state_obj.get("progress", 0) > 0:
        parts.append(f"完成度：{state_obj['progress']:.0%}")
    return "，".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 核心执行逻辑
# ─────────────────────────────────────────────────────────────────────────────

def execute_arc(action: dict) -> tuple[str, dict, str | None]:
    action_id: int = action.get("actionId") or action.get("id")
    raw_payload = action.get("payload") or {}
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except Exception:
            raw_payload = {}

    player_id: str = str(raw_payload.get("player_id") or "demo").strip() or "demo"
    arc_title: str = str(raw_payload.get("arc_title") or "未命名叙事弧").strip()
    premise: str = str(raw_payload.get("premise") or "").strip()
    arc_levels: list = list(raw_payload.get("arc_levels") or [])

    if not arc_levels:
        arc_levels = _auto_expand_levels(arc_title, premise)
        LOGGER.info("Auto-expanded arc into %d levels", len(arc_levels))

    arc_id = _safe_id(arc_title)
    inject_results: list[dict] = []
    level_ids: list[str] = []
    state_graph: list[dict] = []   # ③ structured state per level
    state_obj: dict = {}           # carries over from previous level

    for idx, lv in enumerate(arc_levels):
        title = str(lv.get("title") or f"第{idx+1}关").strip()
        text = str(lv.get("text") or title).strip()

        # ③ Use structured state to build context prefix for next level
        if state_obj and state_obj.get("completed_level"):
            context_str = _state_to_context(state_obj)
            if context_str:
                text = f"{text}（前情：{context_str}）"
                # Conditional branch: if key items present, add hint
                if "钥匙" in state_obj.get("inventory", []):
                    text += " 持有的钥匙可直接开启本关锁门。"
                if "portal_activated" in state_obj.get("flags", []):
                    text += " 传送门已激活，任务完成后可传送。"
                LOGGER.info("  state_graph → context=%r", context_str[:80])

        level_id = _safe_id(arc_title, f"_{idx}")
        res = _inject_level(level_id, title, text, player_id)

        # Extract structured state for next level
        new_state = _extract_state_obj(res, lv)
        # Carry inventory forward (items persist across levels)
        if state_obj.get("inventory"):
            carried = [i for i in state_obj["inventory"] if i not in new_state["inventory"]]
            new_state["inventory"] = carried + new_state["inventory"]
        state_graph.append(new_state)
        state_obj = new_state

        res["state_obj"] = new_state   # visible in result
        inject_results.append(res)
        level_ids.append(level_id)
        LOGGER.info("  → state_obj inventory=%s flags=%s progress=%.0f%%",
            new_state["inventory"], new_state["flags"], new_state["progress"] * 100)
        # ── [ARC] structured console output (observability) ──────────────────
        print(
            f"[ARC] Level {idx + 1}/{len(arc_levels)} '{title}' → "
            f"beats={res.get('beats', 0)} "
            f"inventory={new_state['inventory']} "
            f"flags={new_state['flags']} "
            f"progress={new_state['progress']:.0%}",
            flush=True,
        )
        # Soft state-graph branch: if door_unlocked, log conditional hint
        if "door_unlocked" in new_state.get("flags", []):
            print(f"[ARC]   ↳ door_unlocked detected → next level will auto-open gate", flush=True)

    succeed_count = sum(1 for r in inject_results if r.get("status") == "ok")
    total_beats = sum(r.get("beats", 0) for r in inject_results)
    has_state_bridge = any(s.get("inventory") or s.get("flags") for s in state_graph)

    result = {
        "schemaVersion": "v3",
        "worker": WORKER_ID,
        "actionId": action_id,
        "arc_id": arc_id,
        "arc_title": arc_title,
        "level_count": len(level_ids),
        "level_ids": level_ids,
        "inject_results": inject_results,
        "state_graph": state_graph,       # ③ structured (was string state_chain)
        "total_beats": total_beats,
        "summary": (
            f"叙事弧 '{arc_title}' — {succeed_count}/{len(level_ids)} 个关卡注入 Drift，"
            f"共 {total_beats} 个 narrative beats"
            + ("（state_graph 已激活）" if has_state_bridge else "")
        ),
    }
    status = "SUCCEEDED" if succeed_count > 0 else "FAILED"
    error = None if succeed_count > 0 else "所有关卡注入均失败"
    return status, result, error


# ─────────────────────────────────────────────────────────────────────────────
# Progress notify（state 回流 Drift）
# ─────────────────────────────────────────────────────────────────────────────

def _notify_progress(player_id: str, arc_title: str, result: dict) -> None:
    """POST /story/progress/notify so Drift (and MC plugin) knows arc completed."""
    body = {
        "player_id": player_id,
        "stage": "arc_completed",
        "message": f"[ARC] 叙事弧 '{arc_title}' 完成：{result.get('level_count', 0)} 关，{result.get('total_beats', 0)} beats",
        "workflow_id": str(result.get("actionId", "")),
        "status": "SUCCEEDED",
        "state_graph": result.get("state_graph", []),
    }
    try:
        resp = _drift.post(f"{DRIFT_URL}/story/progress/notify", json=body, timeout=10)
        if resp.status_code in (200, 201):
            LOGGER.info("progress/notify accepted for player=%s", player_id)
            print(f"[ARC] ✓ progress/notify → Drift player={player_id} arc='{arc_title}'", flush=True)
        else:
            LOGGER.warning("progress/notify returned %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        LOGGER.warning("progress/notify failed (non-fatal): %s", exc)

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
                status, result, error = execute_arc(action)
            # ── State 回流：notify Drift progress after arc completes ────────
            if status == "SUCCEEDED":
                raw_payload = action.get("payload") or {}
                if isinstance(raw_payload, str):
                    try:
                        raw_payload = json.loads(raw_payload)
                    except Exception:
                        raw_payload = {}
                _notify_progress(
                    player_id=str(raw_payload.get("player_id") or "demo"),
                    arc_title=str(raw_payload.get("arc_title") or result.get("arc_title", "")),
                    result=result,
                )
            submit_result(action_id, status, result, error)
        except Exception as exc:
            LOGGER.exception("execute_arc failed: %s", exc)
            submit_result(action_id, "FAILED",
                          {"reason": str(exc)},
                          error=str(exc))


if __name__ == "__main__":
    run()
