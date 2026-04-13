"""
experience_design_parser.py — Phase 7: Experience Authoring System
===================================================================
将玩家/设计师的自然语言文本解析为结构化 DesignSpec，
再通过 to_experience_spec() 转换为 Runtime 可执行的 ExperienceSpec。

转换链路：
    DesignText (自然语言)
        ↓  parse_design_text()
    DesignSpec (结构清晰)
        ↓  to_experience_spec()
    ExperienceSpec (Runtime 可执行)
        ↓  already-existing runtime
    Runtime (Phase 5)

设计原则：
- 无 LLM 依赖（纯规则 + 正则提取）
- 对缺失字段产出 warning 而非静默失败
- 不修改 experience_runtime / experience_spec_compiler
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 数字工具
# ─────────────────────────────────────────────────────────────────────────────
_CN_DIGIT_MAP: Dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_to_int(s: str) -> Optional[int]:
    """将简单中文/阿拉伯数字（0-99）转为整型。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN_DIGIT_MAP:
        return _CN_DIGIT_MAP[s]
    if s == "十":
        return 10
    # 二十一 ~ 九十九
    m = re.match(r"^([一二三四五六七八九])十([一二三四五六七八九]?)$", s)
    if m:
        tens = _CN_DIGIT_MAP[m.group(1)] * 10
        ones = _CN_DIGIT_MAP.get(m.group(2), 0) if m.group(2) else 0
        return tens + ones
    return None


# ─────────────────────────────────────────────────────────────────────────────
# DesignSpec 数据结构
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TriggerSpec:
    """一条触发器规则: 事件 → 动作"""
    event: str
    action: str
    raw: str = ""
    trigger_type: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "action": self.action,
            "raw": self.raw,
            "trigger_type": self.trigger_type,
        }


@dataclass
class DesignSpec:
    """
    玩家可理解的游戏设计规格（Design DSL 中间结构）。

    对应 JSON schema:
    {
      "goal": "collect 3 gems",
      "win_condition": "collected_count >= 3",
      "lose_condition": "timer <= 0",
      "triggers": [{"event": "collect gem", "action": "collected_count +1", ...}],
      "time_limit": 60,
      "state_vars": {"collected_count": 0, "timer": 60}
    }
    """
    goal: str = ""
    win_condition: str = ""
    lose_condition: str = ""
    triggers: List[TriggerSpec] = field(default_factory=list)
    time_limit: Optional[int] = None
    state_vars: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "win_condition": self.win_condition,
            "lose_condition": self.lose_condition,
            "triggers": [t.to_dict() for t in self.triggers],
            "time_limit": self.time_limit,
            "state_vars": self.state_vars,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 提取工具 — 时间限制
# ─────────────────────────────────────────────────────────────────────────────
_TIMER_PATS = [
    re.compile(r"限时\s*([零一二两三四五六七八九十百千\d]+)\s*(秒|分钟|分)", re.I),
    re.compile(r"([零一二两三四五六七八九十百千\d]+)\s*(秒|分钟|分)\s*(?:内|完成|通关|限制)", re.I),
    re.compile(r"(\d+)\s*(?:seconds?|minutes?)\s*(?:limit|time)", re.I),
]


def _extract_time_limit(text: str) -> Optional[int]:
    for pat in _TIMER_PATS:
        m = pat.search(text)
        if m:
            n = _cn_to_int(m.group(1))
            if n is None:
                continue
            unit = m.group(2) if len(m.groups()) >= 2 else "秒"
            if "分" in unit or "min" in unit.lower():
                return n * 60
            return n
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 提取工具 — 目标
# ─────────────────────────────────────────────────────────────────────────────
_GOAL_PATS = [
    re.compile(r"(?:玩家需要|玩家必须|你需要|你必须|目标[是：:])(.{4,40}?)(?:[。！？才]|$)"),
    re.compile(r"(?:任务[是：:]|任务目标[是：:]|关卡目标[是：:])(.{4,40}?)(?:[。！？]|$)"),
    re.compile(r"(?:goal\s*[：:])(.{4,80}?)(?:[。！？\n]|$)", re.I),
]
_GOAL_STARTS = ("收集", "获得", "到达", "找到", "解锁", "完成", "击败",
                "collect", "find", "reach", "unlock", "defeat")


