"""
drift_git_push_worker — stub worker for drift_git_push action type.

Behavior: logs the deploy result and returns SUCCEEDED without actually
pushing to git. Keeps the DAG flowing for demo/hackathon purposes.

Environment variables
---------------------
  ASYNCAIFLOW_URL              = http://localhost:8080
  DRIFT_GIT_PUSH_WORKER_ID     = drift-git-push-worker-1
  POLL_INTERVAL_S              = 2
"""
from __future__ import annotations

import json
import logging
import os
import time

import requests

ACTION_TYPE = "drift_git_push"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-git-push-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

ASYNCAIFLOW_URL: str = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
WORKER_ID: str = os.environ.get("DRIFT_GIT_PUSH_WORKER_ID", "drift-git-push-worker-1")
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
    except Exception as e:
        LOGGER.warning("Heartbeat failed: %s", e)


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
    try:
        _post("/action/result", payload)
        LOGGER.info("action_id=%s submitted %s", action_id, status)
    except Exception as e:
        LOGGER.error("submit_result failed: %s", e)


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
        except Exception as e:
            LOGGER.warning("Poll failed: %s — retrying in %ss", e, POLL_INTERVAL_S)
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
            submit_result(action_id, "FAILED",
                          {"reason": f"unsupported type: {action_type}"},
                          error=f"unsupported action type: {action_type}")
            continue

        try:
            p = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except Exception:
            p = {}
        issue_text = p.get("issue_text") or p.get("issue") or "(no issue)"
        player_id = p.get("player_id") or "unknown"
        deploy_result = p.get("deploy_result") or p.get("summary") or "patch deployed"
        branch = f"demo/{player_id}-{int(time.time())}"

        LOGGER.info("Git push stub for player=%s branch=%s issue=%.60s",
                    player_id, branch, issue_text)

        # Stub: simulate a successful git push without touching git
        submit_result(action_id, "SUCCEEDED", {
            "pushed": True,
            "branch": branch,
            "player_id": player_id,
            "deploy_summary": str(deploy_result)[:200],
            "message": f"[demo] pushed branch {branch} — no actual git operation",
        })


if __name__ == "__main__":
    run_worker()
