"""
drift_experiment_worker/worker.py v3
======================================
Level 4 — Adaptive Search System

① Beam Search (Tree Search):
     每轮保留 top-K 路径（而非贪心单路径）
     Round N: beam_width paths × n_each variants → 全局竞争 → 保留 top-K

② LLM as Hypothesis Generator（设计空间扩展器）:
     不是「修补问题」，而是「提出全新设计方向」
     LLM generates novel design hypotheses, not just patches

③ Scoring: coverage(0.30)+pacing(0.25)+coherence_LLM(0.30)+structure(0.15)

Result: schemaVersion v3, rounds[], beam_evolution[], global best across all paths
"""
from __future__ import annotations
import json, logging, os, re, time, threading
import requests

ACTION_TYPE = os.environ.get("DRIFT_EXPERIMENT_ACTION_TYPE", "drift_experiment")
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [drift-experiment-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S")
LOGGER = logging.getLogger(__name__)

ASYNCAIFLOW_URL = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
DRIFT_URL = os.environ.get("DRIFT_URL", "http://localhost:8000")
WORKER_ID = os.environ.get("DRIFT_EXPERIMENT_WORKER_ID", "drift-experiment-worker-1")
POLL_INTERVAL_S = float(os.environ.get("POLL_INTERVAL_S", "2"))
HEARTBEAT_INTERVAL_S = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))
MAX_VARIANTS = 5
MAX_META_ROUNDS = 3
DEFAULT_SCORE_THRESHOLD = 0.72
DEFAULT_BEAM_WIDTH = 2          # Beam Search: top-K paths to keep per round

_aaf = requests.Session(); _aaf.trust_env = False
_drift = requests.Session(); _drift.trust_env = False

# ── LLM client ────────────────────────────────────────────────────────────────

def _resolve_llm():
    if os.getenv("OPENAI_API_KEY"):
        return os.getenv("OPENAI_API_KEY",""), os.getenv("OPENAI_MODEL","gpt-4o-mini"), None
    if os.getenv("LLM_API_KEY"):
        return os.getenv("LLM_API_KEY",""), os.getenv("LLM_MODEL","glm-4-flash"), os.getenv("LLM_BASE_URL","https://open.bigmodel.cn/api/paas/v4/")
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.getenv("DEEPSEEK_API_KEY",""), os.getenv("LLM_MODEL","deepseek-chat"), "https://api.deepseek.com/v1"
    return "", "gpt-4o-mini", None

_LLM_KEY, _LLM_MODEL, _LLM_BASE = _resolve_llm()
_ls = requests.Session(); _ls.trust_env = False

def _llm(system, user, max_tokens=200):
    if not _LLM_KEY: return ""
    base = _LLM_BASE or "https://api.openai.com/v1"
    try:
        r = _ls.post(f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {_LLM_KEY}", "Content-Type": "application/json"},
            json={"model": _LLM_MODEL, "messages":[{"role":"system","content":system},{"role":"user","content":user}],
                  "max_tokens": max_tokens, "temperature": 0.7}, timeout=20)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        LOGGER.warning("LLM failed: %s", e); return ""

# ── AAF helpers ───────────────────────────────────────────────────────────────

def _aaf_post(path, body):
    r = _aaf.post(f"{ASYNCAIFLOW_URL}{path}", json=body, timeout=10); r.raise_for_status()
    d = r.json()
    if not d.get("success"): raise RuntimeError(f"AAF {path}: {d.get('message','error')}")
    return d

def register_worker():
    _aaf_post("/worker/register", {"workerId": WORKER_ID, "capabilities": [ACTION_TYPE]})
    LOGGER.info("Registered %s", WORKER_ID)

def heartbeat():
    try: _aaf_post("/worker/heartbeat", {"workerId": WORKER_ID})
    except Exception as e: LOGGER.warning("HB: %s", e)

def poll_action():
    r = _aaf.get(f"{ASYNCAIFLOW_URL}/action/poll",
        params={"workerId": WORKER_ID, "capabilities": ACTION_TYPE}, timeout=10)
    if r.status_code == 204 or not r.text.strip(): return None
    r.raise_for_status()
    d = r.json()
    return d.get("data") if d.get("success") else None