def _extract_goal(text: str) -> str:
    for pat in _GOAL_PATS:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    # 回退：第一句中找动宾短语
    first = re.split(r"[。！？\n]", text)[0]
    for kw in _GOAL_STARTS:
        idx = first.find(kw)
        if idx >= 0:
            return first[idx:idx + 30].strip()
    return text[:40].strip()


# ─────────────────────────────────────────────────────────────────────────────
# 提取工具 — 胜利条件
# ─────────────────────────────────────────────────────────────────────────────
_COLLECT_PAT = re.compile(
    r"(?:收集|捡起|拾取|找到|获取|gather|collect)\s*"
    r"([零一二两三四五六七八九十\d]+)?\s*"
    r"(?:[个块颗枚件只]?)\s*"
    r"([\u4e00-\u9fff]{1,3}|[a-zA-Z]{1,12})"
    r"(?=[，,。！？\s才则就后可]|才能|$)"
)
_WIN_KEYWORDS = ("赢", "胜利", "通关", "完成", "成功", "win", "complete", "success")


def _extract_win_condition(text: str) -> Tuple[str, Optional[str]]:
    """
    Returns (condition_str, item_name_or_None).
    e.g. ("collected_count >= 3", "宝石")
    """
    # 优先：收集 N 个 item
    for m in _COLLECT_PAT.finditer(text):
        cnt_str = m.group(1)
        item = (m.group(2) or "").strip()
        if cnt_str:
            count = _cn_to_int(cnt_str)
            if count and count > 0:
                return f"collected_count >= {count}", item
        # 有 item 无数量 → 至少1个
        if item:
            return "collected_count >= 1", item

    # 到达类
    reach_m = re.search(
        r"(?:到达|找到|进入|抵达|reach|arrive)[^，,。！？]{0,3}"
        r"([\u4e00-\u9fff]{2,6}|[a-zA-Z ]{2,12})"
        r".{0,10}(?:才能赢|才能通关|才能完成|胜利|win)", text
    )
    if reach_m:
        target = reach_m.group(1).strip()
        safe = re.sub(r"[^\w]", "_", target)
        return f"reached_{safe} == True", None

    # 通用关键词
    for kw in _WIN_KEYWORDS:
        if kw in text:
            return "goal_achieved == True", None

    return "", None


# ─────────────────────────────────────────────────────────────────────────────
# 提取工具 — 失败条件
# ─────────────────────────────────────────────────────────────────────────────
_GUARD_PATS = [
    re.compile(r"(?:被|遭)?(?:守卫|卫兵|guard|enemy|敌人|怪物|monster)(?:发现|察觉|看到|spotted|detected|detect)", re.I),
    re.compile(r"(?:被发现|被察觉|被看到|get caught|spotted)"),
]
_LOSE_KEYWORDS = ("输", "失败", "死亡", "game over", "被发现", "终结", "fail", "lose")


def _extract_lose_condition(text: str, time_limit: Optional[int]) -> str:
    # 有时间限制 → 自动产出 timer
    if time_limit is not None:
        return "timer <= 0"
    # 守卫/发现
    for pat in _GUARD_PATS:
        if pat.search(text):
            return "guard_detected == True"
    # 死亡
    if re.search(r"(?:死亡|被击败|player_dead|hp\s*<=\s*0|血量为0)", text, re.I):
        return "player_alive == False"
    # 通用失败词
    for kw in _LOSE_KEYWORDS:
        if kw in text.lower():
            return "player_failed == True"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 提取工具 — 触发器
# ─────────────────────────────────────────────────────────────────────────────
_ARROW_PAT = re.compile(
    r"(.{2,30}?)\s*(?:→|->|⇒)\s*(.{2,40}?)(?:[。！？\n,，]|$)"
)
_PROXIMITY_PAT = re.compile(
    r"(?:靠近|走近|进入|踩到|触碰|接触|approach|enter|near)\s*"
    r"([\u4e00-\u9fff]{1,3}|[a-zA-Z]{1,15})"
    r"(?=[，,。！？\s可才则就后]|可以|才能|$)"
)


