"""Check-mode serial recapture and strict failure classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import time

from tests.ace.tui.visual._png_diff_comparison import diff_pngs
from tests.ace.tui.visual._visual_capture import InventoryReport
from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes
from tests.ace.tui.visual._visual_capture_records import CaptureRecord
from tests.ace.tui.visual._visual_maintenance_verify_attempts import AttemptDriver
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_selected_captures,
)
from tests.ace.tui.visual._visual_maintenance_manifest import posix_relative
from tests.ace.tui.visual._visual_maintenance_trust import derive_node_trust
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_UNCHANGED,
    KIND_UPDATED,
    REASON_UNSTABLE,
    SKIP_KIND_NODE,
    AttemptRecord,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceHooks,
    SkippedRecord,
)


# Two serial recaptures, capped at 25 nodes, so the 45-minute visual-test job
# still has headroom after a typical 24-33 minute first pass.
MAX_CHECK_RECAPTURE_ATTEMPTS = 2
CHECK_RECAPTURE_NODE_LIMIT = 25
FIRST_ATTEMPT_DIFFS_DIRNAME = "first-attempt-diffs"


@dataclass
class CheckRecaptureResult:
    """Outcome of check-mode serial recapture of first-pass failures."""

    remaining_failed: tuple[str, ...]
    execution_failed: tuple[str, ...]
    unstable: tuple[SkippedRecord, ...]
    remaining_changes: tuple[ChangeRecord, ...]
    attempts: tuple[AttemptRecord, ...]
    logs: dict[str, str]
    warnings: tuple[str, ...]
    verify_dir: Path | None
    first_attempt_diffs_dir: str | None
    budget_exhausted: bool = False
    retry_errors: tuple[str, ...] = ()
    retry_trusted: tuple[str, ...] = ()


def first_pass_failed_nodes(
    inventory: InventoryReport,
    changes: Sequence[ChangeRecord],
) -> tuple[str, ...]:
    """Return visual node IDs that failed the first check-mode pass.

    Includes pytest failures/errors/unaccounted nodes and owners of created
    or updated captures. Stale goldens are not recaptured: they are missing
    tests, not a capture race.
    """
    _trusted, recover = derive_node_trust(inventory)
    drifted = {
        change.node_id
        for change in changes
        if change.kind in {KIND_CREATED, KIND_UPDATED} and change.node_id
    }
    return tuple(sorted(set(recover) | drifted))


def write_first_attempt_diffs(
    run_dir: Path,
    changes: Sequence[ChangeRecord],
    *,
    repo_root: Path,
    capture_dir: Path,
) -> Path | None:
    """Write first-pass actual/expected/diff PNGs for drifted captures."""
    drifted = [
        change for change in changes if change.kind in {KIND_CREATED, KIND_UPDATED}
    ]
    if not drifted:
        return None
    out_dir = run_dir / FIRST_ATTEMPT_DIFFS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = False
    for change in drifted:
        slug = _diff_slug(change.node_id or change.path)
        node_dir = out_dir / slug
        node_dir.mkdir(parents=True, exist_ok=True)
        expected = repo_root / change.path
        if expected.is_file():
            atomic_write_bytes(node_dir / "expected.png", expected.read_bytes())
            wrote = True
        candidate: bytes | None = None
        if change.candidate_png_relpath:
            candidate_path = capture_dir / change.candidate_png_relpath
            if candidate_path.is_file():
                candidate = candidate_path.read_bytes()
                atomic_write_bytes(node_dir / "actual.png", candidate)
                wrote = True
        if expected.is_file() and candidate is not None:
            try:
                _summary, diff_png = diff_pngs(expected.read_bytes(), candidate)
            except Exception:
                continue
            atomic_write_bytes(node_dir / "diff.png", diff_png)
            wrote = True
    return out_dir if wrote else None


def run_check_recapture(
    *,
    hooks: MaintenanceHooks,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    baseline: GoldenBaseline,
    failed_nodes: Sequence[str],
    first_pass_changes: Sequence[ChangeRecord],
    first_pass_recover: Sequence[str] = (),
    budget_seconds: int | None = None,
) -> CheckRecaptureResult:
    """Re-run first-pass failures serially until they match goldens or attempts end.

    A node is resolved only when one attempt both trusts the node (test
    passed) and classifies every capture as unchanged (exact golden match).
    Resolved nodes are reported as ``unstable``. Check mode never writes
    goldens. Persistent test failures (never trusted on recapture, or
    first-pass recover when recapture never ran) are ``execution_failed``.
    """
    remaining = set(failed_nodes)
    unstable: list[SkippedRecord] = []
    attempts: list[AttemptRecord] = []
    logs: dict[str, str] = {}
    warnings: list[str] = []
    retry_errors: list[str] = []
    retry_trusted: set[str] = set()
    verify_dir_first: Path | None = None
    last_trusted: dict[str, bool] = {}
    attempts_with_evidence = 0
    clock = hooks.monotonic if hooks.monotonic is not None else time.monotonic
    deadline = None if budget_seconds is None else clock() + budget_seconds

    def _remaining_owners() -> Sequence[str]:
        return tuple(sorted(remaining))

    driver = AttemptDriver(
        hooks=hooks,
        repo_root=repo_root,
        run_id=run_id,
        run_dir=run_dir,
        max_attempts=MAX_CHECK_RECAPTURE_ATTEMPTS,
        workers_for_attempt=lambda _index: 1,
        deadline=deadline,
        clock=clock,
    )
    for attempt_index, attempt, attempt_dir, inventory in driver.run_while(
        _remaining_owners
    ):
        logs[attempt.label] = attempt.log
        attempts.append(attempt)
        if verify_dir_first is None:
            verify_dir_first = attempt_dir
        if inventory is None:
            continue
        blocker = _retry_attempt_blocker(attempt, inventory)
        if blocker is not None:
            # A matching image from a broken retry cannot cure the first
            # pass: its node data is unusable and the breakage itself fails
            # the run. Other nodes may still recover on a later valid
            # attempt.
            retry_errors.append(blocker)
            continue
        attempts_with_evidence += 1
        trusted, _ = derive_node_trust(inventory)
        # A test failure is cured once the node passes on a valid retry,
        # even when its image still drifts: the drift is reported through
        # remaining changes, not as a test failure.
        retry_trusted.update(trusted)
        by_node: dict[str, list[CaptureRecord]] = {}
        for record in inventory.captures:
            by_node.setdefault(record.node_id, []).append(record)
        newly_passed: list[str] = []
        owners = sorted(remaining)
        for node_id in owners:
            last_trusted[node_id] = node_id in trusted
            if node_id not in trusted:
                continue
            records = by_node.get(node_id, [])
            if not records:
                continue
            classified, problems = classify_selected_captures(
                [(record, attempt_dir) for record in records],
                baseline=baseline,
                repo_root=repo_root,
            )
            if problems:
                continue
            if any(item.kind != KIND_UNCHANGED for item in classified):
                continue
            newly_passed.append(node_id)
            path = records[0].canonical_golden_path
            unstable.append(
                SkippedRecord(
                    kind=SKIP_KIND_NODE,
                    node_id=node_id,
                    path=path,
                    reason=REASON_UNSTABLE,
                    detail=(
                        "passed its test and matched its golden on recapture "
                        f"attempt {attempt_index}"
                    ),
                    evidence=(attempt.log,),
                    attempts=attempt_index + 1,
                )
            )
        remaining -= set(newly_passed)
    if driver.budget_exhausted and remaining:
        warnings.append(
            "recapture budget exhausted; remaining nodes keep their first-pass outcome"
        )
    resolved = {record.node_id for record in unstable}
    remaining_changes = tuple(
        item
        for item in first_pass_changes
        if item.node_id not in resolved or item.kind not in {KIND_CREATED, KIND_UPDATED}
    )
    recover = set(first_pass_recover)
    if attempts_with_evidence:
        execution_failed = tuple(
            sorted(
                node_id for node_id in remaining if not last_trusted.get(node_id, False)
            )
        )
    else:
        # No usable retry evidence (budget expired, every retry broken, or
        # no retry ran): remaining nodes keep their first-pass outcome, so
        # only first-pass test failures fail here. Pure drift stays drift.
        execution_failed = tuple(
            sorted(node_id for node_id in remaining if node_id in recover)
        )
    diffs_dir = run_dir / FIRST_ATTEMPT_DIFFS_DIRNAME
    diffs_rel = posix_relative(diffs_dir, repo_root) if diffs_dir.is_dir() else None
    return CheckRecaptureResult(
        remaining_failed=tuple(sorted(remaining)),
        execution_failed=execution_failed,
        unstable=tuple(unstable),
        remaining_changes=remaining_changes,
        attempts=tuple(attempts),
        logs=dict(logs),
        warnings=tuple(warnings),
        verify_dir=verify_dir_first,
        first_attempt_diffs_dir=diffs_rel,
        budget_exhausted=driver.budget_exhausted,
        retry_errors=tuple(retry_errors),
        retry_trusted=tuple(sorted(retry_trusted)),
    )


# Pytest exit codes with an ordinary per-test meaning: success and plain
# test failure. Anything else (interrupt, internal error, usage error, no
# tests collected) is harness breakage that recapture cannot cure.
ORDINARY_EXITSTATUSES = (0, 1)

# Retry-inventory reasons proving the retry harness itself broke, so none
# of its node data may cure the first pass.
_RETRY_HARNESS_PREFIXES = (
    "missing_worker:",
    "incomplete_worker:",
    "lost_worker:",
    "unexpected_worker:",
    "duplicate_canonical_path:",
    "worker_error:",
    "malformed_worker:",
    "invalid_capture:",
    "invalid_scope:",
)


def _retry_attempt_blocker(
    attempt: AttemptRecord, inventory: InventoryReport
) -> str | None:
    """Return why a retry attempt cannot cure the first pass, if any.

    Only ordinary test outcomes from a protocol-clean retry may recover a
    node. Abnormal exits, exit disagreement, collect-only or mismatched
    collection, and capture protocol errors invalidate the whole attempt
    while leaving other nodes free to recover on a later valid attempt.
    """
    label = attempt.label
    child_exit = attempt.child_exit_code
    session_exit = inventory.session_exitstatus
    if child_exit is not None and child_exit not in ORDINARY_EXITSTATUSES:
        return (
            f"retry {label} child exit {child_exit} is not an ordinary "
            "test result; its captures cannot cure the first pass"
        )
    if session_exit not in ORDINARY_EXITSTATUSES:
        return (
            f"retry {label} session exit status {session_exit} is not an "
            "ordinary test result; its captures cannot cure the first pass"
        )
    if child_exit is not None and child_exit != session_exit:
        return (
            f"retry {label} child exit {child_exit} disagrees with session "
            f"exit status {session_exit}; its captures cannot cure the first pass"
        )
    if inventory.collectonly:
        return (
            f"retry {label} only collected tests; its captures cannot cure "
            "the first pass"
        )
    if "collection_mismatch" in inventory.reasons:
        return (
            f"retry {label} workers disagreed about collection; its captures "
            "cannot cure the first pass"
        )
    if inventory.errors:
        names = ", ".join(sorted(set(inventory.errors))[:3])
        return (
            f"retry {label} has capture protocol errors ({names}); its "
            "captures cannot cure the first pass"
        )
    for reason in inventory.reasons:
        if reason.startswith(_RETRY_HARNESS_PREFIXES):
            return (
                f"retry {label} has harness evidence ({reason}); its captures "
                "cannot cure the first pass"
            )
    return None


# Inventory scope marker, never a failure on its own.
_STRICT_BENIGN_REASONS = frozenset({"requested_scope_targeted"})

# Node-failure reasons a trusted exact-matching recapture may cure.
_STRICT_CURABLE_PREFIXES = (
    "failed_node:",
    "error_node:",
    "unaccounted_node:",
)

# Structural root evidence demanded only from full-scope runs. A targeted
# run legitimately covers one root; its missing sibling is not a failure.
_FULL_SCOPE_ROOT_PREFIX = "visual_root_unexecuted:"


def check_mode_strict_errors(
    inventory: InventoryReport,
    *,
    recovered: Sequence[str],
    child_exit_code: int | None = None,
    scope: str = "full",
) -> tuple[str, ...]:
    """Return first-pass failures recapture cannot hide.

    Only ordinary pytest test-failure status (exit 1) and node failure
    reasons actually cured on a valid retry are ignored: a node that passes
    its test on a protocol-clean retry cured its failure, and an exact
    golden match additionally clears its drift. Internal errors,
    interrupts, usage failures, unexplained exit disagreement, protocol
    errors, collect-only or mismatched collection, missing workers,
    skipped nodes, and structural full-scope omissions remain failures.
    Targeted runs are not required to execute both visual roots.
    """
    recovered_nodes = set(recovered)
    errors = list(inventory.errors)
    for reason in inventory.reasons:
        if reason in _STRICT_BENIGN_REASONS:
            continue
        if reason.startswith(_STRICT_CURABLE_PREFIXES):
            node_id = reason.split(":", 1)[1]
            if node_id not in recovered_nodes:
                errors.append(reason)
            continue
        if reason.startswith(_FULL_SCOPE_ROOT_PREFIX) and scope != "full":
            continue
        if reason.startswith("session_exitstatus:"):
            try:
                status = int(reason.split(":", 1)[1])
            except ValueError:
                errors.append(reason)
                continue
            if status in ORDINARY_EXITSTATUSES:
                continue
            errors.append(reason)
            continue
        errors.append(reason)
    if child_exit_code is not None and child_exit_code not in ORDINARY_EXITSTATUSES:
        errors.append(
            f"child_exit_code:{child_exit_code} is not an ordinary test result"
        )
    session_exit = inventory.session_exitstatus
    if child_exit_code is not None and child_exit_code != session_exit:
        errors.append(
            f"exit_disagreement:child={child_exit_code}:session={session_exit}"
        )
    return tuple(errors)


def _diff_slug(value: str) -> str:
    """Return a filesystem-safe directory name for one first-attempt diff."""
    slug = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value
    )
    return slug.strip("-")[:80] or "node"
