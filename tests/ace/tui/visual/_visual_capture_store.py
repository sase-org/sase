"""Versioned capture records, worker-local writes, and inventory merge."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import inspect
import json
import os
from pathlib import Path
import threading
from typing import Any

from tests.ace.tui.visual._visual_capture_paths import (
    SCHEMA_VERSION,
    VisualCaptureError,
    VisualCaptureRoots,
    atomic_write_bytes,
    atomic_write_text,
    capture_artifact_id,
    canonical_golden_path,
    png_dimensions,
    sha256_bytes,
    visual_root_for_nodeid,
    worker_directory,
)


_ENV_RATIO = "SASE_VISUAL_PNG_MAX_DIFF_RATIO"
_ENV_THRESHOLD = "SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD"
_ENV_MATERIAL_PIXELS = "SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS"
_INTERNAL_FRAMES = frozenset(
    {
        "_visual_capture_store.py",
        "_visual_capture.py",
        "_visual_capture_paths.py",
        "_visual_capture_plugin.py",
        "png_diff.py",
    }
)


@dataclass(frozen=True)
class ComparisonSettings:
    """Comparison kwargs and env overrides in force at capture time."""

    max_diff_pixels: int | None
    max_diff_ratio: float | None
    material_diff_threshold: int | None
    max_material_diff_pixels: int | None
    env_max_diff_ratio: str | None
    env_material_diff_threshold: str | None
    env_max_material_diff_pixels: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_diff_pixels": self.max_diff_pixels,
            "max_diff_ratio": self.max_diff_ratio,
            "material_diff_threshold": self.material_diff_threshold,
            "max_material_diff_pixels": self.max_material_diff_pixels,
            "env_max_diff_ratio": self.env_max_diff_ratio,
            "env_material_diff_threshold": self.env_material_diff_threshold,
            "env_max_material_diff_pixels": self.env_max_material_diff_pixels,
        }


@dataclass(frozen=True)
class CaptureRecord:
    """One candidate PNG captured by a visual snapshot assertion."""

    run_id: str
    worker_id: str
    sequence: int
    node_sequence: int
    artifact_id: str
    node_id: str
    snapshot_name: str
    canonical_golden_path: str
    root_identity: str
    test_file: str | None
    test_line: int | None
    source_file: str | None
    source_line: int | None
    candidate_png_relpath: str
    candidate_svg_relpath: str | None
    candidate_sha256: str
    png_width: int
    png_height: int
    comparison_settings: ComparisonSettings
    schema_version: int = SCHEMA_VERSION
    kind: str = "capture"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "sequence": self.sequence,
            "node_sequence": self.node_sequence,
            "artifact_id": self.artifact_id,
            "node_id": self.node_id,
            "snapshot_name": self.snapshot_name,
            "canonical_golden_path": self.canonical_golden_path,
            "root_identity": self.root_identity,
            "test_file": self.test_file,
            "test_line": self.test_line,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "candidate_png_relpath": self.candidate_png_relpath,
            "candidate_svg_relpath": self.candidate_svg_relpath,
            "candidate_sha256": self.candidate_sha256,
            "png_width": self.png_width,
            "png_height": self.png_height,
            "comparison_settings": self.comparison_settings.to_dict(),
        }


@dataclass(frozen=True)
class WorkerSessionRecord:
    """Execution completeness evidence for one pytest worker."""

    run_id: str
    worker_id: str
    completed: bool
    collectonly: bool
    exitstatus: int | None
    collected_node_ids: tuple[str, ...]
    executed_node_ids: tuple[str, ...]
    skipped_node_ids: tuple[str, ...]
    xfailed_node_ids: tuple[str, ...]
    xpassed_node_ids: tuple[str, ...]
    failed_node_ids: tuple[str, ...]
    error_node_ids: tuple[str, ...]
    deselected_node_ids: tuple[str, ...]
    capture_count: int
    errors: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION
    kind: str = "worker_session"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "completed": self.completed,
            "collectonly": self.collectonly,
            "exitstatus": self.exitstatus,
            "collected_node_ids": list(self.collected_node_ids),
            "executed_node_ids": list(self.executed_node_ids),
            "skipped_node_ids": list(self.skipped_node_ids),
            "xfailed_node_ids": list(self.xfailed_node_ids),
            "xpassed_node_ids": list(self.xpassed_node_ids),
            "failed_node_ids": list(self.failed_node_ids),
            "error_node_ids": list(self.error_node_ids),
            "deselected_node_ids": list(self.deselected_node_ids),
            "capture_count": self.capture_count,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class InventoryReport:
    """Merged capture inventory and completeness evidence."""

    run_id: str
    requested_scope: str
    full_inventory: bool
    pruning_allowed: bool
    complete: bool
    session_exitstatus: int
    collectonly: bool
    reasons: tuple[str, ...]
    errors: tuple[str, ...]
    workers_expected: tuple[str, ...]
    workers_seen: tuple[str, ...]
    lost_workers: tuple[str, ...]
    captures: tuple[CaptureRecord, ...]
    worker_sessions: tuple[WorkerSessionRecord, ...]
    collected_visual_node_ids: tuple[str, ...]
    executed_visual_node_ids: tuple[str, ...]
    skipped_visual_node_ids: tuple[str, ...]
    xfailed_visual_node_ids: tuple[str, ...]
    failed_visual_node_ids: tuple[str, ...]
    deselected_visual_node_ids: tuple[str, ...]
    roots_executed: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    kind: str = "inventory"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "requested_scope": self.requested_scope,
            "full_inventory": self.full_inventory,
            "pruning_allowed": self.pruning_allowed,
            "complete": self.complete,
            "session_exitstatus": self.session_exitstatus,
            "collectonly": self.collectonly,
            "reasons": list(self.reasons),
            "errors": list(self.errors),
            "workers_expected": list(self.workers_expected),
            "workers_seen": list(self.workers_seen),
            "lost_workers": list(self.lost_workers),
            "captures": [record.to_dict() for record in self.captures],
            "worker_sessions": [record.to_dict() for record in self.worker_sessions],
            "collected_visual_node_ids": list(self.collected_visual_node_ids),
            "executed_visual_node_ids": list(self.executed_visual_node_ids),
            "skipped_visual_node_ids": list(self.skipped_visual_node_ids),
            "xfailed_visual_node_ids": list(self.xfailed_visual_node_ids),
            "failed_visual_node_ids": list(self.failed_visual_node_ids),
            "deselected_visual_node_ids": list(self.deselected_visual_node_ids),
            "roots_executed": list(self.roots_executed),
        }


@dataclass
class VisualCaptureSession:
    """Worker-local candidate writer used by ACE and pager fixtures."""

    capture_dir: Path
    run_id: str
    worker_id: str
    repo_root: Path
    roots: VisualCaptureRoots
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _captures: list[CaptureRecord] = field(default_factory=list, repr=False)
    _owned_paths: dict[str, str] = field(default_factory=dict, repr=False)
    _sequence: int = field(default=0, repr=False)
    _node_sequence: dict[str, int] = field(default_factory=dict, repr=False)

    def owns_root(self, snapshot_root: Path) -> bool:
        """Return whether *snapshot_root* is an ACE or pager golden root."""
        return self.roots.identity_for(snapshot_root) is not None

    @property
    def captures(self) -> tuple[CaptureRecord, ...]:
        with self._lock:
            return tuple(self._captures)

    @property
    def worker_dir(self) -> Path:
        return worker_directory(self.capture_dir, self.worker_id)

    def record_capture(
        self,
        *,
        name: str,
        png_bytes: bytes,
        snapshot_root: Path,
        node_id: str,
        source_svg: str | None = None,
        test_file: str | None = None,
        test_line: int | None = None,
        max_diff_pixels: int | None = None,
        max_diff_ratio: float | None = None,
        material_diff_threshold: int | None = None,
        max_material_diff_pixels: int | None = None,
    ) -> CaptureRecord:
        """Write candidate PNG/SVG and metadata without touching goldens."""
        identity, canonical = canonical_golden_path(
            snapshot_root=snapshot_root,
            name=name,
            repo_root=self.repo_root,
            roots=self.roots,
        )
        width, height = png_dimensions(png_bytes)
        source_file, source_line = _call_location(self.repo_root)
        with self._lock:
            owner = self._owned_paths.get(canonical)
            if owner is not None:
                raise VisualCaptureError(
                    "duplicate canonical golden path "
                    f"{canonical}: owned by {owner} and {node_id}"
                )
            self._sequence += 1
            sequence = self._sequence
            node_sequence = self._node_sequence.get(node_id, 0) + 1
            self._node_sequence[node_id] = node_sequence
            artifact_id = capture_artifact_id(
                node_id=node_id,
                canonical_golden_path=canonical,
                sequence=sequence,
                worker_id=self.worker_id,
            )
            png_relpath = f"workers/{self.worker_id}/candidates/{artifact_id}.png"
            svg_relpath = (
                None
                if source_svg is None
                else f"workers/{self.worker_id}/candidates/{artifact_id}.svg"
            )
            record = CaptureRecord(
                run_id=self.run_id,
                worker_id=self.worker_id,
                sequence=sequence,
                node_sequence=node_sequence,
                artifact_id=artifact_id,
                node_id=node_id,
                snapshot_name=name,
                canonical_golden_path=canonical,
                root_identity=identity,
                test_file=_repo_relative_optional(test_file, self.repo_root),
                test_line=test_line,
                source_file=source_file,
                source_line=source_line,
                candidate_png_relpath=png_relpath,
                candidate_svg_relpath=svg_relpath,
                candidate_sha256=sha256_bytes(png_bytes),
                png_width=width,
                png_height=height,
                comparison_settings=ComparisonSettings(
                    max_diff_pixels=max_diff_pixels,
                    max_diff_ratio=max_diff_ratio,
                    material_diff_threshold=material_diff_threshold,
                    max_material_diff_pixels=max_material_diff_pixels,
                    env_max_diff_ratio=os.environ.get(_ENV_RATIO),
                    env_material_diff_threshold=os.environ.get(_ENV_THRESHOLD),
                    env_max_material_diff_pixels=os.environ.get(_ENV_MATERIAL_PIXELS),
                ),
            )
            png_path = self.capture_dir / png_relpath
            atomic_write_bytes(png_path, png_bytes)
            if source_svg is not None and svg_relpath is not None:
                atomic_write_text(self.capture_dir / svg_relpath, source_svg)
            record_path = self.worker_dir / "captures" / f"{artifact_id}.json"
            atomic_write_text(
                record_path,
                json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
            )
            self._owned_paths[canonical] = node_id
            self._captures.append(record)
            return record

    def write_worker_session(self, record: WorkerSessionRecord) -> Path:
        """Atomically write this worker's execution-evidence record."""
        if record.worker_id != self.worker_id or record.run_id != self.run_id:
            raise VisualCaptureError(
                "worker session record does not match this capture session"
            )
        path = self.worker_dir / "session.json"
        atomic_write_text(
            path,
            json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
        )
        return path


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