def _classify_trigger_type(event: str) -> str:
    event_l = event.lower()
    if any(kw in event_l for kw in ("collect", "收集", "捡", "拾", "pick")):
        return "item_collect"
    if any(kw in event_l for kw in ("enter", "approach", "near", "靠近", "进入", "走近")):
        return "proximity"
    if any(kw in event_l for kw in ("talk", "dialogue", "对话", "交谈", "询问")):
        return "npc_talk"
    if any(kw in event_l for kw in ("timer", "时间", "倒计时", "countdown", "tick")):
        return "timer"
    if any(kw in event_l for kw in ("guard", "守卫", "卫兵", "detect", "发现")):
        return "proximity"
    return "unknown"


def _normalize_action(event: str, action_raw: str) -> str:
    """将自然语言动作映射到结构化动作字符串。"""
    al = action_raw.lower()
    if any(kw in al for kw in ("+1", "增加", "increment", "++")):
        if any(kw in event.lower() for kw in ("collect", "收集", "捡", "pick")):
            return "collected_count +1"
        return "count +1"
    if any(kw in al for kw in ("解锁", "unlock", "open", "打开", "开门")):
        return "door_unlocked = True"
    if any(kw in al for kw in ("失败", "game over", "输", "结束", "lose", "fail")):
        return "game_over"
    if any(kw in al for kw in ("奖励", "reward", "获得")):
        return "reward_granted = True"
    return action_raw[:40]


def _extract_triggers(
    text: str,
    time_limit: Optional[int],
    win_item: Optional[str],
) -> List[TriggerSpec]:
    triggers: List[TriggerSpec] = []
    seen: set = set()

    def _add(t: TriggerSpec) -> None:
        key = t.event[:20]
        if key not in seen:
            seen.add(key)
            triggers.append(t)

    # 1. 显式箭头: A → B
    for m in _ARROW_PAT.finditer(text):
        ev_raw = m.group(1).strip()
        ac_raw = m.group(2).strip()
        t_type = _classify_trigger_type(ev_raw)
        action = _normalize_action(ev_raw, ac_raw)
        _add(TriggerSpec(
            event=ev_raw,
            action=action,
            raw=m.group(0).strip(),
            trigger_type=t_type,
        ))

    # 2. 隐式收集: 收集/捡起 + [数量] + item
    for m in _COLLECT_PAT.finditer(text):
        item = (m.group(2) or win_item or "item").strip()
        event = f"collect {item}"
        _add(TriggerSpec(
            event=event,
            action="collected_count +1",
            raw=m.group(0).strip(),
            trigger_type="item_collect",
        ))

    # 3. 隐式靠近: 靠近/进入 + target
    for m in _PROXIMITY_PAT.finditer(text):
        target = m.group(1).strip()
        if not target:
            continue
        event = f"enter {target}"
        # 从上下文推断动作
        ctx = text[max(0, m.start() - 5): m.end() + 40]
        if any(kw in ctx for kw in ("奖励", "reward", "得到")):
            action = "reward_granted = True"
        elif any(kw in ctx for kw in ("解锁", "开门", "unlock")):
            action = "door_unlocked = True"
        else:
            action = "activate_event"
        _add(TriggerSpec(
            event=event,
            action=action,
            raw=m.group(0).strip(),
            trigger_type="proximity",
        ))

    # 4. 隐式守卫触发器
    for pat in _GUARD_PATS:
        if pat.search(text):
            _add(TriggerSpec(
                event="guard_detect",
                action="guard_detected = True",
                raw="被守卫发现",
                trigger_type="proximity",
            ))
            break

    # 5. 计时器（有时间限制时自动生成）
    if time_limit:
        _add(TriggerSpec(
            event="timer_tick",
            action="timer -1",
            raw=f"限时{time_limit}秒",
            trigger_type="timer",
        ))

    return triggers[:8]


# ─────────────────────────────────────────────────────────────────────────────
# 状态变量推断
# ─────────────────────────────────────────────────────────────────────────────

