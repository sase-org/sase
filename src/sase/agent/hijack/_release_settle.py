"""Settlement for snapshot-verified release resolutions.

A dismiss claims the record to ``dismissed`` and rewrites the predecessor's
``done.json`` recovery to ``dismissed`` so waiters read ``killed``. A restart
claims the record to ``resolved`` with the relaunched successor recorded, so a
failed relaunch after the workspace is released stays recoverable from the
ledger's prompt and snapshot refs. Both paths are idempotent: re-settling an
already-settled record repairs the ``done.json`` projection.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack.recover_common import RecoveryRefusal, clean_string

LOG = logging.getLogger(__name__)


def settle_release_dismiss(resolving: Mapping[str, Any]) -> dict[str, Any]:
    """Settle a resolving dismiss record to ``dismissed``.

    Advances the ledger with ``complete_resolution`` (the Rust state machine
    routes dismiss-action records to ``dismissed``) and rewrites the
    predecessor ``done.json`` recovery marker. The marker write is best
    effort: a wiped predecessor row still leaves a durable ledger record.
    """
    record = dict(resolving)
    _check_predecessor_outcome(record)
    try:
        settled = ledger.cas_advance_record(record, {"event": "complete_resolution"})
    except ledger.HijackLedgerConflict as exc:
        raise RecoveryRefusal(
            "settlement_conflict",
            f"The dismiss settlement lost its ledger write: {exc}",
        ) from exc
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected", f"The dismiss settlement was rejected: {exc}"
        ) from exc
    _write_dismissed_marker(record)
    return _fresh_record(record, settled)


def settle_release_restart(
    resolving: Mapping[str, Any], *, successor: str | None
) -> dict[str, Any]:
    """Settle a resolving restart record to ``resolved``.

    The relaunched successor name is recorded on the ledger so a failed
    relaunch after release stays recoverable; the predecessor ``done.json``
    recovery is rewritten best effort.
    """
    record = dict(resolving)
    _check_predecessor_outcome(record)
    try:
        settled = ledger.cas_advance_record(record, {"event": "complete_resolution"})
    except ledger.HijackLedgerConflict as exc:
        raise RecoveryRefusal(
            "settlement_conflict",
            f"The restart settlement lost its ledger write: {exc}",
        ) from exc
    except ValueError as exc:
        raise RecoveryRefusal(
            "ledger_rejected", f"The restart settlement was rejected: {exc}"
        ) from exc
    _write_resolved_marker(record, action="restart", successor=successor)
    return _fresh_record(record, settled)


def _check_predecessor_outcome(record: Mapping[str, Any]) -> None:
    """Refuse settlement when the predecessor marker left ``hijacked`` behind."""
    from sase.history.chat_fork.common import load_json_object

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return
    payload = load_json_object(Path(artifacts_dir) / "done.json")
    if not isinstance(payload, Mapping):
        return
    outcome = payload.get("outcome")
    if not isinstance(outcome, str):
        return
    if outcome.strip().lower() != "hijacked":
        raise RecoveryRefusal(
            "outcome_changed",
            f"The predecessor outcome is {outcome!r}, not hijacked; a release "
            "resolution must not rewrite its marker",
        )


def _fresh_record(
    resolving: Mapping[str, Any], settled: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the freshly loaded record, falling back to the CAS result."""
    hijack_id = clean_string(resolving.get("hijack_id"))
    if hijack_id is None:
        return dict(settled)
    reloaded = ledger.load_record(hijack_id)
    if isinstance(reloaded, Mapping) and reloaded:
        return dict(reloaded)
    return dict(settled)


def _write_dismissed_marker(record: Mapping[str, Any]) -> None:
    """Rewrite the predecessor ``done.json`` recovery to ``dismissed``."""
    _write_recovery_marker(
        record,
        {"state": "dismissed", "action": "dismiss"},
    )


def _write_resolved_marker(
    record: Mapping[str, Any], *, action: str, successor: str | None
) -> None:
    """Rewrite the predecessor ``done.json`` recovery to ``resolved``."""
    recovery: dict[str, Any] = {"state": "resolved", "action": action}
    if successor:
        recovery["successor"] = successor
    _write_recovery_marker(record, recovery)


def _write_recovery_marker(record: Mapping[str, Any], recovery: dict[str, Any]) -> None:
    from sase.notification_gates.durability import atomic_write_json

    artifacts_dir = clean_string(record.get("artifacts_dir"))
    if not artifacts_dir:
        return
    path = Path(artifacts_dir) / "done.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    if str(payload.get("outcome") or "").strip().lower() != "hijacked":
        return
    existing = payload.get("recovery")
    merged = dict(existing) if isinstance(existing, Mapping) else {}
    merged.update({"kind": "hijack", **recovery})
    payload["recovery"] = merged
    try:
        atomic_write_json(path, payload)
    except Exception as exc:  # noqa: BLE001 - marker write is best effort
        LOG.warning("could not write release recovery marker for %s: %s", path, exc)
        return
    try:
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(Path(artifacts_dir))
    except Exception as exc:  # noqa: BLE001 - index refresh is best effort
        LOG.warning("could not refresh artifact index for %s: %s", path, exc)


__all__ = [
    "settle_release_dismiss",
    "settle_release_restart",
]
