"""Shared types, exit codes, and errors for TUI screenshot maintenance."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


EXIT_SUCCESS = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2
EXIT_FAILURE = 3

MANIFEST_KIND = "visual_maintenance"
MANIFEST_SCHEMA_VERSION = 1
JOURNAL_KIND = "visual_maintenance_journal"
JOURNAL_SCHEMA_VERSION = 1
CACHE_RELATIVE = ".pytest_cache/sase-visual"
RUNS_DIRNAME = "runs"
JOURNAL_FILENAME = "apply-journal.json"
MANIFEST_FILENAME = "manifest.json"
RUN_FILENAME = "run.json"
LOCK_FILENAME = "maintenance.lock"

KIND_CREATED = "created"
KIND_UPDATED = "updated"
KIND_UNCHANGED = "unchanged"
KIND_STALE = "stale"
ACTIONABLE_KINDS = frozenset({KIND_CREATED, KIND_UPDATED, KIND_STALE})

JOURNAL_PLANNED = "planned"
JOURNAL_APPLYING = "applying"
JOURNAL_APPLIED = "applied"
JOURNAL_ROLLED_BACK = "rolled_back"
JOURNAL_CONFLICT = "conflict"

STATUS_CLEAN = "clean"
STATUS_DRIFT = "drift"
STATUS_APPLIED = "applied"
STATUS_PARTIAL = "partial"
STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

REASON_TEST_FAILED = "test_failed"
REASON_UNSTABLE = "unstable"
REASON_VERIFY_FAILED = "verify_failed"
REASON_OWNER_MISMATCH = "owner_mismatch"
REASON_CONCURRENT_EDIT = "concurrent_edit"
REASON_PROTOCOL_ERROR = "protocol_error"

SKIP_KIND_NODE = "node"
SKIP_KIND_GOLDEN = "golden"


class MaintenanceError(Exception):
    """Screenshot maintenance failed after arguments were accepted."""

    exit_code = EXIT_FAILURE


class UsageError(MaintenanceError):
    """Invalid arguments or environment refusal."""

    exit_code = EXIT_USAGE


class OverlappingRunError(UsageError):
    """Another maintenance run holds the checkout-local lock."""


class VisualPytestFn(Protocol):
    """Governed visual pytest invocation used to collect candidates."""

    def __call__(
        self,
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        workers: int | None = None,
    ) -> int: ...


@dataclass(frozen=True)
class MaintenanceHooks:
    """Test seams for preflight, pytest execution, and environment checks."""

    preflight: Callable[[bool], None] | None = None
    run_pytest: VisualPytestFn | None = None
    is_ci: Callable[[Mapping[str, str]], bool] | None = None
    platform_system: Callable[[], str] | None = None
    renderer_identity: Callable[[], dict[str, Any]] | None = None
    lock_timeout_seconds: float | None = None
    lock_poll_interval_seconds: float | None = None


@dataclass(frozen=True)
class MaintenanceRequest:
    """Parsed invocation for one maintenance run."""

    check: bool
    pytest_args: tuple[str, ...]
    scope: str
    scope_reasons: tuple[str, ...]
    argv: tuple[str, ...]
    workers: int | None = None


@dataclass(frozen=True)
class GoldenFileState:
    """Run-start snapshot of one committed PNG golden."""

    relative_path: str
    sha256: str
    size: int
    mtime_ns: int
    root_identity: str


@dataclass(frozen=True)
class GoldenBaseline:
    """Hashes and dirty paths for both PNG roots at run start."""

    ace_root: Path
    pager_root: Path
    ace_tree_hash: str
    pager_tree_hash: str
    files: dict[str, GoldenFileState]
    dirty_paths: tuple[str, ...]
    git_index_fingerprint: str


@dataclass(frozen=True)
class ChangeRecord:
    """One created, updated, unchanged, or stale screenshot."""

    kind: str
    path: str
    root_identity: str
    node_id: str | None
    snapshot_name: str | None
    baseline_sha256: str | None
    candidate_sha256: str | None
    baseline_width: int | None
    baseline_height: int | None
    candidate_width: int | None
    candidate_height: int | None
    changed_pixels: int | None
    total_pixels: int | None
    material_diff_pixels: int | None
    byte_equal: bool
    encoding_only: bool
    dimension_mismatch: bool
    candidate_png_relpath: str | None
    candidate_svg_relpath: str | None
    artifact_id: str | None
    test_file: str | None = None
    test_line: int | None = None
    source_file: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "root_identity": self.root_identity,
            "node_id": self.node_id,
            "snapshot_name": self.snapshot_name,
            "baseline_sha256": self.baseline_sha256,
            "candidate_sha256": self.candidate_sha256,
            "baseline_width": self.baseline_width,
            "baseline_height": self.baseline_height,
            "candidate_width": self.candidate_width,
            "candidate_height": self.candidate_height,
            "changed_pixels": self.changed_pixels,
            "total_pixels": self.total_pixels,
            "material_diff_pixels": self.material_diff_pixels,
            "byte_equal": self.byte_equal,
            "encoding_only": self.encoding_only,
            "dimension_mismatch": self.dimension_mismatch,
            "candidate_png_relpath": self.candidate_png_relpath,
            "candidate_svg_relpath": self.candidate_svg_relpath,
            "artifact_id": self.artifact_id,
            "test_file": self.test_file,
            "test_line": self.test_line,
            "source_file": self.source_file,
            "source_line": self.source_line,
        }


@dataclass(frozen=True)
class SkippedRecord:
    """One node or golden the run left untouched behind a warning."""

    kind: str
    node_id: str | None
    path: str | None
    reason: str
    detail: str
    evidence: tuple[str, ...] = ()
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "node_id": self.node_id,
            "path": self.path,
            "reason": self.reason,
            "detail": self.detail,
            "evidence": list(self.evidence),
            "attempts": self.attempts,
        }


@dataclass(frozen=True)
class AttemptRecord:
    """One governed pytest pass that contributed to the run."""

    label: str
    run_id: str
    capture_dir: str
    log: str
    workers: int | None
    child_exit_code: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "run_id": self.run_id,
            "capture_dir": self.capture_dir,
            "log": self.log,
            "workers": self.workers,
            "child_exit_code": self.child_exit_code,
        }


@dataclass
class ChangeManifest:
    """Machine-readable input for the screenshot change-reports phase."""

    run_id: str
    mode: str
    status: str
    requested_scope: str
    scope_reasons: tuple[str, ...]
    full_inventory: bool
    pruning_allowed: bool
    complete: bool
    exit_code: int
    child_exit_code: int | None
    counts: dict[str, int]
    dirty_before: tuple[str, ...]
    changes: tuple[ChangeRecord, ...]
    roots: dict[str, dict[str, str]]
    renderer: dict[str, Any]
    arguments: tuple[str, ...]
    pytest_args: tuple[str, ...]
    inventory_reasons: tuple[str, ...]
    errors: tuple[str, ...]
    run_dir: str
    capture_dir: str
    verify_dir: str | None
    manifest_path: str
    journal_path: str | None
    logs: dict[str, str]
    git_index_fingerprint: str
    extra: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    skipped: tuple[SkippedRecord, ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()
    pruning_skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "kind": MANIFEST_KIND,
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "requested_scope": self.requested_scope,
            "scope_reasons": list(self.scope_reasons),
            "full_inventory": self.full_inventory,
            "pruning_allowed": self.pruning_allowed,
            "complete": self.complete,
            "exit_code": self.exit_code,
            "child_exit_code": self.child_exit_code,
            "counts": dict(self.counts),
            "dirty_before": list(self.dirty_before),
            "changes": [change.to_dict() for change in self.changes],
            "roots": self.roots,
            "renderer": self.renderer,
            "arguments": list(self.arguments),
            "pytest_args": list(self.pytest_args),
            "inventory_reasons": list(self.inventory_reasons),
            "errors": list(self.errors),
            "run_dir": self.run_dir,
            "capture_dir": self.capture_dir,
            "verify_dir": self.verify_dir,
            "manifest_path": self.manifest_path,
            "journal_path": self.journal_path,
            "logs": dict(self.logs),
            "git_index_fingerprint": self.git_index_fingerprint,
            "warnings": list(self.warnings),
            "skipped": [record.to_dict() for record in self.skipped],
            "attempts": [record.to_dict() for record in self.attempts],
            "pruning_skipped_reason": self.pruning_skipped_reason,
        }
        payload.update(self.extra)
        return payload


def counts_from_changes(changes: Sequence[ChangeRecord]) -> dict[str, int]:
    """Return created/updated/unchanged/stale counts for *changes*."""
    counts = {
        KIND_CREATED: 0,
        KIND_UPDATED: 0,
        KIND_UNCHANGED: 0,
        KIND_STALE: 0,
    }
    for change in changes:
        if change.kind in counts:
            counts[change.kind] += 1
    return counts


def has_actionable_changes(changes: Sequence[ChangeRecord]) -> bool:
    """Return whether any change would write or delete a golden."""
    return any(change.kind in ACTIONABLE_KINDS for change in changes)