def _infer_state_vars(
    win_cond: str,
    lose_cond: str,
    triggers: List[TriggerSpec],
    time_limit: Optional[int],
) -> Dict[str, Any]:
    vars_: Dict[str, Any] = {}

    def _parse_cond(cond: str) -> None:
        m = re.match(r"(\w+)\s*(>=|<=|==|>|<|!=)\s*(.+)", (cond or "").strip())
        if not m:
            return
        var, _, val = m.group(1), m.group(2), m.group(3).strip()
        if var in vars_:
            return
        if val.lstrip("-").isdigit():
            # timer starts at time_limit, counters start at 0
            vars_[var] = time_limit if (var == "timer" and time_limit) else 0
        elif val.lower() in ("true", "false"):
            vars_[var] = False
        else:
            vars_[var] = ""

    _parse_cond(win_cond)
    _parse_cond(lose_cond)

    # 从 trigger actions 补充
    for t in triggers:
        act = t.action
        # "var +1" / "var -1"
        m = re.match(r"(\w+)\s*[+-]1$", act)
        if m and m.group(1) not in vars_:
            vars_[m.group(1)] = 0
        # "var = True/False"
        m = re.match(r"(\w+)\s*=\s*(True|False)", act)
        if m and m.group(1) not in vars_:
            vars_[m.group(1)] = m.group(2) == "False"  # initial = opposite

    return vars_


# ─────────────────────────────────────────────────────────────────────────────
# 主解析函数
# ─────────────────────────────────────────────────────────────────────────────

