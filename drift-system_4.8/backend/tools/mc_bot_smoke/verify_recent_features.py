import json
from typing import Any, Dict

import requests

BASE = "http://127.0.0.1:8000/world"
PLAYER_ID = "FeatureBot"

SESSION = requests.Session()
SESSION.trust_env = False


def _get(path: str) -> Dict[str, Any]:
    resp = SESSION.get(f"{BASE}{path}", timeout=20)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    resp = SESSION.post(f"{BASE}{path}", json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _print_block(title: str, payload: Dict[str, Any]) -> None:
    print(f"--- {title} ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    start = _post("/story/start", {"player_id": PLAYER_ID, "level_id": "flagship_01"})
    _print_block(
        "story_start",
        {
            "status": start.get("status"),
            "level_id": start.get("level_id"),
            "has_world_patch": bool(start.get("world_patch")),
        },
    )

    state0 = _get(f"/state/{PLAYER_ID}")
    _print_block(
        "state0.narrative",
        {
            "current_node": state0.get("current_node"),
            "scene_hints": state0.get("scene_hints"),
        },
    )

    spawn = _post(
        f"/story/{PLAYER_ID}/spawnfragment",
        {"scene_theme": "village", "scene_hint": "village"},
    )
    _print_block(
        "spawnfragment",
        {
            "status": spawn.get("status"),
            "fragment_count": spawn.get("fragment_count"),
            "fallback": spawn.get("fallback"),
            "scene_theme": spawn.get("scene_theme"),
            "scene_hint": spawn.get("scene_hint"),
        },
    )

    choose1 = _post(f"/story/{PLAYER_ID}/narrative/choose", {"mode": "auto_best"})
    _print_block(
        "choose1",
        {
            "status": choose1.get("status"),
            "current_node": choose1.get("current_node"),
            "narrative_decision": choose1.get("narrative_decision"),
            "transition_candidates": choose1.get("transition_candidates"),
        },
    )

    rule_event = _post(
        "/story/rule-event",
        {"player_id": PLAYER_ID, "event_type": "found_rune", "payload": {}},
    )
    _print_block("rule_event_found_rune", {"status": rule_event.get("status")})

    choose2 = _post(f"/story/{PLAYER_ID}/narrative/choose", {"mode": "auto_best"})
    _print_block(
        "choose2",
        {
            "status": choose2.get("status"),
            "current_node": choose2.get("current_node"),
            "narrative_decision": choose2.get("narrative_decision"),
            "transition_candidates": choose2.get("transition_candidates"),
            "scene_hints": (choose2.get("narrative_state") or {}).get("scene_hints"),
        },
    )

    _post(
        "/story/rule-event",
        {"player_id": PLAYER_ID, "event_type": "talk", "payload": {"text": "qwerty asdfgh"}},
    )

    prediction_resp = _get(f"/story/{PLAYER_ID}/predict_scene")
    prediction = prediction_resp.get("prediction") if isinstance(prediction_resp, dict) else {}

    report = {
        "predicted_root": prediction.get("predicted_root"),
        "predicted_root_hint": prediction.get("predicted_root_hint"),
        "semantic": prediction.get("semantic"),
        "semantic_fallback_source": prediction.get("semantic_fallback_source"),
        "semantic_reason": prediction.get("semantic_reason"),
        "scene_hints": prediction.get("scene_hints"),
        "scene_hints_theme_override": prediction.get("scene_hints_theme_override"),
        "effective_scene_hint": prediction.get("effective_scene_hint"),
        "candidate_scores": prediction.get("candidate_scores"),
    }
    _print_block("predict_scene", report)

    scene_hints = prediction.get("scene_hints") if isinstance(prediction.get("scene_hints"), dict) else {}
    fallback_root = scene_hints.get("fallback_root")

    checks = {
        "has_scene_hints": bool(scene_hints),
        "fallback_source_is_narrative": prediction.get("semantic_fallback_source") == "narrative",
        "root_hint_matches_scene_hints_fallback": bool(fallback_root)
        and prediction.get("predicted_root_hint") == fallback_root,
        "has_theme_override": bool(prediction.get("scene_hints_theme_override")),
    }
    _print_block("checks", checks)

    all_pass = all(checks.values())
    print("ALL_PASS", all_pass)
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
