"""
simulation_engine.py  —  Drift Simulation Engine (Phase 10)
============================================================
可控、可解释的小世界模型 — Monte Carlo 关卡模拟

功能：
  - 从 ExperienceSpec 推导 Action 空间
  - 随机模拟玩家行为 (Monte Carlo, N=200)
  - 评估胜率 / 平均步数 / 失败原因 / 难度
  - 输出人类可读 insights

设计约束：
  ❌ 不使用 RL / 大模型 / 外部依赖
  ✅ 纯 Python 标准库 + 简单概率
"""

from __future__ import annotations

import copy
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 1. Condition Evaluator
#    支持：>= <= > < == != 以及 == true/false (布尔)
# ─────────────────────────────────────────────────────────────────────────────

_OP_RE = re.compile(
    r"^\s*(\w+)\s*(>=|<=|!=|>|<|==)\s*(.+?)\s*$"
)


def _eval_condition(condition: str, state: Dict[str, Any]) -> bool:
    """
    安全地用 state 变量求值 condition 字符串。
    支持：collected_count >= 3  |  guard_detected == true  |  timer <= 0
    永远不使用 eval()。
    """
    m = _OP_RE.match(condition)
    if not m:
        return False
    var, op, rhs = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()

    lval = state.get(var)
    if lval is None:
        return False

    # 将 rhs 转成和 lval 同类型
    rhs_lower = rhs.lower()
    try:
        if isinstance(lval, bool) or rhs_lower in ("true", "false"):
            lval = bool(lval)
            rval: Any = rhs_lower == "true"
        elif isinstance(lval, float) or "." in rhs:
            lval = float(lval)
            rval = float(rhs)
        else:
            lval = int(float(lval))
            rval = int(float(rhs))
    except (ValueError, TypeError):
        return False

    return {
        ">=": lval >= rval,
        "<=": lval <= rval,
        ">":  lval > rval,
        "<":  lval < rval,
        "==": lval == rval,
        "!=": lval != rval,
    }.get(op, False)


def _check_outcome(
    state: Dict[str, Any],
    rules: List[Dict[str, Any]],
) -> Optional[str]:
    """按优先级 lose > win > unlock > grant 检查终止规则。返回 outcome 或 None。"""
    for priority in ("lose", "win", "unlock", "grant"):
        for rule in rules:
            if rule.get("type") != priority:
                continue
            cond = str(rule.get("condition") or "")
            if cond and _eval_condition(cond, state):
                # 顺便记 lose 原因
                if priority == "lose":
                    return "lose:" + re.sub(r"\s+", "_", cond)[:32]
                return priority
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Action Space 推导
#    从 triggers 列表生成可执行动作，固定加入 "idle" / "guard_wanders"
# ─────────────────────────────────────────────────────────────────────────────

