"""
experience_debug_store.py — Phase 6: Experience Observability
=============================================================

DebugRecorder: 记录最近10次事件 (per player_id)
  - event_name, prev_state, new_state, triggered_rules, outcome, timestamp
  - 纯内存存储；服务重启后清空（调试工具，不需要持久化）

summarize_progress: 将 state + spec.rules 转化为玩家可读进度说明
"""

from __future__ import annotations

import time
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

MAX_TIMELINE_LEN = 10  # 最近保留条数


# ─────────────────────────────────────────────────────────────────────────────
# DebugEntry — 单次事件记录
# ─────────────────────────────────────────────────────────────────────────────

class DebugEntry:
    __slots__ = (
        "event_name",
        "event_type",
        "quest_event",
        "matched_triggers",
        "state_before",
        "state_after",
        "triggered_rules",
        "rule_evaluation",
        "outcome",
        "ts_ms",
        "level_id",
    )

    def __init__(
        self,
        event_name: str,
        event_type: str,
        quest_event: str,
        matched_triggers: List[str],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        triggered_rules: List[Dict[str, Any]],
        rule_evaluation: List[Dict[str, Any]],
        outcome: Optional[str],
        level_id: str,
    ) -> None:
        self.event_name = event_name
        self.event_type = event_type
        self.quest_event = quest_event
        self.matched_triggers = matched_triggers
        self.state_before = state_before
        self.state_after = state_after
        self.triggered_rules = triggered_rules
        self.rule_evaluation = rule_evaluation
        self.outcome = outcome
        self.ts_ms = int(time.time() * 1000)
        self.level_id = level_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "level_id": self.level_id,
            "event": self.event_name,
            "event_type": self.event_type,
            "quest_event": self.quest_event,
            "matched_trigger": self.matched_triggers[0] if self.matched_triggers else None,
            "matched_triggers": self.matched_triggers,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "triggered_rules": self.triggered_rules,
            "rule_evaluation": self.rule_evaluation,
            "outcome": self.outcome,
        }

    def to_timeline_entry(self) -> Dict[str, Any]:
        """精简版，用于 timeline 数组。"""
        # 只保留业务字段，不含内部元数据 (_last_trigger_*)
        clean_state = {
            k: v
            for k, v in self.state_after.items()
            if not k.startswith("_")
        }
        return {
            "ts_ms": self.ts_ms,
            "event": self.event_name,
            "state": clean_state,
            "outcome": self.outcome,
        }


# ─────────────────────────────────────────────────────────────────────────────
# DebugStore — 每玩家独立的环形缓冲区
# ─────────────────────────────────────────────────────────────────────────────

