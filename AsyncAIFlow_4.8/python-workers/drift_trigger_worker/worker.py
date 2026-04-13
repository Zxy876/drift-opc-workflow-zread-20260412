"""
drift_trigger_worker — 将 AsyncAIFlow drift_trigger action 转化为 Drift API 调用

每次 poll 到 drift_trigger action 时：
1. 解析 payload 中的 summary / issue 字段
2. 调用 Drift POST /story/inject 创建新的剧情关卡
3. 提交 SUCCEEDED 结果，附带 Drift API 响应

启动方法：
    python3 worker.py

依赖：pip install requests
"""

from __future__ import annotations

import json
import logging
import os
import time
import re

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [drift-trigger-worker] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────
ASYNCAIFLOW_URL: str = os.environ.get("ASYNCAIFLOW_URL", "http://localhost:8080")
DRIFT_URL: str = os.environ.get("DRIFT_URL", "http://localhost:8000")
WORKER_ID: str = os.environ.get("DRIFT_TRIGGER_WORKER_ID", "drift-trigger-worker-1")
CAPABILITIES: list[str] = ["drift_trigger"]
POLL_INTERVAL_S: float = float(os.environ.get("POLL_INTERVAL_S", "2"))
HEARTBEAT_INTERVAL_S: float = float(os.environ.get("HEARTBEAT_INTERVAL_S", "10"))

# ─────────────────────────────────────────────────────────────
# HTTP session（trust_env=False 避免代理干扰本地通信）
# ─────────────────────────────────────────────────────────────
_session = requests.Session()
_session.trust_env = False
_drift_session = requests.Session()
_drift_session.trust_env = False


