from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


def _normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return token.replace("-", "_").replace(" ", "_").strip("_")


def _normalize_scene_hints(raw_value: Any) -> Dict[str, Any]:
    if not isinstance(raw_value, dict):
        return {}

    preferred: List[str] = []
    seen_preferred: set[str] = set()
    for item in raw_value.get("preferred_semantics") if isinstance(raw_value.get("preferred_semantics"), list) else []:
        token = _normalize_token(item)
        if not token or token in seen_preferred:
            continue
        seen_preferred.add(token)
        preferred.append(token)

    required: List[str] = []
    seen_required: set[str] = set()
    for item in raw_value.get("required_semantics") if isinstance(raw_value.get("required_semantics"), list) else []:
        token = _normalize_token(item)
        if not token or token in seen_required:
            continue
        seen_required.add(token)
        required.append(token)

    fallback_root = _normalize_token(raw_value.get("fallback_root"))
    theme_override = _normalize_token(raw_value.get("theme_override"))

    hints: Dict[str, Any] = {}
    if preferred:
        hints["preferred_semantics"] = list(preferred)
    if required:
        hints["required_semantics"] = list(required)
    if fallback_root:
        hints["fallback_root"] = fallback_root
    if theme_override:
        hints["theme_override"] = theme_override
    return hints


@dataclass
class NarrativeTransitionCandidate:
    node: str
    requires: List[str] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    satisfied: bool = False
    scene_hints: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.node = _normalize_token(self.node)
        self.requires = [_normalize_token(item) for item in self.requires if _normalize_token(item)]
        self.blocked_by = [_normalize_token(item) for item in self.blocked_by if _normalize_token(item)]
        self.satisfied = bool(self.satisfied)
        self.scene_hints = _normalize_scene_hints(self.scene_hints)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "requires": list(self.requires),
            "blocked_by": list(self.blocked_by),
            "satisfied": bool(self.satisfied),
            "scene_hints": dict(self.scene_hints),
        }


@dataclass
class NarrativeState:
    version: str = "narrative_state_v1"
    graph_version: str = "p8a_v1"
    current_arc: str = "main"
    current_node: str = ""
    unlocked_nodes: List[str] = field(default_factory=list)
    completed_nodes: List[str] = field(default_factory=list)
    transition_candidates: List[NarrativeTransitionCandidate] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)
    observed_signals: List[str] = field(default_factory=list)
    scene_hints: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.version = str(self.version or "narrative_state_v1").strip() or "narrative_state_v1"
        self.graph_version = str(self.graph_version or "p8a_v1").strip() or "p8a_v1"
        self.current_arc = _normalize_token(self.current_arc) or "main"
        self.current_node = _normalize_token(self.current_node)

        self.unlocked_nodes = [_normalize_token(item) for item in self.unlocked_nodes if _normalize_token(item)]
        self.completed_nodes = [_normalize_token(item) for item in self.completed_nodes if _normalize_token(item)]
        self.blocked_by = [_normalize_token(item) for item in self.blocked_by if _normalize_token(item)]
        self.observed_signals = sorted({
            _normalize_token(item)
            for item in self.observed_signals
            if _normalize_token(item)
        })
        self.scene_hints = _normalize_scene_hints(self.scene_hints)

        normalized_candidates: List[NarrativeTransitionCandidate] = []
        for candidate in self.transition_candidates:
            if isinstance(candidate, NarrativeTransitionCandidate):
                normalized_candidates.append(candidate)
                continue
            if isinstance(candidate, dict):
                normalized_candidates.append(
                    NarrativeTransitionCandidate(
                        node=str(candidate.get("node") or ""),
                        requires=list(candidate.get("requires") or []),
                        blocked_by=list(candidate.get("blocked_by") or []),
                        satisfied=bool(candidate.get("satisfied")),
                        scene_hints=dict(candidate.get("scene_hints") or {}),
                    )
                )
        self.transition_candidates = normalized_candidates

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "graph_version": self.graph_version,
            "current_arc": self.current_arc,
            "current_node": self.current_node,
            "unlocked_nodes": list(self.unlocked_nodes),
            "completed_nodes": list(self.completed_nodes),
            "transition_candidates": [candidate.to_dict() for candidate in self.transition_candidates],
            "blocked_by": list(self.blocked_by),
            "observed_signals": list(self.observed_signals),
            "scene_hints": dict(self.scene_hints),
        }
