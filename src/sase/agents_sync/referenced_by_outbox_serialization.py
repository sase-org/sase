"""Schema-aware JSON decoding for the Referenced By outbox."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

from sase.agents_sync.referenced_by_outbox_models import (
    ReferencedByOutboxItem,
    validate_referenced_by_item,
)

SUPPORTED_REFERENCED_BY_OUTBOX_SCHEMA_VERSIONS = (1,)


@dataclass(frozen=True, slots=True)
class ReferencedByOutboxDocument:
    """One decoded referenced-by outbox file."""

    items: tuple[ReferencedByOutboxItem, ...]
    notices: tuple[str, ...] = ()


def read_referenced_by_outbox_document(
    path: Path,
    project_key: str,
) -> ReferencedByOutboxDocument:
    """Decode and validate a complete referenced-by outbox document."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ReferencedByOutboxDocument(())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read referenced-by outbox: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("referenced-by outbox must be a JSON object")
    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_REFERENCED_BY_OUTBOX_SCHEMA_VERSIONS
    ):
        raise RuntimeError("unsupported referenced-by outbox schema")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("referenced-by outbox items must be a list")

    items = tuple(_item_from_json(row, project_key) for row in rows)
    if len({item.logical_key for item in items}) != len(items):
        raise RuntimeError("referenced-by outbox contains duplicate requests")
    return ReferencedByOutboxDocument(items)


def read_referenced_by_outbox(
    path: Path,
    project_key: str,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Decode one outbox file and return its queued requests."""

    return read_referenced_by_outbox_document(path, project_key).items


def _item_from_json(value: object, project_key: str) -> ReferencedByOutboxItem:
    if not isinstance(value, dict):
        raise RuntimeError("referenced-by outbox item must be an object")
    row = value
    item = ReferencedByOutboxItem(
        project_key=_json_text(row, "project_key"),
        project=_json_text(row, "project"),
        global_agent=_json_text(row, "global_agent"),
        agent_url=_json_optional_text(row, "agent_url"),
        primary_revision=_json_text(row, "primary_revision"),
        sidecar_role=_json_text(row, "sidecar_role"),
        provider=_json_text(row, "provider"),
        artifact_id=_json_text(row, "artifact_id"),
        repo_relpath=_json_text(row, "repo_relpath"),
        identity_value=_json_optional_text(row, "identity_value"),
        canonical_ref=_json_text(row, "canonical_ref"),
        destination=_json_optional_text(row, "destination"),
        uses=_json_positive_int(row, "uses"),
        published_date=_json_text(row, "published_date"),
        relation=_json_text(row, "relation", default="cites"),
        origin=_json_text(row, "origin", default="prompt_ref"),
        description=_json_text(row, "description", default=""),
        attempts=_json_nonnegative_int(row, "attempts", default=0),
        last_error=_json_optional_text(row, "last_error"),
        quarantined=_json_boolean(row, "quarantined", default=False),
        quarantined_at=_json_optional_number(row, "quarantined_at"),
        terminal=_json_boolean(row, "terminal", default=False),
        terminal_reason=_json_optional_text(row, "terminal_reason"),
        created_at=_json_number(row, "created_at", default=0.0),
        updated_at=_json_number(row, "updated_at", default=0.0),
    )
    validate_referenced_by_item(item, project_key)
    return item


def _json_text(
    row: dict[object, object],
    field: str,
    *,
    default: str = "",
) -> str:
    value = row.get(field, default)
    if not isinstance(value, str):
        raise RuntimeError(f"referenced-by outbox {field} must be a string")
    return value


def _json_optional_text(
    row: dict[object, object],
    field: str,
) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise RuntimeError(f"referenced-by outbox {field} must be a string or null")
    return value


def _json_boolean(
    row: dict[object, object],
    field: str,
    *,
    default: bool,
) -> bool:
    value = row.get(field, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"referenced-by outbox {field} must be a boolean")
    return value


def _json_nonnegative_int(
    row: dict[object, object],
    field: str,
    *,
    default: int,
) -> int:
    value = row.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            f"referenced-by outbox {field} must be a non-negative integer"
        )
    return value


def _json_positive_int(row: dict[object, object], field: str) -> int:
    value = _json_nonnegative_int(row, field, default=0)
    if value < 1:
        raise RuntimeError(f"referenced-by outbox {field} must be positive")
    return value


def _json_number(
    row: dict[object, object],
    field: str,
    *,
    default: float,
) -> float:
    value = row.get(field, default)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise RuntimeError(f"referenced-by outbox {field} must be a number")
    return float(value)


def _json_optional_number(
    row: dict[object, object],
    field: str,
) -> float | None:
    value = row.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise RuntimeError(f"referenced-by outbox {field} must be a number or null")
    return float(value)


__all__ = [
    "SUPPORTED_REFERENCED_BY_OUTBOX_SCHEMA_VERSIONS",
    "ReferencedByOutboxDocument",
    "read_referenced_by_outbox",
    "read_referenced_by_outbox_document",
]
