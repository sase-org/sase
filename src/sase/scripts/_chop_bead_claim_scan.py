"""Claim-bearing artifact scans for the bead_claim_checks chop.

The idle pre-pass prefers the persistent artifact index so
``scan_agent_artifacts`` only runs when that index is missing or the
legacy full-walk fallback is selected.

Most ticks read a bounded window of the index (see
:func:`sase.scripts._chop_incremental_index.query_claim_window_payloads`).
Once per :data:`CLAIM_FULL_SWEEP_INTERVAL_SECONDS` the pre-pass widens to
full history, which also covers hidden or dismissed rows that never wrote a
done marker and completed rows older than the window. The sweep time is
persisted, so a scheduler restart does not reset the cadence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.claims import BEAD_CLAIM_MARKER
from sase.bead.work_liveness import agent_record_is_alive
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    agent_artifact_records_from_dicts,
)
from sase.core.paths import sase_subdir
from sase.scripts._chop_incremental_index import (
    query_claim_history_payloads,
    query_claim_window_payloads,
)

#: Terminal marker written beside a dead owner's artifact record once its claim
#: has been reconciled. Without it the pre-pass would keep every dead record as
#: a release candidate forever and open bead stores on every tick.
BEAD_CLAIM_RECONCILED_MARKER = "bead_claim_reconciled.json"

#: How often the owner pre-pass widens its bounded index window to full
#: history. Between sweeps, hidden or dismissed owners without a done marker
#: and owners that finished before the window wait at most this long.
CLAIM_FULL_SWEEP_INTERVAL_SECONDS = 3600.0


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
    return ClaimArtifact(
        project_name=record.project_name,
        agent_name=meta.name,
        artifact_dir=artifact_dir,
        timestamp=record.timestamp,
        pid=meta.pid,
        stopped_at=meta.stopped_at,
        bead_id=meta.bead_id,
        bead_claim_promoted=_read_claim_promoted(artifact_dir),
        has_bead_claim_marker=(artifact_dir / BEAD_CLAIM_MARKER).exists(),
        has_reconcile_tombstone=(artifact_dir / BEAD_CLAIM_RECONCILED_MARKER).exists(),
        is_alive=agent_record_is_alive(record),
    )


def claim_artifacts_from_index(
    projects_root: Path,
    *,
    full_history: bool,
    now: float | None = None,
) -> list[ClaimArtifact] | None:
    """Return the pre-pass's open owner rows from the index, or ``None`` to fall back.

    ``full_history`` selects the periodic full-history sweep; otherwise only
    the bounded claim window is read. The pre-pass acts only on each
    ``(project, agent)`` pair's newest row, and only while that row is not
    tombstoned and its claim was not promoted (``bead_claim_promoted is
    False``). Every other row is dropped from the raw index payload before
    it is rehydrated, so the result holds just the open owners.
    """

    if full_history:
        payloads = query_claim_history_payloads(projects_root)
    else:
        payloads = query_claim_window_payloads(projects_root, now=now)
    if payloads is None:
        return None
    open_owners = [
        payload
        for payload in _latest_owner_payloads(payloads)
        if _may_hold_open_claim(Path(str(payload.get("artifact_dir"))))
    ]
    claims: list[ClaimArtifact] = []
    for record in agent_artifact_records_from_dicts(open_owners):
        claim = claim_artifact_from_record(record)
        if claim is not None:
            claims.append(claim)
    return claims


def _latest_owner_payloads(
    payloads: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Keep each ``(project, agent)`` pair's newest raw row, like the chop does."""

    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for payload in payloads:
        meta = payload.get("agent_meta")
        if not isinstance(meta, Mapping):
            continue
        key = (str(payload.get("project_name")), str(meta.get("name")))
        previous = latest.get(key)
        if previous is None or str(payload.get("timestamp")) > str(
            previous.get("timestamp")
        ):
            latest[key] = payload
    return list(latest.values())


def _may_hold_open_claim(artifact_dir: Path) -> bool:
    """Return whether the pre-pass could act on this owner row at all."""

    if (artifact_dir / BEAD_CLAIM_RECONCILED_MARKER).exists():
        return False
    return _read_claim_promoted(artifact_dir) is False


def _read_claim_promoted(artifact_dir: Path) -> bool | None:
    """Return ``bead_claim_promoted``; ``None`` when ``agent_meta.json`` is unreadable."""

    raw_meta = _read_json_dict(artifact_dir / "agent_meta.json")
    if raw_meta is None:
        # An unreadable marker cannot prove that the claim was never promoted.
        return None
    return raw_meta.get("bead_claim_promoted") is True


def _full_sweep_stamp_path() -> Path:
    return sase_subdir("axe") / "bead_claim_checks_last_full_sweep"


def claim_full_sweep_due(now: float) -> bool:
    """Return whether the pre-pass should read full history this tick."""

    try:
        stamp = float(_full_sweep_stamp_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    # A stamp from the future (clock step) must not suppress sweeps forever.
    return not 0 <= now - stamp < CLAIM_FULL_SWEEP_INTERVAL_SECONDS


def record_claim_full_sweep(now: float) -> None:
    """Persist that a full-history pre-pass completed at *now* (best effort)."""

    path = _full_sweep_stamp_path()
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(f"{now}\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        pass
