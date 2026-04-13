from __future__ import annotations

from typing import Any, Dict, List


SEMANTIC_FIELDS: Dict[str, Dict[str, Any]] = {
    "trade": {
        "tokens": [
            "trade",
            "merchant",
            "shop",
            "market",
            "buy",
            "sell",
            "交易",
            "商人",
            "市场",
            "买",
            "卖",
            "货物",
            "商品",
            "集市",
        ],
        "poetic": ["商队", "铃声", "驼队", "货箱", "旅商"],
        "environment": ["帐篷", "车队", "商路"],
        "root": "trade_post",
    },
    "travel": {
        "tokens": [
            "travel",
            "journey",
            "road",
            "wander",
            "旅行",
            "旅途",
            "远方",
            "道路",
            "出发",
        ],
        "poetic": ["风", "脚步", "天际", "沙丘", "地平线"],
        "environment": ["沙漠", "草原", "道路"],
        "root": "road",
    },
    "explore": {
        "tokens": [
            "explore",
            "discover",
            "ruin",
            "cave",
            "探索",
            "遗迹",
            "洞穴",
            "废墟",
            "古城",
        ],
        "poetic": ["尘封", "古老", "失落", "石门", "遗忘"],
        "environment": ["地下", "矿道", "石门"],
        "root": "mine",
    },
}


SEMANTIC_COMBOS: List[Dict[str, Any]] = [
    {
        "requires": {"trade", "travel"},
        "semantic": "caravan_trade",
        "root": "trade_post_caravan_camp",
        "bonus": 2,
    }
]