def _capture_from_dict(raw: Mapping[str, Any]) -> CaptureRecord:
    settings_raw = raw.get("comparison_settings")
    if not isinstance(settings_raw, Mapping):
        settings_raw = {}
    return CaptureRecord(
        run_id=str(raw["run_id"]),
        worker_id=str(raw["worker_id"]),
        sequence=int(raw["sequence"]),
        node_sequence=int(raw["node_sequence"]),
        artifact_id=str(raw["artifact_id"]),
        node_id=str(raw["node_id"]),
        snapshot_name=str(raw["snapshot_name"]),
        canonical_golden_path=str(raw["canonical_golden_path"]),
        root_identity=str(raw["root_identity"]),
        test_file=_optional_str(raw.get("test_file")),
        test_line=_optional_int(raw.get("test_line")),
        source_file=_optional_str(raw.get("source_file")),
        source_line=_optional_int(raw.get("source_line")),
        candidate_png_relpath=str(raw["candidate_png_relpath"]),
        candidate_svg_relpath=_optional_str(raw.get("candidate_svg_relpath")),
        candidate_sha256=str(raw["candidate_sha256"]),
        png_width=int(raw["png_width"]),
        png_height=int(raw["png_height"]),
        comparison_settings=ComparisonSettings(
            max_diff_pixels=_optional_int(settings_raw.get("max_diff_pixels")),
            max_diff_ratio=_optional_float(settings_raw.get("max_diff_ratio")),
            material_diff_threshold=_optional_int(
                settings_raw.get("material_diff_threshold")
            ),
            max_material_diff_pixels=_optional_int(
                settings_raw.get("max_material_diff_pixels")
            ),
            env_max_diff_ratio=_optional_str(settings_raw.get("env_max_diff_ratio")),
            env_material_diff_threshold=_optional_str(
                settings_raw.get("env_material_diff_threshold")
            ),
            env_max_material_diff_pixels=_optional_str(
                settings_raw.get("env_max_material_diff_pixels")
            ),
        ),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        kind=str(raw.get("kind", "capture")),
    )


