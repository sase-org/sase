"""Claim-bearing artifact scans for the bead_claim_checks chop.

The idle pre-pass prefers the persistent artifact index so
``scan_agent_artifacts`` only runs when that index is missing or the
legacy full-walk fallback is selected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.claims import BEAD_CLAIM_MARKER
from sase.bead.work_liveness import agent_record_is_alive
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.scripts._chop_incremental_index import query_ace_run_index_records

#: Terminal marker written beside a dead owner's artifact record once its claim
#: has been reconciled. Without it the pre-pass would keep every dead record as
#: a release candidate forever and open bead stores on every tick.
BEAD_CLAIM_RECONCILED_MARKER = "bead_claim_reconciled.json"


@dataclass(frozen=True)
class ClaimArtifact:
    project_name: str
    agent_name: str
    artifact_dir: Path
    timestamp: str
    pid: int | None
    stopped_at: str | None
    bead_id: str
    bead_claim_promoted: bool | None
    has_bead_claim_marker: bool
    has_reconcile_tombstone: bool = False
    is_alive: bool = False


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def claim_artifact_from_record(record: AgentArtifactRecordWire) -> ClaimArtifact | None:
    """Project one scan/index record into a claim-bearing owner row."""

    meta = record.agent_meta
    if (
        record.workflow_dir_name != "ace-run"
        or meta is None
        or not meta.name
        or not meta.bead_id
    ):
        return None

    artifact_dir = Path(record.artifact_dir)
    raw_meta = _read_json_dict(artifact_dir / "agent_meta.json")
    promoted: bool | None
    if raw_meta is None:
        # An unreadable marker cannot prove that the claim was never promoted.
        promoted = None
    else:
        promoted = raw_meta.get("bead_claim_promoted") is True

    return ClaimArtifact(
        project_name=record.project_name,
        agent_name=meta.name,
        artifact_dir=artifact_dir,
        timestamp=record.timestamp,
        pid=meta.pid,
        stopped_at=meta.stopped_at,
        bead_id=meta.bead_id,
        bead_claim_promoted=promoted,
        has_bead_claim_marker=(artifact_dir / BEAD_CLAIM_MARKER).exists(),
        has_reconcile_tombstone=(artifact_dir / BEAD_CLAIM_RECONCILED_MARKER).exists(),
        is_alive=agent_record_is_alive(record),
    )


def claim_artifacts_from_index(projects_root: Path) -> list[ClaimArtifact] | None:
    """Return claim-bearing rows from the artifact index, or ``None`` to fall back."""

    records = query_ace_run_index_records(projects_root)
    if records is None:
        return None
    claims: list[ClaimArtifact] = []
    for record in records:
        claim = claim_artifact_from_record(record)
        if claim is not None:
            claims.append(claim)
    return claims
