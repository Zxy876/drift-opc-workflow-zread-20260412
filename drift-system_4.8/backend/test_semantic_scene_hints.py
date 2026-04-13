"""Regression tests for narrative scene_hints and fallback behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.narrative.semantic_engine import infer_semantic_from_text
from app.core.narrative.scene_assembler import assemble_scene


class SemanticSceneHintsTests(unittest.TestCase):
    def test_empty_text_prefers_narrative_fallback_root(self):
        result = infer_semantic_from_text(
            "",
            scene_hints={
                "fallback_root": "shrine",
                "required_semantics": ["temple"],
            },
            current_theme="camp",
        )

        self.assertEqual(result.get("semantic"), "narrative_fallback")
        self.assertEqual(result.get("predicted_root"), "shrine")
        self.assertEqual(result.get("fallback_source"), "narrative")

    def test_required_semantics_mismatch_triggers_constraint_fallback(self):
        result = infer_semantic_from_text(
            "我想去远方旅行",
            scene_hints={
                "required_semantics": ["temple"],
                "fallback_root": "shrine",
            },
            current_theme="camp",
        )

        self.assertEqual(result.get("semantic"), "narrative_fallback")
        self.assertEqual(result.get("predicted_root"), "shrine")
        self.assertEqual(result.get("reason"), "narrative_constraint")
        self.assertIn("temple", result.get("forced_semantics", []))

    def test_no_semantic_match_uses_theme_fallback_before_global(self):
        with patch("app.core.narrative.semantic_engine._theme_default_root", return_value="forge"):
            result = infer_semantic_from_text(
                "qwerty asdfgh",
                scene_hints=None,
                current_theme="village",
            )

        self.assertEqual(result.get("semantic"), "theme_fallback")
        self.assertEqual(result.get("predicted_root"), "forge")
        self.assertEqual(result.get("fallback_source"), "theme")


class SceneAssemblerThemeOverrideTests(unittest.TestCase):
    def test_theme_override_takes_precedence(self):
        with patch(
            "app.core.narrative.scene_assembler.select_fragments_with_debug",
            return_value={
                "fragments": ["shrine_core"],
                "scene_graph": {"root": "shrine"},
                "layout": {"nodes": []},
                "debug": {},
            },
        ) as mocked_select, patch(
            "app.core.narrative.scene_assembler.build_event_plan",
            return_value=[{"event_id": "spawn_shrine", "type": "spawn"}],
        ):
            result = assemble_scene(
                inventory_state={"player_id": "tester", "resources": {}},
                story_theme="camp",
                theme_override="knowledge_temple",
                scene_hint="temple",
            )

        self.assertEqual(result.get("story_theme"), "knowledge_temple")
        self.assertEqual(result.get("requested_story_theme"), "camp")
        self.assertEqual(result.get("theme_override"), "knowledge_temple")

        # Ensure fragment selection received the override theme.
        self.assertTrue(mocked_select.called)
        _, kwargs = mocked_select.call_args
        self.assertEqual(kwargs.get("scene_hint"), "temple")
        args = mocked_select.call_args.args
        self.assertGreaterEqual(len(args), 2)
        self.assertEqual(args[1], "knowledge_temple")


if __name__ == "__main__":
    unittest.main()