def _worker_session_from_dict(raw: Mapping[str, Any]) -> WorkerSessionRecord:
    return WorkerSessionRecord(
        run_id=str(raw["run_id"]),
        worker_id=str(raw["worker_id"]),
        completed=bool(raw["completed"]),
        collectonly=bool(raw.get("collectonly", False)),
        exitstatus=_optional_int(raw.get("exitstatus")),
        collected_node_ids=_string_tuple(raw.get("collected_node_ids")),
        executed_node_ids=_string_tuple(raw.get("executed_node_ids")),
        skipped_node_ids=_string_tuple(raw.get("skipped_node_ids")),
        xfailed_node_ids=_string_tuple(raw.get("xfailed_node_ids")),
        xpassed_node_ids=_string_tuple(raw.get("xpassed_node_ids")),
        failed_node_ids=_string_tuple(raw.get("failed_node_ids")),
        error_node_ids=_string_tuple(raw.get("error_node_ids")),
        deselected_node_ids=_string_tuple(raw.get("deselected_node_ids")),
        capture_count=int(raw.get("capture_count", 0)),
        errors=_string_tuple(raw.get("errors")),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        kind=str(raw.get("kind", "worker_session")),
    )


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


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _repo_relative_optional(value: str | None, repo_root: Path) -> str | None:
    if value is None:
        return None
    path = Path(value)
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _call_location(repo_root: Path) -> tuple[str | None, int | None]:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            filename = frame.f_code.co_filename
            if Path(filename).name not in _INTERNAL_FRAMES:
                return _repo_relative_optional(filename, repo_root), frame.f_lineno
            frame = frame.f_back
    finally:
        del frame
    return None, None