def submit_result(action_id, status, result, error=None):
    p = {"workerId": WORKER_ID, "actionId": action_id, "status": status,
         "result": json.dumps(result, ensure_ascii=False)}
    if error: p["errorMessage"] = error
    _aaf_post("/action/result", p)
    LOGGER.info("action=%s submitted %s", action_id, status)

def renew_lease(action_id):
    """Renew the action lease to prevent expiry during long processing."""
    try:
        _aaf_post(f"/action/{action_id}/renew-lease", {"workerId": WORKER_ID})
        LOGGER.debug("Lease renewed for action=%s", action_id)
    except Exception as e:
        LOGGER.warning("Lease renew failed for action=%s: %s", action_id, e)

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

# ── Drift helpers ─────────────────────────────────────────────────────────────

def _safe_id(pfx="exp"):
    return f"{pfx}_{int(time.time())}"

def _make_variants(premise, n):
    """Generate N variant texts from premise (first = original)."""
    augs = ["增加计时器压迫感，玩家必须限时完成。",
            "强调潜行机制，被发现超2次则失败。",
            "加入奖励机制，收集特定物品获额外能力。",
            "多阶段触发：完成目标才解锁下一区域。"]
    return [premise] + [f"{premise} {augs[(i-1)%len(augs)]}" for i in range(1, min(n, MAX_VARIANTS))]

def _inject(variant_text, player_id, idx):
    lid = f"{_safe_id()}_{idx}"
    try:
        r = _drift.post(f"{DRIFT_URL}/story/inject", json={
            "level_id": lid, "title": f"实验变体 #{idx+1}",
            "text": variant_text, "player_id": player_id, "use_experience_spec": True}, timeout=60)
        if not r.text.strip():
            return {"level_id": lid, "inject_ok": False, "variant_text": variant_text}
        d = r.json(); exp = d.get("experience_spec_summary") or {}
        return {"level_id": lid, "inject_ok": r.status_code in (200, 201),
                "beats": exp.get("beat_count", 0), "rules": exp.get("rule_count", 0),
                "triggers": exp.get("trigger_count", 0),
                "has_win": exp.get("has_win_condition", False),
                "has_lose": exp.get("has_lose_condition", False),
                "variant_text": variant_text[:120]}
    except Exception as e:
        LOGGER.warning("inject %d: %s", idx, e)
        return {"level_id": lid, "inject_ok": False, "variant_text": variant_text}

def _simulate(level_id, player_id, events):
    sp = f"{player_id}_sim_{int(time.time())}"
    try:
        lr = _drift.post(f"{DRIFT_URL}/story/load/{sp}/{level_id}", json={}, timeout=15)
        if lr.status_code not in (200, 201):
            return {"load_ok": False, "beats_activated": 0, "events_fired": 0}
    except Exception as e:
        LOGGER.warning("load %s: %s", level_id, e)
        return {"load_ok": False, "beats_activated": 0, "events_fired": 0}
    beats_activated = events_fired = 0
    for ev in events:
        try:
            er = _drift.post(f"{DRIFT_URL}/world/story/rule-event",
                json={"player_id": sp, "event_type": ev.get("event_type", "quest_event"),
                      "payload": ev.get("payload") or {}}, timeout=10)
            if er.status_code == 200:
                beats_activated += len(er.json().get("narrative_beats_executed") or [])
                events_fired += 1
        except Exception:
            pass
    return {"load_ok": True, "beats_activated": beats_activated, "events_fired": events_fired}

# ── Scoring: coverage + pacing + coherence(LLM) + structure ──────────────────

def _coherence(premise, meta):
    if not _LLM_KEY: return 0.5
    raw = _llm(
        "You are a game design critic. Rate narrative coherence of a level design.",
        f"Premise: {premise}\nVariant: {meta.get('variant_text','')}\n"
        f"Beats: {meta.get('beats',0)} Rules: {meta.get('rules',0)} Win: {meta.get('has_win')} Lose: {meta.get('has_lose')}\n"
        "Rate narrative coherence 0.0-1.0. Return ONLY a single number like 0.75.", 10)
    m = re.search(r"\d+\.?\d*", raw)
    if m:
        v = float(m.group()); return min(max(v if v <= 1.0 else v / 10.0, 0.0), 1.0)
    return 0.5