def _derive_actions(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    返回列表，每个元素：
    {
        "name": str,
        "weight": float,          # 相对采样概率
        "effects": {var: delta},  # 对 state 的确定性影响
        "trigger_type": str,
    }
    """
    actions: List[Dict[str, Any]] = []
    seen: set = set()

    for trigger in (spec.get("triggers") or []):
        ttype = str(trigger.get("type") or "").strip().lower()
        target = str(trigger.get("target") or "item").strip().lower().replace(" ", "_")
        name = f"{ttype}_{target}" if target and target != "item" else ttype

        if name in seen:
            continue
        seen.add(name)

        effects: Dict[str, Any] = {}
        weight = 1.0

        if ttype == "item_collect":
            # 推断 state 变量：target_count 或 collected_count
            key = f"{target}_count" if target not in ("item", "") else "collected_count"
            effects[key] = 1          # +1
            effects["collected_count"] = 1   # 通用计数
            weight = 2.0              # 主要目标，玩家倾向于捡
        elif ttype == "proximity":
            effects[f"visited_{target}"] = True
            weight = 1.2
        elif ttype == "interact":
            effects[f"interacted_{target}"] = True
            weight = 1.0
        elif ttype == "npc_talk":
            effects[f"talked_to_{target}"] = True
            weight = 0.8
        elif ttype == "timer":
            # timer trigger 不是玩家动作，跳过
            continue

        actions.append({
            "name": name,
            "weight": weight,
            "effects": effects,
            "trigger_type": ttype,
        })

    # 固有动作
    actions.append({"name": "idle",         "weight": 0.5,  "effects": {},                            "trigger_type": "idle"})
    # guard_wanders weight 支持 spec._guard_weight 覆盖（由 spec_optimizer 写入）
    guard_w = float(spec.get("_guard_weight", 0.15))
    actions.append({"name": "guard_wanders","weight": guard_w, "effects": {"guard_detected": True},   "trigger_type": "hazard"})

    return actions


# ─────────────────────────────────────────────────────────────────────────────
# 3. Transition Function
# ─────────────────────────────────────────────────────────────────────────────

def _apply_action(
    state: Dict[str, Any],
    action: Dict[str, Any],
) -> Dict[str, Any]:
    """把 action.effects 叠加到 state 副本并返回。"""
    new_state = copy.copy(state)
    for k, delta in (action.get("effects") or {}).items():
        if isinstance(delta, bool):
            new_state[k] = delta
        elif k in new_state and isinstance(new_state[k], (int, float)):
            new_state[k] = new_state[k] + delta
        elif k not in new_state:
            new_state[k] = delta
    # 每步 timer 自然减少（如果存在）
    if "timer" in new_state and isinstance(new_state["timer"], (int, float)):
        new_state["timer"] = max(0, new_state["timer"] - 1)
    return new_state


# ─────────────────────────────────────────────────────────────────────────────
# 4. Weighted Random Action Sampler (纯标准库，不用 random.choices 的权重版)
# ─────────────────────────────────────────────────────────────────────────────

import random as _random

def _sample_action(
    actions: List[Dict[str, Any]],
    rng: _random.Random,
) -> Dict[str, Any]:
    total = sum(a["weight"] for a in actions)
    r = rng.uniform(0, total)
    cumul = 0.0
    for a in actions:
        cumul += a["weight"]
        if r <= cumul:
            return a
    return actions[-1]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Single Simulation Run
# ─────────────────────────────────────────────────────────────────────────────

MAX_STEPS = 30


def _simulate_once(
    spec: Dict[str, Any],
    actions: List[Dict[str, Any]],
    rng: _random.Random,
    max_steps: int = MAX_STEPS,
) -> Tuple[str, int]:
    """
    模拟一局游戏。
    返回 (outcome, steps)
    outcome ∈ {'win', 'lose:<reason>', 'timeout'}
    """
    state_block = spec.get("state") or {}
    initial = (state_block.get("initial_values") or {}) if isinstance(state_block, dict) else {}
    state = copy.copy(initial)

    # 确保 timer 存在（若 spec 有 timer trigger）
    has_timer_trigger = any(
        str(t.get("type", "")).lower() == "timer" for t in (spec.get("triggers") or [])
    )
    if has_timer_trigger and "timer" not in state:
        duration = 60  # 默认60步
        for t in (spec.get("triggers") or []):
            if str(t.get("type", "")).lower() == "timer":
                duration = int(t.get("duration", 60))
                break
        state["timer"] = duration

    rules = spec.get("rules") or []

    for step in range(1, max_steps + 1):
        action = _sample_action(actions, rng)
        state = _apply_action(state, action)

        outcome = _check_outcome(state, rules)
        if outcome:
            return outcome, step

    return "timeout", max_steps


# ─────────────────────────────────────────────────────────────────────────────
# 6. Monte Carlo Loop  (N runs)
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_many(
    spec: Dict[str, Any],
    n: int = 200,
    seed: Optional[int] = None,
    max_steps: int = MAX_STEPS,
) -> Dict[str, Any]:
    """
    运行 n 局 Monte Carlo 模拟。
    返回原始 results 列表 + aggregate 统计。
    """
    rng = _random.Random(seed)
    actions = _derive_actions(spec)
    results: List[Tuple[str, int]] = []

    for _ in range(n):
        outcome, steps = _simulate_once(spec, actions, rng, max_steps)
        results.append((outcome, steps))

    return _aggregate(results, n, actions)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Aggregate & Evaluate
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate(
    results: List[Tuple[str, int]],
    n: int,
    actions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    wins = sum(1 for o, _ in results if o == "win")
    losses = [(o, s) for o, s in results if o.startswith("lose")]
    timeouts = sum(1 for o, _ in results if o == "timeout")
    all_steps = [s for _, s in results]

    win_rate = round(wins / n, 3)
    avg_steps = round(sum(all_steps) / n, 1)

    # 失败原因统计
    fail_reasons: Dict[str, float] = {}
    for outcome, _ in losses:
        reason = outcome[len("lose:"):] if ":" in outcome else outcome
        fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
    fail_reasons = {k: round(v / n, 3) for k, v in fail_reasons.items()}
    if timeouts:
        fail_reasons["timeout"] = round(timeouts / n, 3)

    # 难度分级
    difficulty = _classify_difficulty(win_rate)

    # Insights
    insights = _generate_insights(win_rate, avg_steps, fail_reasons, results, actions)

    return {
        "win_rate": win_rate,
        "avg_steps": avg_steps,
        "fail_reasons": fail_reasons,
        "difficulty": difficulty,
        "insights": insights,
        "_meta": {
            "n": n,
            "wins": wins,
            "losses": len(losses),
            "timeouts": timeouts,
            "action_space": [a["name"] for a in actions],
        },
    }


def _classify_difficulty(win_rate: float) -> str:
    if win_rate >= 0.75:
        return "easy"
    elif win_rate >= 0.45:
        return "medium"
    elif win_rate >= 0.20:
        return "hard"
    else:
        return "extreme"


def _generate_insights(
    win_rate: float,
    avg_steps: float,
    fail_reasons: Dict[str, float],
    results: List[Tuple[str, int]],
    actions: List[Dict[str, Any]],
) -> List[str]:
    insights: List[str] = []

    # 胜率相关
    if win_rate >= 0.85:
        insights.append("关卡偏简单，玩家几乎必胜，建议提高挑战难度")
    elif win_rate >= 0.60:
        insights.append("胜率适中，关卡平衡性较好")
    elif win_rate >= 0.35:
        insights.append("关卡较有挑战性，适合中等玩家")
    else:
        insights.append("关卡极难，大多数玩家会失败，请检查条件是否过严")

    # 平均步数
    if avg_steps <= 4:
        insights.append(f"平均 {avg_steps} 步即结束，关卡节奏很快")
    elif avg_steps >= 20:
        insights.append(f"平均 {avg_steps} 步，关卡偏长，可能导致玩家疲劳")

    # 失败原因分析
    dominant_fail = max(fail_reasons, key=fail_reasons.get) if fail_reasons else None
    if dominant_fail:
        rate = fail_reasons[dominant_fail]
        if dominant_fail == "timeout":
            insights.append(f"超时是最主要失败原因（{int(rate*100)}%），可考虑延长时限或减少所需步骤")
        elif "guard" in dominant_fail:
            insights.append(f"守卫检测导致 {int(rate*100)}% 的失败，偷越逻辑可能过于随机")
        elif "timer" in dominant_fail:
            insights.append(f"计时器耗尽导致 {int(rate*100)}% 的失败，timer 约束较紧")
        else:
            insights.append(f"主要失败原因是 {dominant_fail}（{int(rate*100)}%）")

    # 步数分布
    win_steps = [s for o, s in results if o == "win"]
    if win_steps:
        early_wins = sum(1 for s in win_steps if s <= 5)
        if early_wins / len(win_steps) > 0.6:
            insights.append("多数胜利在前5步完成 — 赢法路径较短，关卡可能被'速通'")

    # action space 提示
    collectables = [a for a in actions if a["trigger_type"] == "item_collect"]
    if len(collectables) == 0:
        insights.append("关卡没有 item_collect 类型触发器，胜利路径依赖其他触发类型")

    return insights


# ─────────────────────────────────────────────────────────────────────────────
# 8. 公开接口
# ─────────────────────────────────────────────────────────────────────────────

def simulate_experience_spec(
    spec: Dict[str, Any],
    n: int = 200,
    seed: Optional[int] = None,
    max_steps: int = MAX_STEPS,
) -> Dict[str, Any]:
    """
    主入口：接受 experience_spec dict，返回 simulation 结果。

    参数：
        spec      — ExperienceSpec dict（含 rules/triggers/state）
        n         — Monte Carlo 运行次数（默认 200）
        seed      — 随机种子（可选，用于可复现测试）
        max_steps — 每局最大步数（默认 30）

    返回：
        {
          "win_rate": float,
          "avg_steps": float,
          "fail_reasons": {reason: rate},
          "difficulty": "easy|medium|hard|extreme",
          "insights": [str],
          "_meta": {...},
        }
    """
    if not isinstance(spec, dict):
        return _empty_result("invalid_spec")

    has_rules = bool(spec.get("rules"))
    if not has_rules:
        return _empty_result("no_rules")

    try:
        t0 = time.monotonic()
        result = _simulate_many(spec, n=n, seed=seed, max_steps=max_steps)
        result["_meta"]["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return result
    except Exception as exc:
        return _empty_result(f"error:{exc}")


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "win_rate": None,
        "avg_steps": None,
        "fail_reasons": {},
        "difficulty": "unknown",
        "insights": [f"无法模拟：{reason}"],
        "_meta": {"error": reason},
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. 内置测试样例（宝石关卡）
# ─────────────────────────────────────────────────────────────────────────────

GEM_LEVEL_SPEC = {
    "rules": [
        {"type": "win",  "condition": "collected_count >= 3", "desc": "收集3个宝石"},
        {"type": "lose", "condition": "guard_detected == true", "desc": "被守卫发现"},
        {"type": "lose", "condition": "timer <= 0", "desc": "时间耗尽"},
    ],
    "triggers": [
        {"type": "item_collect", "target": "gem",   "action": "collect", "desc": "捡宝石"},
        {"type": "proximity",    "target": "altar",  "action": "enter",   "desc": "靠近祭坛"},
    ],
    "state": {
        "variables": {"collected_count": "type_int", "timer": "type_int", "guard_detected": "type_bool"},
        "initial_values": {"collected_count": 0, "timer": 20, "guard_detected": False},
    },
}


def run_gem_level_test() -> Dict[str, Any]:
    """开箱即用的宝石关卡测试。"""
    return simulate_experience_spec(GEM_LEVEL_SPEC, n=300, seed=42)


if __name__ == "__main__":
    import json as _json
    print("=== 宝石关卡模拟测试 ===")
    result = run_gem_level_test()
    print(_json.dumps(result, ensure_ascii=False, indent=2))
