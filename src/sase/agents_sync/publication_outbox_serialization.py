"""Schema-aware JSON decoding for the publication outbox."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path

from sase.agents_sync.publication_outbox_models import (
    AgentPublicationOutboxItem,
    validate_publication_item,
)

SUPPORTED_PUBLICATION_OUTBOX_SCHEMA_VERSIONS = (1, 2, 3, 4, 5)
_MULTI_KIND_SCHEMA_VERSION = 4


@dataclass(frozen=True, slots=True)
class PublicationOutboxDocument:
    """One decoded outbox file plus any migration notices it produced."""

    items: tuple[AgentPublicationOutboxItem, ...]
    notices: tuple[str, ...] = ()


def read_publication_outbox_document(
    path: Path,
    project_key: str,
) -> PublicationOutboxDocument:
    """Decode and validate a complete publication outbox document.

    Schema 4 briefly stored non-agent-hood request kinds for sidecar work that
    is published inline on the commit path again. Those records are dropped on
    read rather than resurrected, and the drop is reported as a notice so it is
    visible instead of silent.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return PublicationOutboxDocument(())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read agents publication outbox: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agents publication outbox must be a JSON object")
    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_PUBLICATION_OUTBOX_SCHEMA_VERSIONS
    ):
        raise RuntimeError("unsupported agents publication outbox schema")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("agents publication outbox items must be a list")

    retained: list[object] = []
    dropped: Counter[str] = Counter()
    for row in rows:
        kind = _obsolete_row_kind(row, schema_version=schema_version)
        if kind is None:
            retained.append(row)
        else:
            dropped[kind] += 1

    items = tuple(
        _item_from_json(row, project_key, schema_version=schema_version)
        for row in retained
    )
    if len({item.logical_key for item in items}) != len(items):
        raise RuntimeError("agents publication outbox contains duplicate requests")
    return PublicationOutboxDocument(items, _dropped_notices(path, dropped))


def read_publication_outbox(
    path: Path,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Decode one outbox file and return only its agent-hood requests."""

    return read_publication_outbox_document(path, project_key).items


def _obsolete_row_kind(value: object, *, schema_version: int) -> str | None:
    """Return the obsolete request kind of *value*, or ``None`` to keep it."""

    if schema_version != _MULTI_KIND_SCHEMA_VERSION or not isinstance(value, dict):
        return None
    kind = value.get("kind", "agent_hood")
    if not isinstance(kind, str) or kind == "agent_hood":
        return None
    return kind


def _dropped_notices(path: Path, dropped: Counter[str]) -> tuple[str, ...]:
    if not dropped:
        return ()
    breakdown = ", ".join(f"{count} {kind}" for kind, count in sorted(dropped.items()))
    return (
        f"dropped {sum(dropped.values())} obsolete publication request(s) "
        f"({breakdown}) from the schema-{_MULTI_KIND_SCHEMA_VERSION} outbox at "
        f"{path}: bead pages, plan headers, and sidecar pushes are published "
        "inline on the commit path, so only agent-hood retries are queued",
    )


def _item_from_json(
    value: object,
    project_key: str,
    *,
    schema_version: int,
) -> AgentPublicationOutboxItem:
    if not isinstance(value, dict):
        raise RuntimeError("agents publication outbox item must be an object")
    row = value
    item = AgentPublicationOutboxItem(
        project_key=_json_text(row, "project_key"),
        project=_json_text(row, "project"),
        local_agent=_json_text(row, "local_agent"),
        global_agent=_json_text(row, "global_agent"),
        primary_revision=_json_text(row, "primary_revision"),
        local_hood=_json_text(row, "local_hood"),
        hood_digest=_json_text(row, "hood_digest", default="pending"),
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


__all__ = [
    "SUPPORTED_PUBLICATION_OUTBOX_SCHEMA_VERSIONS",
    "PublicationOutboxDocument",
    "read_publication_outbox",
    "read_publication_outbox_document",
]