def _score(premise, meta, sim, coh=None):
    beats = meta.get("beats", 0)
    coverage = min(beats / 4.0, 1.0)
    pacing = (min(sim["beats_activated"] / max(sim["events_fired"], 1), 1.0)
              if sim.get("load_ok") and sim.get("events_fired", 0) > 0 else 0.0)
    coherence = coh if coh is not None else _coherence(premise, meta)
    has_win = meta.get("has_win", False); has_lose = meta.get("has_lose", False)
    structure = (0.4 if has_win else 0.0) + (0.4 if has_lose else 0.0) + min(meta.get("triggers", 0) / 3.0, 1.0) * 0.2
    total = round(coverage * 0.30 + pacing * 0.25 + coherence * 0.30 + structure * 0.15, 3)
    return {"coverage": round(coverage, 3), "pacing": round(pacing, 3),
            "coherence": round(coherence, 3), "structure": round(structure, 3), "score": total}

# ── Weakness analysis ─────────────────────────────────────────────────────────

def _analyze(best):
    issues = []
    if best.get("coverage", 0) < 0.5: issues.append(f"beats不足({best.get('beats',0)}，期望≥4)")
    if not best.get("has_win"): issues.append("缺胜利条件")
    if not best.get("has_lose"): issues.append("缺失败条件")
    if best.get("pacing", 0) < 0.4: issues.append(f"节奏弱(激活率={best.get('pacing',0):.2f})")
    if best.get("coherence", 0.5) < 0.5: issues.append(f"连贯性低(LLM={best.get('coherence',0):.2f})")
    if _LLM_KEY and issues:
        adv = _llm("你是游戏设计顾问。",
            f"问题：{'；'.join(issues[:3])}\n文本：{best.get('variant_text','')}\n给出一句话改进方向（≤30字）：", 60)
        if adv: return adv.strip()
    return "；".join(issues) if issues else "质量良好，微调叙事密度"

# ── ② LLM Hypothesis Generator（设计空间扩展，非补丁）────────────────────────

def _llm_hypothesis(variant: dict, weakness: str, rnd: int) -> str:
    """
    LLM as hypothesis generator: proposes a NOVEL design direction, not a fix.
    V2: _improve() only patched problems → V3: _llm_hypothesis() expands the design space.
    """
    vt = variant.get("variant_text", "")
    if _LLM_KEY:
        raw = _llm(
            "你是资深游戏体验设计师，擅长探索性思维和创新设计空间扩展。",
            f"当前关卡设计：{vt}\n"
            f"已知弱点：{weakness}\n"
            f"第{rnd}轮假设生成。\n"
            "请提出一个【全新设计方向假设】（不是修补已有问题，而是探索新设计维度）：\n"
            "可以引入：巡逻/追逐系统、多步骤解谜序列、隐藏捷径、NPC盟友/对立、"
            "环境危机（洪水/坍塌）、时间循环、道具组合触发等。\n"
            "直接输出新设计前提（20-80字，只输出设计文本）：",
            150
        )
        if raw and len(raw) > 10:
            return raw.strip()
    # Rule-based hypothesis expansion (no LLM fallback routes)
    _HYPOTHESES = [
        f"{vt[:40]}。加入敌人巡逻路线，玩家需潜入并在被发现前完成目标，发现2次则失败。",
        f"{vt[:40]}。存在三处符文台，需按密码顺序激活才能解锁最终门，顺序来自场景线索。",
        f"{vt[:40]}。有隐藏捷径需收集2个线索道具才能激活，走捷径可绕过主要障碍。",
        f"{vt[:40]}。遇到NPC囚徒，帮助解救后获得关键道具，但耗时触发计时器倒数。",
    ]
    return _HYPOTHESES[(rnd - 1) % len(_HYPOTHESES)]

# ── Default simulation events ─────────────────────────────────────────────────

_DEFAULT_SIM = [
    {"event_type": "quest_event", "payload": {"quest_event": "exp_collect_gem"}},
    {"event_type": "quest_event", "payload": {"quest_event": "exp_proximity_altar"}},
    {"event_type": "quest_event", "payload": {"quest_event": "exp_collect_crystal"}},
]

# ── Single round: evaluate N variants from ONE premise ────────────────────────

