"""Shared read-link recording for audited artifact and bead reads."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sase.agent.identity import discover_agent_identity
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_entry
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    canonicalize_artifact_link_ref,
    resolve_artifact_link_store,
)

READ_NOT_RECORDED_NOTE = (
    "note: this read was not recorded as a graph edge "
    "(no SASE agent run with an identity was detected)"
)


def should_record_read_link() -> bool:
    """Return whether the current run should queue a read-link edge."""
    return bool(_in_agent_run() and discover_agent_identity())


def _in_agent_run() -> bool:
    return bool(os.environ.get("SASE_AGENT"))


def record_read_link(
    target_ref: str,
    *,
    reason: str,
    resolve_store: Callable[[], Any] | None = None,
) -> None:
    """Queue a pending read-link row without writing sidecar VCS state.

    A bare read must never create git dirt or a commit obligation on its
    own, so the row stays local in the read-link outbox until this run
    earns publish eligibility -- see ``sase.sdd.artifact_link_outbox`` and
    ``sase.sdd.artifact_link_release_evidence``. Callers that resolve the
    link store through their own module namespace (so tests can substitute
    it) pass that resolver as *resolve_store*; otherwise the shared store
    is resolved directly.
    """
    identity = discover_agent_identity()
    if identity is None:
        return
    store = (resolve_store or resolve_artifact_link_store)()
    target = canonicalize_artifact_link_ref(target_ref)
    source = f"agent:{identity.name}"
    row = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": source,
        "relation": "read",
        "target_ref": target,
        "description": reason,
        "origin": "read",
        "created_by": identity.name,
        "created_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "uses": 1,
    }
    append_artifact_link_outbox_entry(
        project_key=store.project_key,
        agent_name=identity.name,
        run_id=os.environ.get("SASE_AGENT_TIMESTAMP", ""),
        row=row,
    )


__all__ = [
    "READ_NOT_RECORDED_NOTE",
    "record_read_link",
    "should_record_read_link",
]