TOKEN_WEIGHT = 5
POETIC_WEIGHT = 2
ENVIRONMENT_WEIGHT = 1


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_keyword(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    if not token:
        return ""
    return token.replace("-", "_").replace(" ", "_").strip("_")


def _dedupe_keywords(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _normalize_scene_hints(raw_value: Any) -> Dict[str, Any]:
    payload = dict(raw_value) if isinstance(raw_value, dict) else {}
    if not payload:
        return {}

    preferred: List[str] = []
    seen_preferred: set[str] = set()
    for item in payload.get("preferred_semantics") if isinstance(payload.get("preferred_semantics"), list) else []:
        token = _normalize_token(item)
        if not token or token in seen_preferred:
            continue
        seen_preferred.add(token)
        preferred.append(token)

    required: List[str] = []
    seen_required: set[str] = set()
    for item in payload.get("required_semantics") if isinstance(payload.get("required_semantics"), list) else []:
        token = _normalize_token(item)
        if not token or token in seen_required:
            continue
        seen_required.add(token)
        required.append(token)

    fallback_root = _normalize_token(payload.get("fallback_root"))
    theme_override = _normalize_token(payload.get("theme_override"))

    normalized: Dict[str, Any] = {}
    if preferred:
        normalized["preferred_semantics"] = preferred
    if required:
        normalized["required_semantics"] = required
    if fallback_root:
        normalized["fallback_root"] = fallback_root
    if theme_override:
        normalized["theme_override"] = theme_override
    return normalized


def _scene_hints_from_narrative_state(narrative_state: Any) -> Dict[str, Any]:
    state = dict(narrative_state) if isinstance(narrative_state, dict) else {}
    return _normalize_scene_hints(state.get("scene_hints"))


def _theme_default_root(current_theme: str | None) -> str | None:
    normalized_theme = _normalize_token(current_theme)
    if not normalized_theme:
        return None

    try:
        from app.core.themes.theme_loader import get_theme_registry

        registry = get_theme_registry()
        matched = registry.match_theme(normalized_theme) if hasattr(registry, "match_theme") else {}
        allowed_fragments = matched.get("allowed_fragments") if isinstance(matched, dict) and isinstance(matched.get("allowed_fragments"), list) else []
        for fragment_id in allowed_fragments:
            token = _normalize_token(fragment_id)
            if not token:
                continue
            if ":" in token:
                token = token.split(":", 1)[1]
            if token:
                return token
    except Exception:
        pass

    return normalized_theme


def _smart_fallback(
    *,
    scene_hints: Dict[str, Any] | None = None,
    current_theme: str | None = None,
    reason: str | None = None,
) -> Dict[str, Any]:
    hints = _normalize_scene_hints(scene_hints)
    fallback_root = _normalize_token(hints.get("fallback_root")) if hints else ""
    if fallback_root:
        return {
            "semantic": "narrative_fallback",
            "predicted_root": fallback_root,
            "score": 0,
            "all_scores": {},
            "matched_keywords": [],
            "resolution": [],
            "fallback_source": "narrative",
            "reason": str(reason or f"using_narrative_fallback:{fallback_root}"),
        }

    theme_root = _theme_default_root(current_theme)
    if theme_root:
        return {
            "semantic": "theme_fallback",
            "predicted_root": theme_root,
            "score": 0,
            "all_scores": {},
            "matched_keywords": [],
            "resolution": [],
            "fallback_source": "theme",
            "reason": str(reason or f"using_theme_fallback:{theme_root}"),
        }

    return {
        "semantic": "global_fallback",
        "predicted_root": "camp",
        "score": 0,
        "all_scores": {},
        "matched_keywords": [],
        "resolution": [],
        "fallback_source": "global",
        "reason": str(reason or "using_global_fallback"),
    }


def _score_domain(text: str, domain_rule: Dict[str, Any]) -> tuple[int, List[Dict[str, Any]]]:
    total = 0
    hits: List[Dict[str, Any]] = []

    for token in domain_rule.get("tokens") or []:
        normalized = _normalize_keyword(token)
        if normalized and normalized in text:
            total += TOKEN_WEIGHT
            hits.append({"keyword": str(token), "source": "token", "weight": TOKEN_WEIGHT})

    for token in domain_rule.get("poetic") or []:
        normalized = _normalize_keyword(token)
        if normalized and normalized in text:
            total += POETIC_WEIGHT
            hits.append({"keyword": str(token), "source": "poetic", "weight": POETIC_WEIGHT})

    for token in domain_rule.get("environment") or []:
        normalized = _normalize_keyword(token)
        if normalized and normalized in text:
            total += ENVIRONMENT_WEIGHT
            hits.append({"keyword": str(token), "source": "environment", "weight": ENVIRONMENT_WEIGHT})

    return total, hits


def _combo_from_scores(scores: Dict[str, int]) -> Dict[str, Any] | None:
    if not scores:
        return None

    for combo in SEMANTIC_COMBOS:
        required = combo.get("requires")
        if not isinstance(required, set) or not required:
            continue
        if any(scores.get(domain, 0) <= 0 for domain in required):
            continue

        bonus = int(combo.get("bonus") or 0)
        score = sum(int(scores.get(domain, 0)) for domain in required) + max(0, bonus)
        return {
            "semantic": str(combo.get("semantic") or "caravan_trade"),
            "predicted_root": str(combo.get("root") or "trade_post_caravan_camp"),
            "score": score,
        }

    return None


def infer_semantic_from_text(
    text: str | None,
    *,
    narrative_state: Dict[str, Any] | None = None,
    scene_hints: Dict[str, Any] | None = None,
    current_theme: str | None = None,
) -> Dict[str, Any]:
    normalized_text = _normalize_text(text)
    effective_scene_hints = _normalize_scene_hints(scene_hints)
    if not effective_scene_hints:
        effective_scene_hints = _scene_hints_from_narrative_state(narrative_state)

    if not normalized_text:
        return _smart_fallback(
            scene_hints=effective_scene_hints,
            current_theme=current_theme,
            reason="empty_input",
        )

    score_by_domain: Dict[str, int] = {}
    hits_by_domain: Dict[str, List[Dict[str, Any]]] = {}

    for domain, rule in SEMANTIC_FIELDS.items():
        score, hits = _score_domain(normalized_text, rule)
        if score <= 0:
            continue
        score_by_domain[domain] = int(score)
        hits_by_domain[domain] = list(hits)

    if not score_by_domain:
        return _smart_fallback(
            scene_hints=effective_scene_hints,
            current_theme=current_theme,
            reason="no_semantic_match",
        )

    combo = _combo_from_scores(score_by_domain)

    ranked_resolution = sorted(
        (
            {
                "semantic": domain,
                "score": int(score),
                "matches": list(hits_by_domain.get(domain) or []),
            }
            for domain, score in score_by_domain.items()
        ),
        key=lambda row: (-int(row.get("score") or 0), str(row.get("semantic") or "")),
    )

    all_matched_keywords = _dedupe_keywords(
        [
            str(match.get("keyword") or "")
            for rows in hits_by_domain.values()
            for match in rows
            if isinstance(match, dict)
        ]
    )

    if combo:
        combo_result = {
            "semantic": combo["semantic"],
            "predicted_root": combo["predicted_root"],
            "score": int(combo.get("score") or 0),
            "all_scores": dict(score_by_domain),
            "matched_keywords": all_matched_keywords,
            "resolution": ranked_resolution,
        }
        required_semantics = effective_scene_hints.get("required_semantics") if isinstance(effective_scene_hints.get("required_semantics"), list) else []
        if required_semantics:
            matched_semantics = {_normalize_token(tag) for tag in combo.get("semantic", "").split("+") if _normalize_token(tag)}
            matched_semantics.update({_normalize_token(key) for key in score_by_domain.keys() if _normalize_token(key)})
            if any(required not in matched_semantics for required in required_semantics):
                fallback = _smart_fallback(
                    scene_hints=effective_scene_hints,
                    current_theme=current_theme,
                    reason="narrative_constraint",
                )
                fallback["forced_semantics"] = list(required_semantics)
                fallback["matched_semantics"] = sorted(matched_semantics)
                return fallback
        return combo_result

    best_domain = sorted(
        score_by_domain.items(),
        key=lambda row: (-int(row[1]), str(row[0])),
    )[0][0]

    predicted_root = str(SEMANTIC_FIELDS.get(best_domain, {}).get("root") or "camp")
    result = {
        "semantic": best_domain,
        "predicted_root": predicted_root,
        "score": int(score_by_domain.get(best_domain, 0)),
        "all_scores": dict(score_by_domain),
        "matched_keywords": all_matched_keywords,
        "resolution": ranked_resolution,
    }

    required_semantics = effective_scene_hints.get("required_semantics") if isinstance(effective_scene_hints.get("required_semantics"), list) else []
    if required_semantics:
        matched_semantics = {_normalize_token(best_domain)}
        matched_semantics.update({_normalize_token(key) for key in score_by_domain.keys() if _normalize_token(key)})
        if any(required not in matched_semantics for required in required_semantics):
            fallback = _smart_fallback(
                scene_hints=effective_scene_hints,
                current_theme=current_theme,
                reason="narrative_constraint",
            )
            fallback["forced_semantics"] = list(required_semantics)
            fallback["matched_semantics"] = sorted(matched_semantics)
            return fallback

    return result