def _run_round(premise, n_variants, player_id, sim_events, rnd, node_idx=0):
    scored = []
    for idx, vt in enumerate(_make_variants(premise, n_variants)):
        meta = _inject(vt, player_id, idx)
        if not meta.get("inject_ok"):
            scored.append({**meta, "score": 0.0, "coverage": 0.0, "pacing": 0.0,
                           "coherence": 0.0, "structure": 0.0, "beats_activated": 0, "sim_events_fired": 0})
            continue
        coh = _coherence(premise, meta)
        sim = _simulate(meta["level_id"], player_id, sim_events)
        sc = _score(premise, meta, sim, coh)
        scored.append({**meta, **sc, "beats_activated": sim.get("beats_activated", 0),
                       "sim_events_fired": sim.get("events_fired", 0), "load_ok": sim.get("load_ok", False)})
        LOGGER.info("  [R%d b%d v%d] %s score=%.3f cov=%.2f pac=%.2f coh=%.2f str=%.2f",
            rnd, node_idx, idx, meta["level_id"], sc["score"],
            sc["coverage"], sc["pacing"], sc["coherence"], sc["structure"])
    scored.sort(key=lambda v: v.get("score", 0.0), reverse=True)
    return scored

# ── ① Beam Expansion: evaluate all beam nodes, return global sorted candidates ─

def _beam_expand(beam_nodes: list, n_each: int, player_id: str, sim_events: list, rnd: int) -> list:
    """
    Expand ALL active beam paths in parallel.
    Returns a flat list of ALL candidates sorted by score (global competition).

    This is the key difference from v2 greedy search:
    - v2: single path → improve → next round
    - v3: K paths compete → top-K survive → each expands next round
    """
    all_candidates: list = []
    for node_idx, node in enumerate(beam_nodes):
        node_premise = node["premise"]
        LOGGER.info("=== [R%d beam %d/%d] premise=%r ===",
            rnd, node_idx + 1, len(beam_nodes), node_premise[:60])
        variants = _run_round(node_premise, max(n_each, 1), player_id, sim_events, rnd, node_idx)
        for v in variants:
            v["beam_node"] = node_idx
            v["beam_premise"] = node_premise[:80]
            all_candidates.append(v)
    # Global ranking across all beam nodes
    all_candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    for i, c in enumerate(all_candidates): c["global_rank"] = i + 1
    return all_candidates

# ── Main execute: Beam Search meta loop ──────────────────────────────────────

