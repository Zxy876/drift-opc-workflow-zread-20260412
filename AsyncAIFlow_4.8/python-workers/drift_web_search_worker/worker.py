"""
drift_web_search_worker — stub worker for drift_web_search action type.

Behavior: immediately returns SUCCEEDED with a small search summary.
This keeps the difficulty=5 Drift DAG moving even when no dedicated search
integration is configured.
"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

ACTION_TYPE = "drift_web_search"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-web-search-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

ASYNCAIFLOW_URL: str = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
WORKER_ID: str = os.environ.get("DRIFT_WEB_SEARCH_WORKER_ID", "drift-web-search-worker-1")
CAPABILITIES: list[str] = [ACTION_TYPE]
POLL_INTERVAL_S: float = float(os.environ.get("POLL_INTERVAL_S", "2"))
HEARTBEAT_INTERVAL_S: float = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))

_session = requests.Session()
_session.trust_env = False


def _post(path: str, body: dict) -> dict:
    resp = _session.post(f"{ASYNCAIFLOW_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise RuntimeError(f"AsyncAIFlow {path}: {data.get('message', 'error')}")
    return data


def register_worker() -> None:
    _post("/worker/register", {"workerId": WORKER_ID, "capabilities": CAPABILITIES})
    LOGGER.info("Registered as %s", WORKER_ID)


def heartbeat() -> None:
    try:
        _post("/worker/heartbeat", {"workerId": WORKER_ID})
    except Exception as exc:
        LOGGER.warning("Heartbeat failed: %s", exc)


def poll_action() -> dict | None:
    resp = _session.get(
        f"{ASYNCAIFLOW_URL}/action/poll",
        params={"workerId": WORKER_ID, "capabilities": ",".join(CAPABILITIES)},
        timeout=10,
    )
    if resp.status_code == 204:
        return None
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success") or not body.get("data"):
        return None
    return body["data"]


def submit_result(action_id: int, status: str, result: dict, error: str | None = None) -> None:
    payload: dict = {
        "workerId": WORKER_ID,
        "actionId": action_id,
        "status": status,
        "result": json.dumps(result, ensure_ascii=False),
    }
    if error:
        payload["errorMessage"] = error
    _post("/action/result", payload)
    LOGGER.info("action_id=%s submitted %s", action_id, status)


def run_worker() -> None:
    register_worker()
    last_heartbeat = time.monotonic()

    while True:
        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
            heartbeat()
            last_heartbeat = now

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
        payload_raw = action.get("payload", "{}")

        LOGGER.info("Claimed action_id=%s type=%s", action_id, action_type)

        if action_type != ACTION_TYPE:
            submit_result(
                action_id,
                "FAILED",
                {"reason": f"unsupported type: {action_type}"},
                error=f"unsupported action type: {action_type}",
            )
            continue

        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except Exception:
            payload = {}

        issue = payload.get("issue_text") or payload.get("issue") or "(no issue)"
        player_id = payload.get("player_id") or "unknown"

        submit_result(
            action_id,
            "SUCCEEDED",
            {
                "search_summary": f"已检索相关技术信息：{str(issue)[:100]}",
                "references": [
                    {"title": "Stub reference", "url": "https://docs.example.com"},
                ],
                "player_id": player_id,
            },
        )


if __name__ == "__main__":
    run_worker()