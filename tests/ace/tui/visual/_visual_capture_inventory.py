"""Merged capture inventory and completeness evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from tests.ace.tui.visual._visual_capture_paths import (
    SCHEMA_VERSION,
    VisualCaptureError,
    atomic_write_text,
    visual_root_for_nodeid,
)
from tests.ace.tui.visual._visual_capture_records import (
    CaptureRecord,
    InventoryReport,
    WorkerSessionRecord,
    _capture_from_dict,
    _worker_session_from_dict,
)


def evaluate_inventory(
    *,
    run_id: str,
    requested_scope: str,
    session_exitstatus: int,
    collectonly: bool,
    expected_workers: Sequence[str],
    worker_sessions: Sequence[WorkerSessionRecord],
    captures: Sequence[CaptureRecord],
    lost_workers: Sequence[str] = (),
    load_errors: Sequence[str] = (),
) -> InventoryReport:
    """Classify completeness of a capture run from merged worker evidence."""
    reasons: list[str] = []
    errors: list[str] = []
    errors.extend(load_errors)
    expected = _sorted_unique(expected_workers)
    seen = _sorted_unique(session.worker_id for session in worker_sessions)
    lost = _sorted_unique(lost_workers)

    if requested_scope == "targeted":
        reasons.append("requested_scope_targeted")
    elif requested_scope != "full":
        errors.append(f"invalid_scope:{requested_scope}")

    if collectonly:
        reasons.append("collection_only")
    if session_exitstatus != 0:
        reasons.append(f"session_exitstatus:{session_exitstatus}")

    sessions_by_worker = {session.worker_id: session for session in worker_sessions}
    for worker_id in expected:
        session = sessions_by_worker.get(worker_id)
        if session is None:
            reasons.append(f"missing_worker:{worker_id}")
            continue
        if not session.completed:
            reasons.append(f"incomplete_worker:{worker_id}")
        if session.errors:
            errors.extend(f"worker_error:{worker_id}:{item}" for item in session.errors)
    for worker_id in seen:
        if worker_id not in expected:
            reasons.append(f"unexpected_worker:{worker_id}")
    for worker_id in lost:
        reasons.append(f"lost_worker:{worker_id}")

    collected_sets = {
        frozenset(session.collected_node_ids) for session in worker_sessions
    }
    if len(collected_sets) > 1:
        reasons.append("collection_mismatch")

    duplicates = _duplicate_canonical_paths(captures)
    for path, node_ids in duplicates.items():
        message = f"duplicate_canonical_path:{path}:" + ",".join(sorted(node_ids))
        errors.append(message)
        reasons.append(message)

    collected = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.collected_node_ids
    )
    executed = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.executed_node_ids
    )
    skipped = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.skipped_node_ids
    )
    xfailed = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.xfailed_node_ids
    )
    xpassed = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.xpassed_node_ids
    )
    failed = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.failed_node_ids
    )
    errored = _sorted_unique(
        node_id for session in worker_sessions for node_id in session.error_node_ids
    )
    deselected = _sorted_unique(
        node_id
        for session in worker_sessions
        for node_id in session.deselected_node_ids
    )

    visual_collected = tuple(
        node_id for node_id in collected if visual_root_for_nodeid(node_id)
    )
    universe = visual_collected if visual_collected else collected
    visual_deselected = tuple(
        node_id for node_id in deselected if visual_root_for_nodeid(node_id)
    )
    if visual_collected:
        for node_id in visual_deselected:
            reasons.append(f"deselected_visual_node:{node_id}")
    elif requested_scope == "full":
        for node_id in deselected:
            reasons.append(f"deselected_visual_node:{node_id}")

    accounted = set(executed)
    accounted.update(skipped)
    accounted.update(xfailed)
    accounted.update(xpassed)
    accounted.update(failed)
    accounted.update(errored)
    for node_id in universe:
        if node_id not in accounted:
            reasons.append(f"unaccounted_node:{node_id}")
        if node_id in skipped:
            reasons.append(f"skipped_node:{node_id}")
        if node_id in xfailed:
            reasons.append(f"xfailed_node:{node_id}")
        if node_id in xpassed:
            reasons.append(f"xpassed_node:{node_id}")
        if node_id in failed:
            reasons.append(f"failed_node:{node_id}")
        if node_id in errored:
            reasons.append(f"error_node:{node_id}")

    roots_executed = _roots_executed(
        captures=captures,
        executed=executed,
        failed=failed,
        skipped=skipped,
        xfailed=xfailed,
        errored=errored,
    )
    for identity in ("ace", "pager"):
        if identity not in roots_executed:
            reasons.append(f"visual_root_unexecuted:{identity}")

    protocol_ok = not errors
    workers_complete = (
        not collectonly
        and all(
            worker_id in sessions_by_worker and sessions_by_worker[worker_id].completed
            for worker_id in expected
        )
        and not lost
    )
    tests_ok = session_exitstatus == 0 and not collectonly
    complete = protocol_ok and workers_complete and tests_ok
    full_blockers = {
        reason for reason in reasons if reason != "requested_scope_targeted"
    }
    full_inventory = (
        requested_scope == "full"
        and complete
        and not full_blockers
        and set(roots_executed) == {"ace", "pager"}
    )
    if requested_scope == "full":
        complete = full_inventory
    return InventoryReport(
        run_id=run_id,
        requested_scope=requested_scope,
        full_inventory=full_inventory,
        pruning_allowed=full_inventory,
        complete=complete,
        session_exitstatus=session_exitstatus,
        collectonly=collectonly,
        reasons=tuple(sorted(set(reasons))),
        errors=tuple(sorted(set(errors))),
        workers_expected=expected,
        workers_seen=seen,
        lost_workers=lost,
        captures=_sorted_captures(captures),
        worker_sessions=tuple(sorted(worker_sessions, key=lambda item: item.worker_id)),
        collected_visual_node_ids=visual_collected or universe,
        executed_visual_node_ids=tuple(
            node_id for node_id in executed if node_id in universe
        ),
        skipped_visual_node_ids=tuple(
            node_id for node_id in skipped if node_id in universe
        ),
        xfailed_visual_node_ids=tuple(
            node_id for node_id in xfailed if node_id in universe
        ),
        failed_visual_node_ids=tuple(
            node_id for node_id in failed if node_id in universe
        ),
        deselected_visual_node_ids=visual_deselected,
        roots_executed=roots_executed,
    )


def merge_capture_dir(
    capture_dir: Path,
    *,
    run_id: str,
    requested_scope: str,
    expected_workers: Sequence[str],
    session_exitstatus: int,
    collectonly: bool = False,
    lost_workers: Sequence[str] = (),
) -> InventoryReport:
    """Load worker-local records and return the merged inventory."""
    worker_sessions: list[WorkerSessionRecord] = []
    captures: list[CaptureRecord] = []
    load_errors: list[str] = []
    workers_root = capture_dir / "workers"
    if workers_root.is_dir():
        for worker_dir in sorted(workers_root.iterdir()):
            if not worker_dir.is_dir():
                continue
            session_path = worker_dir / "session.json"
            if session_path.is_file():
                session, error = _load_worker_session(session_path, run_id)
                if error is not None:
                    load_errors.append(error)
                elif session is not None:
                    worker_sessions.append(session)
            captures_dir = worker_dir / "captures"
            if not captures_dir.is_dir():
                continue
            for record_path in sorted(captures_dir.glob("*.json")):
                record, error = _load_capture_record(record_path, run_id)
                if error is not None:
                    load_errors.append(error)
                elif record is not None:
                    captures.append(record)
    return evaluate_inventory(
        run_id=run_id,
        requested_scope=requested_scope,
        session_exitstatus=session_exitstatus,
        collectonly=collectonly,
        expected_workers=expected_workers,
        worker_sessions=worker_sessions,
        captures=captures,
        lost_workers=lost_workers,
        load_errors=load_errors,
    )


def write_inventory(capture_dir: Path, inventory: InventoryReport) -> Path:
    """Atomically write *inventory* to ``inventory.json`` under *capture_dir*."""
    path = capture_dir / "inventory.json"
    atomic_write_text(
        path,
        json.dumps(inventory.to_dict(), indent=2, sort_keys=True) + "\n",
    )
    return path


def load_inventory(path: Path) -> InventoryReport:
    """Load a previously written inventory JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise VisualCaptureError(f"inventory is not a JSON object: {path}")
    captures = tuple(
        _capture_from_dict(item)
        for item in raw.get("captures", [])
        if isinstance(item, Mapping)
    )
    sessions = tuple(
        _worker_session_from_dict(item)
        for item in raw.get("worker_sessions", [])
        if isinstance(item, Mapping)
    )
    return InventoryReport(
        run_id=str(raw["run_id"]),
        requested_scope=str(raw["requested_scope"]),
        full_inventory=bool(raw["full_inventory"]),
        pruning_allowed=bool(raw["pruning_allowed"]),
        complete=bool(raw["complete"]),
        session_exitstatus=int(raw["session_exitstatus"]),
        collectonly=bool(raw["collectonly"]),
        reasons=tuple(str(item) for item in raw.get("reasons", [])),
        errors=tuple(str(item) for item in raw.get("errors", [])),
        workers_expected=tuple(str(item) for item in raw.get("workers_expected", [])),
        workers_seen=tuple(str(item) for item in raw.get("workers_seen", [])),
        lost_workers=tuple(str(item) for item in raw.get("lost_workers", [])),
        captures=captures,
        worker_sessions=sessions,
        collected_visual_node_ids=tuple(
            str(item) for item in raw.get("collected_visual_node_ids", [])
        ),
        executed_visual_node_ids=tuple(
            str(item) for item in raw.get("executed_visual_node_ids", [])
        ),
        skipped_visual_node_ids=tuple(
            str(item) for item in raw.get("skipped_visual_node_ids", [])
        ),
        xfailed_visual_node_ids=tuple(
            str(item) for item in raw.get("xfailed_visual_node_ids", [])
        ),
        failed_visual_node_ids=tuple(
            str(item) for item in raw.get("failed_visual_node_ids", [])
        ),
        deselected_visual_node_ids=tuple(
            str(item) for item in raw.get("deselected_visual_node_ids", [])
        ),
        roots_executed=tuple(str(item) for item in raw.get("roots_executed", [])),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        kind=str(raw.get("kind", "inventory")),
    )


