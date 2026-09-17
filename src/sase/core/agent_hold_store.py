"""Store-facing helpers for durable agent holds."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

LOGGER = logging.getLogger(__name__)
AGENT_HOLD_STORE_FILENAME = "agent_holds.json"


def agent_hold_store_path(root: str | Path | None = None) -> Path:
    """Return the durable agent-holds store path."""
    base = sase_home() if root is None else Path(root)
    return base / AGENT_HOLD_STORE_FILENAME


def read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_holds(
    liveness: Mapping[str, Any],
    *,
    now: datetime | float | None,
) -> Mapping[str, Any]:
    list_snapshot = require_rust_binding("agent_hold_list")
    value = list_snapshot(str(sase_home()), dict(liveness), epoch_seconds(now))
    if not isinstance(value, Mapping):
        raise RuntimeError("agent_hold_list returned a non-object snapshot")
    return value


def release_agent_hold_key(
    armer_key: str, *, now: datetime | float | None = None
) -> bool:
    """Best-effort idempotent release for one armer key."""
    try:
        release = require_rust_binding("agent_hold_release")
        return bool(release(str(sase_home()), armer_key, {}, epoch_seconds(now)))
    except Exception as exc:  # noqa: BLE001 - release is cleanup, not settlement.
        LOGGER.warning("agent hold release failed for %s: %s", armer_key, exc)
        return False


def validated_holds(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    if type(snapshot.get("schema_version")) is not int:
        raise RuntimeError("agent hold snapshot has no integer schema_version")
    raw_holds = snapshot.get("holds")
    if not isinstance(raw_holds, list):
        raise RuntimeError("agent hold snapshot has no holds list")
    holds: list[dict[str, Any]] = []
    for hold in raw_holds:
        if not isinstance(hold, Mapping):
            raise RuntimeError("agent hold record is not an object")
        _validate_hold_record(hold)
        holds.append(dict(hold))
    return holds


def _validate_hold_record(hold: Mapping[str, Any]) -> None:
    armer = mapping_payload(hold.get("armer"))
    scope = mapping_payload(hold.get("scope"))
    selectors = mapping_payload(hold.get("selectors"))
    if type(hold.get("schema_version")) is not int:
        raise RuntimeError("agent hold record has no integer schema_version")
    if armer.get("kind") not in {"agent", "proc", "cli", "launch"}:
        raise RuntimeError("agent hold armer kind is invalid")
    for key in ("key", "display", "project"):
        if not isinstance(armer.get(key), str) or not armer.get(key):
            raise RuntimeError(f"agent hold armer {key} is invalid")
    if scope.get("kind") not in {"project", "host"}:
        raise RuntimeError("agent hold scope kind is invalid")
    if not isinstance(selectors, Mapping):
        raise RuntimeError("agent hold selectors are invalid")
    for key in ("created_at", "expires_at"):
        value = hold.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"agent hold {key} is invalid")


def mapping_payload(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError("agent hold payload is not an object")
    return value


def epoch_seconds(value: datetime | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.timestamp()
    return float(value)


def format_epoch(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
