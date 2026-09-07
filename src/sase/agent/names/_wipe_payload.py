"""Shared JSON payload helpers for the agent-name wipe pipeline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def payload_names(
    payload: Mapping[str, Any] | None, *, bundle: bool = False
) -> set[str]:
    if not payload:
        return set()
    keys = (
        ("agent_name", "workflow_name", "name") if bundle else ("name", "workflow_name")
    )
    return {
        value for key in keys if isinstance((value := payload.get(key)), str) and value
    }


def payload_outgoing_suffixes(payload: Mapping[str, Any] | None) -> set[str]:
    if not payload:
        return set()
    value = payload.get("retried_as_timestamp")
    return {value} if isinstance(value, str) and value else set()


def read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
