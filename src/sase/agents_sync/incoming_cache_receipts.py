"""Durable import receipts for incoming agent hoods."""

from __future__ import annotations

import json
import time

from sase.agents_sync.incoming_cache_metadata import (
    exact_object,
    import_receipt_from_json,
    metadata_component,
    project_name,
)
from sase.agents_sync.incoming_cache_paths import receipts_path
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_json
from sase.agents_sync.models import (
    AgentHoodImportReceipt,
    CapturedIncomingHood,
)

_RECEIPTS_DOCUMENT_VERSION = 1


def read_project_receipts(project_key: str) -> tuple[AgentHoodImportReceipt, ...]:
    path = receipts_path(project_key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read import receipts: {exc}") from exc
    row = exact_object(
        raw,
        "agent hood receipts document",
        {"schema_version", "project_key", "project", "receipts"},
    )
    if row["schema_version"] != _RECEIPTS_DOCUMENT_VERSION:
        raise AgentsSyncFormatError("unsupported import receipts document schema")
    if metadata_component(row["project_key"], "project key") != project_key:
        raise AgentsSyncFormatError("import receipts project key does not match path")
    project = project_name(row["project"])
    raw_receipts = row["receipts"]
    if not isinstance(raw_receipts, list):
        raise AgentsSyncFormatError("import receipts must be a list")
    receipts = tuple(import_receipt_from_json(item) for item in raw_receipts)
    if any(
        receipt.project_key != project_key or receipt.project != project
        for receipt in receipts
    ):
        raise AgentsSyncFormatError("import receipt project identity disagrees")
    keys = [receipt.source_hood_key for receipt in receipts]
    if len(keys) != len(set(keys)):
        raise AgentsSyncFormatError("import receipts repeat a source hood")
    return receipts


def write_import_receipt(receipt: AgentHoodImportReceipt) -> None:
    """Atomically advance exactly one project's source-hood receipt."""

    decoded = import_receipt_from_json(receipt.to_json_dict())
    existing = read_project_receipts(decoded.project_key)
    if any(item.project != decoded.project for item in existing):
        raise AgentsSyncFormatError(
            "existing import receipt project name does not match target"
        )
    receipts = {item.source_hood_key: item for item in existing}
    receipts[decoded.source_hood_key] = decoded
    atomic_write_json(
        receipts_path(decoded.project_key),
        {
            "schema_version": _RECEIPTS_DOCUMENT_VERSION,
            "project_key": decoded.project_key,
            "project": decoded.project,
            "receipts": [
                item.to_json_dict()
                for item in sorted(
                    receipts.values(),
                    key=lambda row: (
                        row.source_owner_kind,
                        row.source_username or "",
                        row.source_machine,
                        row.top_hood,
                    ),
                )
            ],
        },
    )


def receipt_for_item(
    item: CapturedIncomingHood,
    *,
    applied_at: float | None = None,
) -> AgentHoodImportReceipt:
    return AgentHoodImportReceipt(
        project_key=item.project_key,
        project=item.project,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
        cache_id=item.cache_id,
        fetched_ref=item.fetched_ref,
        fetched_sha=item.fetched_sha,
        cache_created_at=item.cache_created_at,
        applied_at=time.time() if applied_at is None else applied_at,
    )
