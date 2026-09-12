"""Immutable persistence for frozen monitor outcome policies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION, JsonObject

from ._storage import (
    PublicationTransaction,
    continuation_root,
    read_json_object,
    recover_publication_journal,
    sha_json,
    update_agent_meta_fields,
)


def persist_frozen_outcome_policy(
    artifacts_dir: str,
    frozen: Mapping[str, Any],
) -> str:
    """Persist *frozen* immutably and point the monitor member at it."""

    payload = dict(frozen)
    payload.setdefault("schema_version", CONTINUATION_WIRE_SCHEMA_VERSION)
    fingerprint = str(payload.get("fingerprint") or f"sha256:{sha_json(payload)}")
    payload["fingerprint"] = fingerprint
    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
    digest = fingerprint.removeprefix("sha256:")
    filename = f"{digest}.json"
    txn = PublicationTransaction(root)
    policy_ref, _ = txn.write_record("policies", filename, payload=payload)
    txn.write_pointer("monitor_outcome_policy.json", payload=payload)
    txn.commit()
    update_agent_meta_fields(
        artifacts_dir,
        {
            "continuation_outcome_policy_ref": policy_ref,
            "monitor_policy_digest": fingerprint,
        },
    )
    return policy_ref


def load_frozen_outcome_policy(artifacts_dir: str) -> JsonObject | None:
    """Return the frozen outcome policy published for *artifacts_dir*."""

    path = continuation_root(artifacts_dir) / "monitor_outcome_policy.json"
    payload = read_json_object(path)
    if isinstance(payload, dict) and payload:
        return payload
    return None


__all__ = [
    "load_frozen_outcome_policy",
    "persist_frozen_outcome_policy",
]