def execute_experiment(action):
    action_id = action.get("actionId") or action.get("id")
    raw = action.get("payload") or {}
    if isinstance(raw, str):
        try: raw = json.loads(raw)
        except Exception: raw = {}

    player_id = str(raw.get("player_id") or "demo").strip() or "demo"
    premise = str(raw.get("premise") or "").strip()
    n_variants = min(int(raw.get("n_variants") or 3), MAX_VARIANTS)
    meta_rounds = min(int(raw.get("meta_rounds") or 2), MAX_META_ROUNDS)
    score_threshold = float(raw.get("score_threshold") or DEFAULT_SCORE_THRESHOLD)
    beam_width = max(1, min(int(raw.get("beam_width") or DEFAULT_BEAM_WIDTH), n_variants))
    sim_events = list(raw.get("sim_events") or _DEFAULT_SIM)

    if not premise:
        return "FAILED", {"reason": "premise required"}, "premise required"

    LOGGER.info("Experiment v3 (BeamSearch): beam_width=%d n_variants=%d meta_rounds=%d threshold=%.2f llm=%s",
        beam_width, n_variants, meta_rounds, score_threshold, "YES" if _LLM_KEY else "NO")
    print(
        f"[EXP] Start Beam Search — beam_width={beam_width} n_variants={n_variants} "
        f"rounds={meta_rounds} threshold={score_threshold} llm={'YES' if _LLM_KEY else 'NO (coherence=0.5)'}",
        flush=True,
    )

    # Each beam node: {premise, hypothesis (why this path was chosen)}
    beam: list = [{"premise": premise, "hypothesis": "initial"}]
    history: list = []
    global_best: dict = {}
    global_best_round = 1

    for rnd in range(1, meta_rounds + 1):
        n_each = max(1, n_variants // len(beam))
        all_candidates = _beam_expand(beam, n_each, player_id, sim_events, rnd)

        best = all_candidates[0] if all_candidates else {}
        best_score = best.get("score", 0.0)
        if not global_best or best_score > global_best.get("score", 0.0):
            global_best = best; global_best_round = rnd

        round_summary = {
            "round": rnd,
            "beam_paths": len(beam),
            "candidates_count": len(all_candidates),
            "best_score": best_score,
            "best_level_id": best.get("level_id", ""),
            # Store top candidates (limit for result size)
            "top_candidates": [
                {k: v for k, v in c.items() if k not in ("load_ok",)}
                for c in all_candidates[:beam_width * 2]
            ],
        }

        if best_score >= score_threshold or rnd == meta_rounds:
            LOGGER.info("Round %d DONE score=%.3f [%s]", rnd, best_score,
                        "PASS" if best_score >= score_threshold else "FINAL")
            print(
                f"[EXP] Round {rnd} best score: {best_score:.3f} "
                f"[{'✓ PASS' if best_score >= score_threshold else 'FINAL'}] "
                f"level={best.get('level_id', '?')}",
                flush=True,
            )
            history.append(round_summary)
            break

        # Build next beam: each top-K winner generates a new HYPOTHESIS
        beam_evolution = []
        new_beam = []
        for c in all_candidates[:beam_width]:
            weakness = _analyze(c)
            # ② LLM as hypothesis generator: propose novel design direction
            new_premise = _llm_hypothesis(c, weakness, rnd)
            LOGGER.info("  [beam→] from=%s score=%.3f weakness=%r\n           → hypothesis=%r",
                c.get("level_id","?"), c.get("score",0.0), weakness[:50], new_premise[:60])
            new_beam.append({"premise": new_premise, "hypothesis": weakness})
            beam_evolution.append({
                "from_level_id": c.get("level_id", ""),
                "from_score": c.get("score", 0.0),
                "from_beam_node": c.get("beam_node", 0),
                "weakness": weakness,
                "new_premise": new_premise[:120],
            })

        LOGGER.info("Round %d score=%.3f < %.2f → beam expands %d paths",
            rnd, best_score, score_threshold, len(new_beam))
        print(
            f"[EXP] Beam expanded → {len(new_beam)} paths (score {best_score:.3f} < threshold {score_threshold:.2f})",
            flush=True,
        )
        round_summary["beam_evolution"] = beam_evolution
        history.append(round_summary)
        beam = new_beam

    best_lid = global_best.get("level_id", "")
    best_score_f = global_best.get("score", 0.0)
    result = {
        "schemaVersion": "v3",
        "worker": WORKER_ID,
        "actionId": action_id,
        "premise": premise[:100],
        "n_variants": n_variants,
        "beam_width": beam_width,
        "meta_rounds_run": len(history),
        "rounds": history,
        "best_level_id": best_lid,
        "best_score": best_score_f,
        "best_round": global_best_round,
        "summary": (
            f"Beam Search {len(history)} 轮（beam_width={beam_width}）"
            f"，最优 score={best_score_f:.2f}（第{global_best_round}轮）"
            f"，beats激活: {global_best.get('beats_activated', 0)}"
        ),
    }
    return ("SUCCEEDED" if best_lid else "FAILED"), result, (None if best_lid else "所有变体注入失败")

# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    register_worker()
    last_hb = time.monotonic()
    while True:
        now = time.monotonic()
        if now - last_hb >= HEARTBEAT_INTERVAL_S:
            heartbeat(); last_hb = now
        try:
            action = poll_action()
        except Exception as e:
            LOGGER.warning("Poll: %s", e); time.sleep(POLL_INTERVAL_S); continue
        if action is None:
            time.sleep(POLL_INTERVAL_S); continue
        action_id = action.get("actionId") or action.get("id")
        action_type = action.get("actionType") or action.get("type", "")
        LOGGER.info("Claimed action_id=%s type=%s", action_id, action_type)
        if action_type != ACTION_TYPE:
            submit_result(action_id, "FAILED", {"reason": f"unsupported:{action_type}"},
                          error=f"unsupported:{action_type}")
            continue
        try:
            with lease_keeper(action_id):
                status, result, error = execute_experiment(action)
            submit_result(action_id, status, result, error)
        except Exception as e:
            LOGGER.exception("execute failed: %s", e)
            submit_result(action_id, "FAILED", {"reason": str(e)}, error=str(e))


if __name__ == "__main__":
    run()
