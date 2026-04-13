"""
tests/test_drift_refresh_worker.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for drift_refresh_worker/worker.py
Tests cover:
  - _extract_fields: normal, missing fields, raw string, empty
  - call_story_refresh: success, HTTP error path
  - call_progress_notify: success, failure (non-fatal)
  - Full worker loop: action claimed → storyline → SUCCEEDED / FAILED / unsupported type
"""
from __future__ import annotations

import json
import sys
import os
from unittest.mock import MagicMock, patch, call
import pytest

# ── resolve worker module path ────────────────────────────────────────────────
WORKER_DIR = os.path.join(
    os.path.dirname(__file__), "..", "python-workers", "drift_refresh_worker"
)
sys.path.insert(0, os.path.abspath(WORKER_DIR))

import worker as W  # noqa: E402  (drift_refresh_worker/worker.py)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_fields
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractFields:
    def test_all_fields_present(self):
        payload = json.dumps({
            "player_id": "Steve",
            "issue": "Add a potion shop",
            "summary": "git diff applied successfully",
        })
        pid, issue, summary = W._extract_fields(payload)
        assert pid == "Steve"
        assert issue == "Add a potion shop"
        assert summary == "git diff applied successfully"

    def test_missing_summary_falls_back_to_issue(self):
        payload = json.dumps({"player_id": "Alex", "issue": "Add dungeon"})
        pid, issue, summary = W._extract_fields(payload)
        assert pid == "Alex"
        assert summary == "Add dungeon"

    def test_missing_all_falls_back_to_defaults(self):
        pid, issue, summary = W._extract_fields("{}")
        assert pid == "demo"
        assert summary == "AI workflow completed"

    def test_accepts_dict_directly(self):
        pid, issue, summary = W._extract_fields({"player_id": "Bot", "issue": "Build castle"})
        assert pid == "Bot"
        assert issue == "Build castle"

    def test_malformed_json_falls_back(self):
        pid, issue, summary = W._extract_fields("not-json{{{")
        assert pid == "demo"
        assert summary == "AI workflow completed"

    def test_issue_text_alias(self):
        payload = json.dumps({"player_id": "Dev", "issue_text": "Fix spawn"})
        pid, issue, summary = W._extract_fields(payload)
        assert issue == "Fix spawn"
        assert summary == "Fix spawn"


