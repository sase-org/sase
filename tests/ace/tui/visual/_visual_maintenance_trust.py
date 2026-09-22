"""Node-trust policy for salvaging update-mode screenshot runs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    REASON_CONCURRENT_EDIT,
    REASON_PROTOCOL_ERROR,
    SKIP_KIND_GOLDEN,
    ChangeRecord,
    GoldenBaseline,
    SkippedRecord,
)


DUPLICATE_PATH_PREFIX = "duplicate_canonical_path:"

CURED_REASON_PREFIXES = (
    "failed_node:",
    "error_node:",
    "unaccounted_node:",
    "incomplete_worker:",
    "lost_worker:",
    "missing_worker:",
    "session_exitstatus:",
)

STALE_LEFT_BEHIND = "stale goldens were left in place"


def derive_node_trust(
    inventory: InventoryReport,
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Split visual nodes into trusted nodes and the recover set.

    Trusted nodes executed on a worker whose session completed and were
    not failed, errored, skipped, xfailed, or xpassed. The recover set is
    failed ∪ errored ∪ collected-but-unaccounted visual nodes, including
    nodes stranded on lost or incomplete workers.
    """
    executed: set[str] = set()
    failed: set[str] = set()
    errored: set[str] = set()
    skipped: set[str] = set()
    xfailed: set[str] = set()
    xpassed: set[str] = set()
    for session in inventory.worker_sessions:
        if session.completed:
            executed.update(session.executed_node_ids)
        failed.update(session.failed_node_ids)
        errored.update(session.error_node_ids)
        skipped.update(session.skipped_node_ids)
        xfailed.update(session.xfailed_node_ids)
        xpassed.update(session.xpassed_node_ids)
    trusted = frozenset(executed - failed - errored - skipped - xfailed - xpassed)
    accounted = executed | skipped | xfailed | xpassed | failed | errored
    recover = sorted(
        set(failed)
        | set(errored)
        | {
            node_id
            for node_id in inventory.collected_visual_node_ids
            if node_id not in accounted
        }
    )
    return trusted, tuple(recover)


def trusted_captures(
    inventory: InventoryReport,
    trusted: frozenset[str],
) -> list[CaptureRecord]:
    """Return captures whose node is trusted, in inventory order."""
    return [record for record in inventory.captures if record.node_id in trusted]


def split_protocol_errors(
    errors: Sequence[str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Split inventory errors into path-attributable and unattributable.

    Duplicate-ownership errors name the implicated canonical golden path;
    everything else (malformed workers, invalid captures, scope errors)
    cannot be attributed to one golden.
    """
    attributable: dict[str, list[str]] = {}
    unattributable: list[str] = []
    for error in errors:
        path = _duplicate_error_path(error)
        if path is None:
            unattributable.append(error)
        else:
            attributable.setdefault(path, []).append(error)
    return attributable, unattributable


def extract_failed_lines(log_path: Path, *, limit: int = 5) -> tuple[str, ...]:
    """Return ``FAILED ...`` summary lines from a pytest log, if any."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("FAILED ")
    ]
    return tuple(lines[:limit])


def pruning_gate(
    *,
    requested_scope: str,
    inventory: InventoryReport,
    trusted: frozenset[str],
    protocol_errors: Sequence[str],
    trusted_records: Sequence[CaptureRecord],
    baseline: GoldenBaseline,
) -> tuple[bool, str | None]:
    """Decide whether stale-golden removal is proven safe.

    Return ``(True, None)`` only when every gate in the salvage contract
    holds; otherwise return ``(False, reason)`` describing why stale
    removal was skipped.
    """
    if requested_scope != "full":
        return False, f"requested scope was not full; {STALE_LEFT_BEHIND}"
    untrusted = [
        node_id
        for node_id in inventory.collected_visual_node_ids
        if node_id not in trusted
        and node_id not in inventory.skipped_visual_node_ids
        and node_id not in inventory.xfailed_visual_node_ids
    ]
    if untrusted:
        names = ", ".join(sorted(untrusted)[:5])
        return False, (
            f"capture evidence is incomplete for {len(untrusted)} node(s) "
            f"({names}); {STALE_LEFT_BEHIND}"
        )
    remaining = [
        reason
        for reason in inventory.reasons
        if not reason.startswith(CURED_REASON_PREFIXES)
    ]
    if remaining:
        names = ", ".join(sorted(remaining)[:5])
        return False, (
            f"capture inventory is incomplete ({names}); {STALE_LEFT_BEHIND}"
        )
    if protocol_errors:
        names = ", ".join(sorted(set(protocol_errors))[:3])
        return False, (f"capture protocol errors ({names}); {STALE_LEFT_BEHIND}")
    if not trusted_records:
        return False, f"no trusted screenshot captures; {STALE_LEFT_BEHIND}"
    captured_roots = {record.root_identity for record in trusted_records}
    for identity in ("ace", "pager"):
        has_goldens = any(
            state.root_identity == identity for state in baseline.files.values()
        )
        if has_goldens and identity not in captured_roots:
            return False, (f"no trusted {identity} screenshots; {STALE_LEFT_BEHIND}")
    return True, None


def filter_concurrent_edits(
    changes: Sequence[ChangeRecord],
    conflicts: Sequence[str],
) -> tuple[tuple[ChangeRecord, ...], tuple[SkippedRecord, ...]]:
    """Split *changes* into applicable changes and concurrent-edit skips."""
    edited = {_conflict_path(conflict) for conflict in conflicts}
    edited.discard("")
    kept: list[ChangeRecord] = []
    skipped: list[SkippedRecord] = []
    for change in changes:
        if change.path in edited:
            skipped.append(
                SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=change.node_id,
                    path=change.path,
                    reason=REASON_CONCURRENT_EDIT,
                    detail=("golden changed on disk during the run; left untouched"),
                )
            )
        else:
            kept.append(change)
    return tuple(kept), tuple(skipped)


def stale_records_for(
    trusted: Sequence[CaptureRecord],
    *,
    baseline: GoldenBaseline,
    repo_root: Path,
) -> tuple[ChangeRecord, ...]:
    """Return stale records for baseline goldens no trusted capture covers."""
    from tests.ace.tui.visual._visual_maintenance_compare import _stale_record

    captured_paths = {record.canonical_golden_path for record in trusted}
    return tuple(
        _stale_record(state, repo_root=repo_root)
        for relative, state in sorted(baseline.files.items())
        if relative not in captured_paths
    )


def protocol_error_skip(
    path: str | None,
    detail: str,
    *,
    evidence: Sequence[str] = (),
) -> SkippedRecord:
    """Build a golden skip record for a capture protocol problem."""
    return SkippedRecord(
        kind=SKIP_KIND_GOLDEN,
        node_id=None,
        path=path,
        reason=REASON_PROTOCOL_ERROR,
        detail=detail,
        evidence=tuple(evidence),
        attempts=1,
    )


def _duplicate_error_path(error: str) -> str | None:
    if not error.startswith(DUPLICATE_PATH_PREFIX):
        return None
    rest = error[len(DUPLICATE_PATH_PREFIX) :]
    path, separator, _owners = rest.partition(":")
    if not separator or not path:
        return None
    return path


def _conflict_path(conflict: str) -> str:
    _kind, separator, path = conflict.partition(":")
    return path if separator else conflict
