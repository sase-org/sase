"""Schema-aware JSON decoding for the publication outbox."""

from __future__ import annotations

import json
import math
from pathlib import Path

from sase.agents_sync.publication_outbox_models import (
    PUBLICATION_KIND_RANK,
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
    PublicationKind,
    validate_publication_item,
)


def read_publication_outbox(
    path: Path,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Decode and validate a complete publication outbox document."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read agents publication outbox: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agents publication outbox must be a JSON object")
    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {1, 2, 3, PUBLICATION_OUTBOX_SCHEMA_VERSION}
    ):
        raise RuntimeError("unsupported agents publication outbox schema")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("agents publication outbox items must be a list")
    items = tuple(
        _item_from_json(row, project_key, schema_version=schema_version) for row in rows
    )
    if len({item.logical_key for item in items}) != len(items):
        raise RuntimeError("agents publication outbox contains duplicate requests")
    # Rank is the only cross-kind ordering constraint. Python's stable sort
    # preserves the durable order within one kind, including legacy files.
    return tuple(sorted(items, key=lambda item: item.ordering_rank))


def _item_from_json(
    value: object,
    project_key: str,
    *,
    schema_version: int,
) -> AgentPublicationOutboxItem:
    if not isinstance(value, dict):
        raise RuntimeError("agents publication outbox item must be an object")
    row = value
    kind = (
        "agent_hood"
        if schema_version < PUBLICATION_OUTBOX_SCHEMA_VERSION
        else _json_publication_kind(row, "kind")
    )
    if schema_version == PUBLICATION_OUTBOX_SCHEMA_VERSION:
        rank = _json_nonnegative_int(row, "rank", default=-1)
        if rank != PUBLICATION_KIND_RANK[kind]:
            raise RuntimeError("agents publication outbox rank does not match kind")
    item = AgentPublicationOutboxItem(
        project_key=_json_text(row, "project_key"),
        project=_json_text(row, "project"),
        local_agent=_json_text(row, "local_agent", default=""),
        global_agent=_json_text(row, "global_agent", default=""),
        primary_revision=_json_text(row, "primary_revision"),
        local_hood=_json_text(row, "local_hood", default=""),
        hood_digest=_json_text(row, "hood_digest", default="pending"),
        kind=kind,
        bead_id=_json_text(row, "bead_id", default=""),
        lineage_root=_json_text(row, "lineage_root", default=""),
        plan_ref=_json_text(row, "plan_ref", default=""),
        commit_message=_json_text(row, "commit_message", default=""),
        sidecar_kind=_json_text(row, "sidecar_kind", default=""),
        attempts=_json_nonnegative_int(row, "attempts", default=0),
        last_error=_json_optional_text(row, "last_error"),
        quarantined=_json_boolean(
            row,
            "quarantined",
            default=False if schema_version == 1 else None,
        ),
        quarantined_at=_json_optional_number(row, "quarantined_at"),
        terminal=_json_boolean(
            row,
            "terminal",
            default=False if schema_version < 3 else None,
        ),
        terminal_reason=_json_optional_text(row, "terminal_reason"),
        created_at=_json_number(row, "created_at", default=0.0),
        updated_at=_json_number(row, "updated_at", default=0.0),
    )
    validate_publication_item(item, project_key)
    return item


def _json_text(
    row: dict[object, object],
    field: str,
    *,
    default: str = "",
) -> str:
    value = row.get(field, default)
    if not isinstance(value, str):
        raise RuntimeError(f"agents publication outbox {field} must be a string")
    return value


def _json_publication_kind(
    row: dict[object, object],
    field: str,
) -> PublicationKind:
    value = row.get(field)
    if value not in PUBLICATION_KIND_RANK:
        raise RuntimeError(
            "agents publication outbox kind must be one of: "
            + ", ".join(PUBLICATION_KIND_RANK)
        )
    return value  # type: ignore[return-value]


def _json_optional_text(
    row: dict[object, object],
    field: str,
) -> str | None:
    value = row.get(field)
    if value is not None and not isinstance(value, str):
        raise RuntimeError(
            f"agents publication outbox {field} must be a string or null"
        )
    return value


def _json_boolean(
    row: dict[object, object],
    field: str,
    *,
    default: bool | None,
) -> bool:
    value = row.get(field, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"agents publication outbox {field} must be a boolean")
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
            f"agents publication outbox {field} must be a non-negative integer"
        )
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
        raise RuntimeError(f"agents publication outbox {field} must be a number")
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
        raise RuntimeError(
            f"agents publication outbox {field} must be a number or null"
        )
    return float(value)


__all__ = ["read_publication_outbox"]