# ─────────────────────────────────────────────────────────────────────────────
# call_story_refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestCallStoryRefresh:
    def _mock_resp(self, status_code: int, body: dict) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.raise_for_status = MagicMock(
            side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
        )
        resp.json.return_value = body
        return resp

    def test_success_returns_world_patch(self):
        resp = self._mock_resp(200, {"ok": True, "world_patch": {"mc": {"blocks": []}}, "level_id": "ai_refresh_123"})
        with patch.object(W._drift_session, "post", return_value=resp):
            result = W.call_story_refresh("Steve", "wf-42", "Add shop", "git applied")
        assert result["ok"] is True
        assert "world_patch" in result
        assert result["level_id"] == "ai_refresh_123"

    def test_http_error_propagates(self):
        resp = self._mock_resp(500, {})
        resp.raise_for_status.side_effect = Exception("HTTP 500")
        with patch.object(W._drift_session, "post", return_value=resp):
            with pytest.raises(Exception, match="HTTP 500"):
                W.call_story_refresh("Steve", "", "issue", "summary")

    def test_non_json_response_returns_raw(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.side_effect = ValueError("no json")
        resp.text = "OK plain text"
        with patch.object(W._drift_session, "post", return_value=resp):
            result = W.call_story_refresh("Steve", "", "issue", "summary")
        assert result.get("raw") == "OK plain text"


# ─────────────────────────────────────────────────────────────────────────────
# call_progress_notify
# ─────────────────────────────────────────────────────────────────────────────

class TestCallProgressNotify:
    def test_successful_notify(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        with patch.object(W._drift_session, "post", return_value=resp):
            # Should not raise
            W.call_progress_notify("Steve", "drift_refresh", "done", "wf-1", "SUCCEEDED")

    def test_notify_with_world_patch(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        captured = {}
        def fake_post(url, json=None, timeout=None):
            captured["body"] = json
            return resp
        with patch.object(W._drift_session, "post", side_effect=fake_post):
            W.call_progress_notify("Alex", "drift_refresh", "ok", "wf-2", "SUCCEEDED",
                                   world_patch={"mc": {"blocks": []}})
        assert captured["body"]["world_patch"] == {"mc": {"blocks": []}}

    def test_notify_failure_is_non_fatal(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("conn refused")
        with patch.object(W._drift_session, "post", return_value=resp):
            # Must NOT raise
            W.call_progress_notify("Bot", "drift_refresh", "msg", "", "RUNNING")


# ─────────────────────────────────────────────────────────────────────────────
# Worker main loop (run_worker) — mocked SDK client
# ─────────────────────────────────────────────────────────────────────────────

def _make_assignment(action_type="drift_refresh", action_id=1, player_id="Steve", issue="Add shop"):
    return {
        "type": action_type,
        "actionId": action_id,
        "workflowId": 99,
        "payload": json.dumps({
            "player_id": player_id,
            "issue": issue,
            "summary": "git output: 5 files changed",
        }),
    }


class _StopLoop(BaseException):
    """Sentinel — inherits BaseException so it escapes `except Exception` in the worker loop."""
    pass


class TestRunWorker:
    """Integration-style tests for the run_worker loop with mocked SDK and HTTP."""

    def _setup_client_mock(self, assignments: list):
        """Return a mock AsyncAiFlowClient that yields assignments then raises _StopLoop."""
        mock_client = MagicMock()
        poll_returns = iter(assignments + [_StopLoop("stop")])

        def poll_side_effect():
            val = next(poll_returns)
            if isinstance(val, BaseException):
                raise val
            return val

        mock_client.poll_action.side_effect = poll_side_effect
        mock_client.heartbeat = MagicMock()
        mock_client.register_worker = MagicMock()
        mock_client.submit_result = MagicMock()
        return mock_client

    def test_successful_action_submits_succeeded(self):
        mock_client = self._setup_client_mock([_make_assignment()])

        refresh_resp = {"ok": True, "world_patch": {"mc": {}}, "level_id": "ai_123"}

        with patch("asyncaiflow_client.AsyncAiFlowClient", return_value=mock_client), \
             patch("asyncaiflow_client.AsyncAiFlowConfig"), \
             patch("worker.call_story_refresh", return_value=refresh_resp), \
             patch("worker.call_progress_notify"), \
             patch("time.sleep"):
            with pytest.raises(_StopLoop):
                W.run_worker()

        submit_calls = mock_client.submit_result.call_args_list
        assert len(submit_calls) == 1
        kwargs = submit_calls[0].kwargs
        assert kwargs["status"] == "SUCCEEDED"
        result = json.loads(kwargs["result"]) if isinstance(kwargs["result"], str) else kwargs["result"]
        assert result["player_id"] == "Steve"
        assert result["level_id"] == "ai_123"

    def test_unsupported_action_type_submits_failed(self):
        mock_client = self._setup_client_mock([
            _make_assignment(action_type="wrong_type"),
        ])
        with patch("asyncaiflow_client.AsyncAiFlowClient", return_value=mock_client), \
             patch("asyncaiflow_client.AsyncAiFlowConfig"), \
             patch("time.sleep"):
            with pytest.raises(_StopLoop):
                W.run_worker()

        kwargs = mock_client.submit_result.call_args.kwargs
        assert kwargs["status"] == "FAILED"
        result = json.loads(kwargs["result"]) if isinstance(kwargs["result"], str) else kwargs["result"]
        assert result["reason"] == "unsupported action type"

    def test_story_refresh_http_error_submits_failed(self):
        mock_client = self._setup_client_mock([_make_assignment()])
        import requests as _req

        with patch("asyncaiflow_client.AsyncAiFlowClient", return_value=mock_client), \
             patch("asyncaiflow_client.AsyncAiFlowConfig"), \
             patch("worker.call_story_refresh",
                   side_effect=_req.HTTPError("500 Server Error")), \
             patch("worker.call_progress_notify"), \
             patch("time.sleep"):
            with pytest.raises(_StopLoop):
                W.run_worker()

        kwargs = mock_client.submit_result.call_args.kwargs
        assert kwargs["status"] == "FAILED"
        assert "drift_refresh_http_error" in (kwargs["result"] if isinstance(kwargs["result"], str)
                                               else json.dumps(kwargs["result"]))

    def test_generic_exception_submits_failed(self):
        mock_client = self._setup_client_mock([_make_assignment()])

        with patch("asyncaiflow_client.AsyncAiFlowClient", return_value=mock_client), \
             patch("asyncaiflow_client.AsyncAiFlowConfig"), \
             patch("worker.call_story_refresh",
                   side_effect=RuntimeError("unexpected crash")), \
             patch("worker.call_progress_notify"), \
             patch("time.sleep"):
            with pytest.raises(_StopLoop):
                W.run_worker()

        kwargs = mock_client.submit_result.call_args.kwargs
        assert kwargs["status"] == "FAILED"
        assert kwargs["error_message"] == "unexpected crash"

    def test_progress_notify_called_twice(self):
        """Worker must call progress/notify once with RUNNING then once with SUCCEEDED."""
        mock_client = self._setup_client_mock([_make_assignment()])
        refresh_resp = {"ok": True, "world_patch": {}, "level_id": "lv1"}

        notify_calls = []
        with patch("asyncaiflow_client.AsyncAiFlowClient", return_value=mock_client), \
             patch("asyncaiflow_client.AsyncAiFlowConfig"), \
             patch("worker.call_story_refresh", return_value=refresh_resp), \
             patch("worker.call_progress_notify",
                   side_effect=lambda **kw: notify_calls.append(kw)), \
             patch("time.sleep"):
            with pytest.raises(_StopLoop):
                W.run_worker()

        statuses = [c["status"] for c in notify_calls]
        assert "RUNNING" in statuses
        assert "SUCCEEDED" in statuses
