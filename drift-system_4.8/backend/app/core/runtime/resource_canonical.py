from __future__ import annotations

from typing import Any


_DIRECT_RESOURCE_ALIASES = {
    "porkchop": "pork",
    "raw_porkchop": "pork",
    "cooked_porkchop": "pork",
}


def _strip_collect_prefix(token: str) -> str:
    if token.startswith("collect_"):
        return token[len("collect_") :]
    if token.startswith("collect:"):
        return token[len("collect:") :]
    return token


def _strip_namespace_or_suffix(token: str) -> str:
    if ":" not in token:
        return token

    parts = [segment.strip("_") for segment in token.split(":") if segment.strip("_")]
    if not parts:
        return ""

    if len(parts) == 1:
        return parts[0]

    namespace = parts[0]
    path = parts[1]

    if namespace in {"minecraft", "mc"}:
        return path

    if len(parts) == 2:
        if path.isdigit():
            return namespace
        return f"{namespace}:{path}"

    if path.isdigit():
        return namespace

    if parts[-1].isdigit():
        return f"{namespace}:{path}"

    return f"{namespace}:{path}"


def normalize_inventory_resource_token(raw_value: Any) -> str:
    token = str(raw_value or "").strip().lower()
    if not token:
        return ""

    token = token.replace("-", "_").replace(" ", "_")
    token = _strip_collect_prefix(token)
    token = _strip_namespace_or_suffix(token)
    token = token.strip("_")
    if not token:
        return ""

    aliased = _DIRECT_RESOURCE_ALIASES.get(token)
    if aliased:
        return aliased

    if ":" not in token and (token.endswith("_log") or token.endswith("_wood") or token.endswith("_stem")):
        return "wood"

    return token