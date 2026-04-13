from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class LlmConfig:
    api_key: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 120
    response_schema_text: str | None = None
    base_url: str | None = None


class GeminiJsonClient:
    """OpenAI-compatible JSON LLM client (supports DeepSeek, ZhipuAI, OpenAI, etc.)."""

    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(proxy_var, None)
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,  # None → uses api.openai.com
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        system_parts = [system_prompt.strip()]
        if self.config.response_schema_text:
            system_parts.append(
                "You must produce JSON that conforms to this Design Schema v0.1 definition:\n"
                + self.config.response_schema_text.strip()
            )
        messages = [
            {"role": "system", "content": "\n\n".join(p for p in system_parts if p)},
            {"role": "user", "content": user_prompt.strip()},
        ]

        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            response_format={"type": "json_object"},
            timeout=self.config.timeout_seconds,
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise ValueError("LLM returned empty response")
        return json.loads(content)