def _load_worker_session(
    path: Path, run_id: str
) -> tuple[WorkerSessionRecord | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"malformed_worker:{path.parent.name}:{exc}"
    if not isinstance(raw, Mapping):
        return None, f"malformed_worker:{path.parent.name}:not an object"
    try:
        record = _worker_session_from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        return None, f"malformed_worker:{path.parent.name}:{exc}"
    if record.run_id != run_id:
        return None, None
    return record, None


def _load_capture_record(
    path: Path, run_id: str
) -> tuple[CaptureRecord | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"invalid_capture:{path.stem}:{exc}"
    if not isinstance(raw, Mapping):
        return None, f"invalid_capture:{path.stem}:not an object"
    try:
        record = _capture_from_dict(raw)
    except (KeyError, TypeError, ValueError, VisualCaptureError) as exc:
        return None, f"invalid_capture:{path.stem}:{exc}"
    if record.run_id != run_id:
        return None, None
    if ".." in Path(record.canonical_golden_path).parts:
        return None, (f"invalid_capture:{path.stem}:escaped canonical path")
    return record, None


def _duplicate_canonical_paths(
    captures: Sequence[CaptureRecord],
) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for record in captures:
        owners[record.canonical_golden_path].add(record.node_id)
        counts[record.canonical_golden_path] += 1
    return {path: node_ids for path, node_ids in owners.items() if counts[path] > 1}


def _roots_executed(
    *,
    captures: Sequence[CaptureRecord],
    executed: Sequence[str],
    failed: Sequence[str],
    skipped: Sequence[str],
    xfailed: Sequence[str],
    errored: Sequence[str],
) -> tuple[str, ...]:
    found: set[str] = {record.root_identity for record in captures}
    evidence_nodes = {
        *executed,
        *failed,
        *skipped,
        *xfailed,
        *errored,
    }
    for node_id in evidence_nodes:
        identity = visual_root_for_nodeid(node_id)
        if identity is not None:
            found.add(identity)
    return tuple(sorted(found))


def _sorted_captures(
    captures: Sequence[CaptureRecord],
) -> tuple[CaptureRecord, ...]:
    return tuple(
        sorted(
            captures,
            key=lambda record: (
                record.canonical_golden_path,
                record.node_id,
                record.worker_id,
                record.sequence,
            ),
        )
    )


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))