def parse_design_text(text: str) -> DesignSpec:
    """
    将玩家自然语言输入解析为结构化 DesignSpec。

    支持：
    - 海龟汤式长文本
    - 桌游规则式条文
    - 简短目标描述
    - 混合中英文
    - 显式箭头 DSL: "A → B"

    Returns:
        DesignSpec 实例。空字段通过 generate_warnings() 提示。
    """
    normalized = (text or "").strip()
    if not normalized:
        return DesignSpec(raw_text="")

    time_limit = _extract_time_limit(normalized)
    goal = _extract_goal(normalized)
    win_condition, win_item = _extract_win_condition(normalized)
    lose_condition = _extract_lose_condition(normalized, time_limit)
    triggers = _extract_triggers(normalized, time_limit, win_item)
    state_vars = _infer_state_vars(win_condition, lose_condition, triggers, time_limit)

    return DesignSpec(
        goal=goal,
        win_condition=win_condition,
        lose_condition=lose_condition,
        triggers=triggers,
        time_limit=time_limit,
        state_vars=state_vars,
        raw_text=normalized,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 转换链路：DesignSpec → ExperienceSpec
# ─────────────────────────────────────────────────────────────────────────────

def to_experience_spec(design: DesignSpec) -> Dict[str, Any]:
    """
    将 DesignSpec 转换为 Runtime 可执行的 ExperienceSpec。

    此函数是 Phase 7 的唯一 DesignSpec→Runtime 桥接点。
    不允许直接传自然语言文本给 Runtime。
    """
    rules: List[Dict[str, Any]] = []
    if design.win_condition:
        rules.append({
            "type": "win",
            "condition": design.win_condition,
            "desc": design.goal or "达成胜利条件",
        })
    if design.lose_condition:
        rules.append({
            "type": "lose",
            "condition": design.lose_condition,
            "desc": "失败条件触发",
        })

    triggers: List[Dict[str, Any]] = []
    for t in design.triggers:
        triggers.append({
            "type": t.trigger_type,
            "target": t.event,
            "action": t.action,
            "desc": t.raw or t.event,
        })

    # 构建状态区
    state_variables: Dict[str, str] = {}
    state_initial: Dict[str, Any] = {}
    for var, initial_val in design.state_vars.items():
        if isinstance(initial_val, bool):
            state_variables[var] = "bool"
            state_initial[var] = initial_val
        elif isinstance(initial_val, int):
            state_variables[var] = "int"
            state_initial[var] = initial_val
        else:
            state_variables[var] = "string"
            state_initial[var] = str(initial_val)

    # timer 特殊初始值
    if design.time_limit and "timer" in state_variables:
        state_initial["timer"] = design.time_limit

    return {
        "spec_version": "1.0",
        "scene_class": "CONTENT",
        "rules": rules,
        "triggers": triggers,
        "state": {
            "variables": state_variables,
            "initial_values": state_initial,
        },
        "npc_hints": [],
        "compiler_mode": "design_parser",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 警告生成
# ─────────────────────────────────────────────────────────────────────────────

def generate_warnings(design: DesignSpec) -> List[str]:
    """
    检查 DesignSpec 完整性，返回 warning 列表。

    强制约束（见 Phase 7 spec）：
    - 缺失 trigger 必须 warning
    - win_condition 不可解析必须 warning
    - ExperienceSpec 不允许为空结构
    """
    warnings: List[str] = []

    if not design.goal:
        warnings.append(
            "missing goal: 未检测到目标描述，请说明玩家需要做什么"
        )

    if not design.win_condition:
        warnings.append(
            "missing win_condition: 未检测到胜利条件，"
            "请描述如何获胜（如：收集3个宝石）"
        )
    else:
        if not re.match(r"\w+\s*(>=|<=|==|>|<|!=)\s*.+", design.win_condition):
            warnings.append(
                f"unparseable win_condition: '{design.win_condition}' 格式不规范，"
                f"期望如 'collected_count >= 3'"
            )

    if not design.triggers:
        warnings.append(
            "missing triggers: 未检测到任何触发器，"
            "请描述会发生什么事件（如：收集宝石、靠近祭坛）"
        )
    else:
        # 检查 triggers 是否覆盖 win_condition 变量
        if design.win_condition:
            m = re.match(r"(\w+)\s*(>=|<=|==|>|<)", design.win_condition)
            if m:
                target_var = m.group(1)
                covered = any(
                    target_var in t.action or target_var in t.event
                    for t in design.triggers
                )
                if not covered:
                    warnings.append(
                        f"missing trigger for {target_var}: "
                        f"胜利条件依赖 '{target_var}' 但未找到能修改该变量的触发器，"
                        f"请添加如 'collect item → {target_var} +1' 的触发器"
                    )

    # 失败条件（可选，但如有暗示则 warn）
    if not design.lose_condition and not design.time_limit:
        fail_hints = ("失败", "输", "game over", "死亡",
                      "发现", "limit", "timer", "时间", "lose", "fail")
        if any(h in design.raw_text.lower() for h in fail_hints):
            warnings.append(
                "missing lose_condition: 文本包含失败暗示但未解析到失败条件"
            )

    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# 完整性校验
# ─────────────────────────────────────────────────────────────────────────────

def validate_design_spec(design: DesignSpec) -> Tuple[List[str], float]:
    """
    校验 DesignSpec 并计算完整性分数（0.0 ~ 1.0）。

    Scoring:
      goal non-empty              → +0.15
      win_condition parseable     → +0.25  (partial +0.10 if present but bad fmt)
      triggers present            → +0.20
      trigger covers win var      → +0.15  (+0.05 if no win_condition to check)
      lose_condition or time_limit→ +0.15
      state_vars non-empty        → +0.10

    Returns:
        (issues_list, completeness_score_0_to_1)
    """
    issues: List[str] = []
    score = 0.0

    # goal
    if design.goal:
        score += 0.15
    else:
        issues.append("goal 为空：未描述玩家目标")

    # win_condition
    win_parseable = bool(design.win_condition) and bool(
        re.match(r"\w+\s*(>=|<=|==|>|<|!=)\s*.+", design.win_condition)
    )
    if win_parseable:
        score += 0.25
    elif design.win_condition:
        score += 0.10
        issues.append(f"win_condition '{design.win_condition}' 格式不规范")
    else:
        issues.append("win_condition 为空：缺少胜利条件")

    # triggers
    if design.triggers:
        score += 0.20
        # 覆盖检查
        if design.win_condition:
            m = re.match(r"(\w+)\s*(>=|<=|==|>|<)", design.win_condition)
            if m:
                target_var = m.group(1)
                covered = any(
                    target_var in t.action or target_var in t.event
                    for t in design.triggers
                )
                if covered:
                    score += 0.15
                else:
                    issues.append(f"无触发器覆盖变量: {target_var}")
            else:
                score += 0.05
        else:
            score += 0.05
    else:
        issues.append("没有任何触发器")

    # lose_condition / time_limit
    if design.lose_condition or design.time_limit is not None:
        score += 0.15
    else:
        issues.append("缺少失败条件或时间限制（可选但建议填写）")

    # state_vars
    if design.state_vars:
        score += 0.10
    else:
        issues.append("未推断出任何状态变量")

    return issues, round(min(score, 1.0), 2)