# ─────────────────────────────────────────────────────────────
# AsyncAIFlow 客户端封装
# ─────────────────────────────────────────────────────────────
def _asyncaiflow_post(path: str, body: dict) -> dict:
    resp = _session.post(f"{ASYNCAIFLOW_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        raise RuntimeError(f"AsyncAIFlow {path} failed: {data.get('message', 'unknown error')}")
    return data


def register_worker() -> None:
    _asyncaiflow_post("/worker/register", {
        "workerId": WORKER_ID,
        "capabilities": CAPABILITIES,
    })
    LOGGER.info("Worker %s registered with capabilities %s", WORKER_ID, CAPABILITIES)


def heartbeat() -> None:
    try:
        _asyncaiflow_post("/worker/heartbeat", {"workerId": WORKER_ID})
    except Exception as e:
        LOGGER.warning("Heartbeat failed: %s", e)


def poll_action() -> dict | None:
    resp = _session.get(
        f"{ASYNCAIFLOW_URL}/action/poll",
        params={"workerId": WORKER_ID},
        timeout=10,
    )
    if resp.status_code == 204 or not resp.text.strip():
        return None
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success", False):
        return None
    return data.get("data")


def submit_result(action_id: int, status: str, result: dict, error_message: str | None = None) -> None:
    _asyncaiflow_post("/action/result", {
        "workerId": WORKER_ID,
        "actionId": action_id,
        "status": status,
        "result": json.dumps(result, ensure_ascii=False),
        "errorMessage": error_message,
    })


# ─────────────────────────────────────────────────────────────
# Drift API 调用
# ─────────────────────────────────────────────────────────────
def _safe_level_id(raw: str) -> str:
    """生成安全的 level_id（只包含字母数字下划线，附加时间戳确保唯一）"""
    sanitized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    ts = int(time.time())
    return f"drift_ai_{ts}"


def call_drift_inject(payload_data: dict, action_id: int) -> dict:
    """调用 Drift POST /story/inject 创建剧情关卡，返回响应 dict"""
    # 从 payload 中提取摘要 / issue 文本
    summary = str(
        payload_data.get("summary")
        or payload_data.get("issue")
        or payload_data.get("description")
        or "AI执行完成，世界已更新"
    )[:200]

    level_id = _safe_level_id(summary[:30])
    title = f"AI执行完成 #{action_id}"
    text = f"[AsyncAIFlow] {summary}"

    inject_body = {
        "level_id": level_id,
        "title": title,
        "text": text,
        "player_id": str(payload_data.get("player_id", "demo")),
    }

    LOGGER.info(
        "Calling Drift /story/inject level_id=%s title=%r actionId=%s",
        level_id, title, action_id,
    )

    resp = _drift_session.post(
        f"{DRIFT_URL}/story/inject",
        json=inject_body,
        timeout=15,
    )

    if resp.status_code == 400 and "already exists" in resp.text:
        # level_id 冲突，加上 action_id 重试一次
        inject_body["level_id"] = f"drift_ai_{int(time.time())}_{action_id}"
        LOGGER.warning("Level ID conflict, retrying with %s", inject_body["level_id"])
        resp = _drift_session.post(f"{DRIFT_URL}/story/inject", json=inject_body, timeout=15)

    try:
        resp_data = resp.json()
    except Exception:
        resp_data = {"raw": resp.text[:500]}

    LOGGER.info(
        "Drift /story/inject status=%s response_keys=%s",
        resp.status_code,
        list(resp_data.keys()) if isinstance(resp_data, dict) else type(resp_data).__name__,
    )

    return {
        "http_status": resp.status_code,
        "level_id": inject_body["level_id"],
        "drift_response": resp_data,
        "success": resp.status_code in (200, 201),
    }


# ─────────────────────────────────────────────────────────────
# 执行主逻辑
# ─────────────────────────────────────────────────────────────
def execute_drift_trigger(action: dict) -> tuple[str, dict, str | None]:
    """
    Returns: (status, result_dict, error_message)
    status: "SUCCEEDED" | "FAILED"
    """
    action_id: int = action["actionId"]
    raw_payload = action.get("payload") or {}

    # payload 可能是字符串 JSON
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except Exception:
            raw_payload = {"raw": raw_payload}

    try:
        drift_result = call_drift_inject(raw_payload, action_id)

        result = {
            "schemaVersion": "v1",
            "worker": WORKER_ID,
            "actionId": action_id,
            "drift_level_id": drift_result.get("level_id"),
            "drift_http_status": drift_result.get("http_status"),
            "drift_success": drift_result.get("success"),
            "summary": "Drift world updated via /story/inject",
        }

        if drift_result.get("success"):
            LOGGER.info(
                "drift_trigger SUCCEEDED actionId=%s level_id=%s",
                action_id, drift_result.get("level_id"),
            )
            return "SUCCEEDED", result, None
        else:
            error_msg = f"Drift inject returned HTTP {drift_result.get('http_status')}: {drift_result.get('drift_response')}"
            LOGGER.warning("drift_trigger FAILED (non-2xx) actionId=%s: %s", action_id, error_msg)
            return "FAILED", result, error_msg

    except Exception as exc:
        LOGGER.exception("drift_trigger execution error actionId=%s", action_id)
        return "FAILED", {"error": str(exc)}, str(exc)


# ─────────────────────────────────────────────────────────────
# 主循环
# ─────────────────────────────────────────────────────────────
def main() -> None:
    LOGGER.info("drift_trigger_worker starting — AsyncAIFlow=%s Drift=%s", ASYNCAIFLOW_URL, DRIFT_URL)
    register_worker()

    next_heartbeat = time.monotonic() + HEARTBEAT_INTERVAL_S

    while True:
        now = time.monotonic()
        if now >= next_heartbeat:
            heartbeat()
            next_heartbeat = now + HEARTBEAT_INTERVAL_S

        try:
            action = poll_action()
        except Exception as exc:
            LOGGER.warning("Poll failed: %s", exc)
            time.sleep(POLL_INTERVAL_S)
            continue

        if action is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        action_id = action.get("actionId")
        action_type = action.get("type")
        LOGGER.info("Claimed action actionId=%s type=%s", action_id, action_type)

        status, result, error_message = execute_drift_trigger(action)

        try:
            submit_result(action_id, status, result, error_message)
            LOGGER.info("Submitted result actionId=%s status=%s", action_id, status)
        except Exception as exc:
            LOGGER.error("Failed to submit result actionId=%s: %s", action_id, exc)


if __name__ == "__main__":
    main()