class ExperienceDebugStore:
    """
    纯内存 debug 记录器。
    线程安全（使用 RLock）；每 player_id 最多保存 MAX_TIMELINE_LEN 条记录。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # player_id → deque[DebugEntry]
        self._timelines: Dict[str, Deque[DebugEntry]] = {}

    def record(
        self,
        player_id: str,
        level_id: str,
        event_type: str,
        payload: Dict[str, Any],
        state_before: Dict[str, Any],
        state_after: Dict[str, Any],
        matched_triggers: List[str],
        triggered_rules: List[Dict[str, Any]],
        rule_evaluation: List[Dict[str, Any]],
        outcome: Optional[str],
    ) -> None:
        """记录一次事件处理结果。"""
        quest_event = str((payload or {}).get("quest_event") or "")
        event_name = quest_event or event_type or "unknown"

        entry = DebugEntry(
            event_name=event_name,
            event_type=str(event_type or ""),
            quest_event=quest_event,
            matched_triggers=list(matched_triggers or []),
            state_before=dict(state_before or {}),
            state_after=dict(state_after or {}),
            triggered_rules=list(triggered_rules or []),
            rule_evaluation=list(rule_evaluation or []),
            outcome=outcome,
            level_id=str(level_id or ""),
        )

        pid = str(player_id or "").strip()
        with self._lock:
            if pid not in self._timelines:
                self._timelines[pid] = deque(maxlen=MAX_TIMELINE_LEN)
            self._timelines[pid].append(entry)

    def get_last_entry(self, player_id: str) -> Optional[DebugEntry]:
        pid = str(player_id or "").strip()
        with self._lock:
            dq = self._timelines.get(pid)
            if dq:
                return dq[-1]
        return None

    def get_timeline(self, player_id: str) -> List[Dict[str, Any]]:
        """返回时间线数组（精简版，供 Player View 使用）。"""
        pid = str(player_id or "").strip()
        with self._lock:
            dq = self._timelines.get(pid)
            if not dq:
                return []
            return [e.to_timeline_entry() for e in dq]

    def get_debug_view(self, player_id: str) -> Optional[Dict[str, Any]]:
        """返回最后一次事件的完整 debug 信息。"""
        entry = self.get_last_entry(player_id)
        if entry is None:
            return None
        return entry.to_dict()

    def get_all_entries(self, player_id: str) -> List[Dict[str, Any]]:
        """返回全部（最多 MAX_TIMELINE_LEN 条）完整事件记录。"""
        pid = str(player_id or "").strip()
        with self._lock:
            dq = self._timelines.get(pid)
            if not dq:
                return []
            return [e.to_dict() for e in dq]

    def clear(self, player_id: str) -> None:
        pid = str(player_id or "").strip()
        with self._lock:
            self._timelines.pop(pid, None)


# 模块级单例
experience_debug_store = ExperienceDebugStore()


# ─────────────────────────────────────────────────────────────────────────────
# Progress Summarizer — 将 state + spec.rules 转化为玩家可读进度
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

_COND_RE = _re.compile(
    r"([a-z_][a-z_0-9]*)\s*(>=|<=|==|>|<|!=)\s*([0-9]+(?:\.[0-9]+)?)",
    _re.IGNORECASE,
)


def _describe_goal(condition: str, var_val: Any) -> Optional[Dict[str, Any]]:
    """
    将单个 win 条件转化为 {goal, current, goal_value, remaining} 四元组。
    目前只处理 var >= N 形式（最常见的收集类目标）。
    """
    matches = _COND_RE.findall(condition)
    if not matches:
        return None

    # 使用第一个可解析的表达式
    var_name, op, threshold_str = matches[0]
    try:
        goal_value = int(float(threshold_str))
    except (TypeError, ValueError):
        return None

    try:
        current = int(float(var_val)) if var_val is not None else 0
    except (TypeError, ValueError):
        current = 0

    remaining = max(0, goal_value - current)
    goal_text = f"{var_name} {op} {goal_value}"
    return {
        "goal": goal_text,
        "current": current,
        "goal_value": goal_value,
        "remaining": remaining,
        "progress_pct": min(100, round(current / goal_value * 100)) if goal_value > 0 else 100,
    }


def summarize_progress(
    state: Dict[str, Any],
    exp_spec: Optional[Dict[str, Any]],
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """
    玩家视角进度摘要。

    返回:
    {
      "status": "in_progress" | "win" | "lose" | "unlock" | "grant",
      "active_rules": [...],
      "progress": {
        "goal": "collected_count >= 3",
        "current": 2,
        "goal_value": 3,
        "remaining": 1,
        "progress_pct": 67
      } | None,
    }
    """
    # 终止状态直接返回
    if outcome in ("win", "lose"):
        return {
            "status": outcome,
            "active_rules": [],
            "progress": None,
        }

    if not isinstance(exp_spec, dict):
        return {"status": "in_progress", "active_rules": [], "progress": None}

    rules = exp_spec.get("rules") or []

    # 找第一个 win 规则作为主要进度目标
    progress_info: Optional[Dict[str, Any]] = None
    active_rules: List[Dict[str, Any]] = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rtype = str(rule.get("type") or "")
        condition = str(rule.get("condition") or "")
        active_rules.append({"type": rtype, "condition": condition, "desc": rule.get("desc", "")})

        if rtype == "win" and progress_info is None:
            # 找 condition 中引用的变量
            matches = _COND_RE.findall(condition)
            if matches:
                var_name = matches[0][0]
                var_val = state.get(var_name)
                progress_info = _describe_goal(condition, var_val)

    status = "in_progress"
    if outcome:
        status = outcome

    return {
        "status": status,
        "active_rules": active_rules,
        "progress": progress_info,
    }


def build_rule_evaluation(
    exp_spec: Optional[Dict[str, Any]],
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    返回每条规则的评估结果列表，用于 debug view。
    [{"rule": "collected_count >= 3", "type": "win", "result": false}, ...]
    """
    if not isinstance(exp_spec, dict):
        return []
    result: List[Dict[str, Any]] = []
    for rule in (exp_spec.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        condition = str(rule.get("condition") or "")
        # 逐个比较子表达式
        matches = _COND_RE.findall(condition)
        evaluated = True
        if not matches:
            evaluated = False
        else:
            for var_name, op, threshold_str in matches:
                var_val = state.get(var_name)
                if var_val is None:
                    evaluated = False
                    break
                try:
                    lhs = float(var_val)
                    rhs = float(threshold_str)
                except (TypeError, ValueError):
                    evaluated = False
                    break
                if op == ">=" and not (lhs >= rhs):
                    evaluated = False; break
                elif op == "<=" and not (lhs <= rhs):
                    evaluated = False; break
                elif op == "==" and not (lhs == rhs):
                    evaluated = False; break
                elif op == ">" and not (lhs > rhs):
                    evaluated = False; break
                elif op == "<" and not (lhs < rhs):
                    evaluated = False; break
                elif op == "!=" and not (lhs != rhs):
                    evaluated = False; break
        result.append({
            "type": rule.get("type"),
            "rule": condition,
            "desc": rule.get("desc", ""),
            "result": evaluated,
        })
    return result
