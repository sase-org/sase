"""Per-golden determinism agreement over bounded serial re-verification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from tests.ace.tui.visual._png_diff_comparison import diff_pngs
from tests.ace.tui.visual._visual_capture import InventoryReport, load_inventory
from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes
from tests.ace.tui.visual._visual_capture_records import CaptureRecord
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_selected_captures,
)
from tests.ace.tui.visual._visual_maintenance_exec import run_pytest
from tests.ace.tui.visual._visual_maintenance_manifest import posix_relative
from tests.ace.tui.visual._visual_maintenance_trust import derive_node_trust
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_UNCHANGED,
    KIND_UPDATED,
    REASON_OWNER_MISMATCH,
    REASON_UNSTABLE,
    REASON_VERIFY_FAILED,
    SKIP_KIND_GOLDEN,
    SKIP_KIND_NODE,
    AttemptRecord,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceHooks,
    SkippedRecord,
)


MAX_VERIFY_ATTEMPTS = 3
# Two serial recaptures, capped at 25 nodes, so the 45-minute visual-test job
# still has headroom after a typical 24-33 minute first pass.
MAX_CHECK_RECAPTURE_ATTEMPTS = 2
CHECK_RECAPTURE_NODE_LIMIT = 25
FIRST_ATTEMPT_DIFFS_DIRNAME = "first-attempt-diffs"


@dataclass
class VerifyAgreementResult:
    """Outcome of per-golden agreement voting."""

    changes: tuple[ChangeRecord, ...]
    skipped: tuple[SkippedRecord, ...]
    warnings: tuple[str, ...]
    verify_dir: Path | None
    attempts: tuple[AttemptRecord, ...]
    logs: dict[str, str]
    sources: dict[str, tuple[CaptureRecord, Path]]


@dataclass
class _Sample:
    sha256: str
    source_dir: Path
    record: CaptureRecord


@dataclass
class _Golden:
    path: str
    owner: str | None
    initial_record: CaptureRecord
    initial_source: Path
    samples: list[_Sample] = field(default_factory=list)
    decided_hash: str | None = None
    decided_sample: _Sample | None = None


def run_verify_agreement(
    *,
    hooks: MaintenanceHooks,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    baseline: GoldenBaseline,
    ordered: Sequence[tuple[CaptureRecord, Path]],
    changes: Sequence[ChangeRecord],
) -> VerifyAgreementResult:
    """Verify created/updated goldens by per-golden hash agreement."""
    actionable = [item for item in changes if item.kind in {KIND_CREATED, KIND_UPDATED}]
    passthrough = tuple(
        item for item in changes if item.kind not in {KIND_CREATED, KIND_UPDATED}
    )
    if not actionable:
        return VerifyAgreementResult(
            changes=tuple(changes),
            skipped=(),
            warnings=(),
            verify_dir=None,
            attempts=(),
            logs={},
            sources={},
        )
    ordered_by_path = _ordered_by_path(ordered)
    goldens: dict[str, _Golden] = {}
    early_skips: list[SkippedRecord] = []
    for change in actionable:
        init = ordered_by_path.get(change.path)
        if init is None:
            early_skips.append(
                SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=change.node_id,
                    path=change.path,
                    reason=REASON_VERIFY_FAILED,
                    detail=("no trusted capture for verification; left untouched"),
                    attempts=0,
                )
            )
            continue
        record, source = init
        goldens[change.path] = _Golden(
            path=change.path,
            owner=change.node_id,
            initial_record=record,
            initial_source=source,
            samples=[
                _Sample(
                    sha256=record.candidate_sha256,
                    source_dir=source,
                    record=record,
                )
            ],
        )
    attempts: list[AttemptRecord] = []
    logs: dict[str, str] = {}
    warnings: list[str] = []
    skipped: list[SkippedRecord] = list(early_skips)
    skipped_paths: set[str] = {item.path for item in early_skips if item.path}
    mismatch: dict[str, SkippedRecord] = {}
    seen_unexpected: set[str] = set()
    verify_dir_first: Path | None = None
    for attempt_index in range(1, MAX_VERIFY_ATTEMPTS + 1):
        undecided = [
            state
            for state in goldens.values()
            if state.decided_hash is None and state.path not in mismatch
        ]
        if not undecided:
            break
        owners = sorted({state.owner for state in undecided if state.owner})
        if not owners:
            for state in undecided:
                if state.path not in skipped_paths:
                    skipped_paths.add(state.path)
                    skipped.append(
                        SkippedRecord(
                            kind=SKIP_KIND_GOLDEN,
                            node_id=state.owner,
                            path=state.path,
                            reason=REASON_VERIFY_FAILED,
                            detail=("no owner node to re-verify; left untouched"),
                            evidence=tuple(logs[value] for value in sorted(logs)),
                            attempts=len(attempts),
                        )
                    )
            break
        workers = None if attempt_index == 1 else 1
        attempt, attempt_dir, inventory = _run_one_verify_attempt(
            hooks=hooks,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            attempt_index=attempt_index,
            owners=owners,
            workers=workers,
        )
        logs[attempt.label] = attempt.log
        attempts.append(attempt)
        if verify_dir_first is None:
            verify_dir_first = attempt_dir
        if inventory is None:
            continue
        trusted, _ = derive_node_trust(inventory)
        by_path: dict[str, list[CaptureRecord]] = {}
        for record in inventory.captures:
            by_path.setdefault(record.canonical_golden_path, []).append(record)
        for path, records in sorted(by_path.items()):
            if path not in goldens:
                if path not in seen_unexpected:
                    seen_unexpected.add(path)
                    owner = records[0].node_id if records else "unknown"
                    warnings.append(
                        f"verify captured unexpected golden {path} "
                        f"from {owner}; ignoring"
                    )
                continue
        for state in undecided:
            records = by_path.get(state.path, [])
            if not records:
                continue
            if len(records) != 1 or records[0].node_id != state.owner:
                actual = ",".join(sorted({item.node_id for item in records}))
                mismatch[state.path] = SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=state.owner,
                    path=state.path,
                    reason=REASON_OWNER_MISMATCH,
                    detail=(
                        f"verify owner {actual} differs from capture owner "
                        f"{state.owner}; left untouched"
                    ),
                    evidence=(attempt.log,),
                    attempts=len(attempts),
                )
                continue
            record = records[0]
            if record.node_id not in trusted:
                continue
            state.samples.append(
                _Sample(
                    sha256=record.candidate_sha256,
                    source_dir=attempt_dir,
                    record=record,
                )
            )
            counts: dict[str, int] = {}
            for sample in state.samples:
                counts[sample.sha256] = counts.get(sample.sha256, 0) + 1
                if counts[sample.sha256] >= 2:
                    state.decided_hash = sample.sha256
                    state.decided_sample = _deciding_sample(state)
                    break
    skipped.extend(mismatch.values())
    skipped_paths.update(mismatch)
    decided_inputs: list[tuple[CaptureRecord, Path]] = []
    decided_paths: list[str] = []
    for path, state in goldens.items():
        if path in mismatch or state.decided_hash is None:
            continue
        assert state.decided_sample is not None
        decided_inputs.append(
            (state.decided_sample.record, state.decided_sample.source_dir)
        )
        decided_paths.append(path)
    reclassified: dict[str, ChangeRecord] = {}
    if decided_inputs:
        fresh, problems = classify_selected_captures(
            decided_inputs, baseline=baseline, repo_root=repo_root
        )
        reclassified = {item.path: item for item in fresh}
        for problem in problems:
            path, _, detail = problem.partition(":")
            path = path.strip()
            if path in skipped_paths:
                continue
            skipped_paths.add(path)
            prior = goldens.get(path)
            skipped.append(
                SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=prior.owner if prior else None,
                    path=path or None,
                    reason=REASON_VERIFY_FAILED,
                    detail=(
                        "verification candidate could not be classified; "
                        f"left untouched ({detail.strip()})"
                    ),
                    evidence=tuple(logs[key] for key in sorted(logs)),
                    attempts=len(attempts),
                )
            )
    final: list[ChangeRecord] = list(passthrough)
    sources: dict[str, tuple[CaptureRecord, Path]] = {}
    for path in decided_paths:
        item = reclassified.get(path)
        if item is None:
            continue
        final.append(item)
        state = goldens[path]
        assert state.decided_sample is not None
        sources[path] = (
            state.decided_sample.record,
            state.decided_sample.source_dir,
        )
    for path, state in sorted(goldens.items()):
        if path in mismatch or state.decided_hash is not None:
            continue
        if path in skipped_paths:
            continue
        skipped_paths.add(path)
        if len(state.samples) <= 1:
            skipped.append(
                SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=state.owner,
                    path=state.path,
                    reason=REASON_VERIFY_FAILED,
                    detail=(
                        f"owner {state.owner} never produced a trusted "
                        f"verification capture after {len(attempts)} "
                        "attempt(s); left untouched"
                    ),
                    evidence=tuple(logs[key] for key in sorted(logs)),
                    attempts=len(attempts),
                )
            )
        else:
            distinct = sorted({sample.sha256 for sample in state.samples})
            candidates = sorted(
                {
                    posix_relative(
                        sample.source_dir / sample.record.candidate_png_relpath,
                        repo_root,
                    )
                    for sample in state.samples
                }
            )
            evidence = tuple(logs[key] for key in sorted(logs)) + tuple(candidates)
            skipped.append(
                SkippedRecord(
                    kind=SKIP_KIND_GOLDEN,
                    node_id=state.owner,
                    path=state.path,
                    reason=REASON_UNSTABLE,
                    detail=(
                        f"captures disagree after {len(attempts)} verify "
                        f"attempt(s): {len(distinct)} distinct hashes from "
                        f"{len(state.samples)} samples; left untouched"
                    ),
                    evidence=evidence,
                    attempts=len(attempts),
                )
            )
    final_sorted = tuple(
        sorted(final, key=lambda item: (item.kind, item.path, item.node_id or ""))
    )
    return VerifyAgreementResult(
        changes=final_sorted,
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        verify_dir=verify_dir_first,
        attempts=tuple(attempts),
        logs=dict(logs),
        sources=dict(sources),
    )


def _ordered_by_path(
    ordered: Sequence[tuple[CaptureRecord, Path]],
) -> dict[str, tuple[CaptureRecord, Path]]:
    """Map each golden path to its first trusted capture and source dir."""
    mapping: dict[str, tuple[CaptureRecord, Path]] = {}
    for record, source_dir in ordered:
        mapping.setdefault(record.canonical_golden_path, (record, source_dir))
    return mapping


def _deciding_sample(state: _Golden) -> _Sample:
    """Return the verify sample that decided *state*, preferring verify bytes."""
    assert state.decided_hash is not None
    for sample in reversed(state.samples[1:]):
        if sample.sha256 == state.decided_hash:
            return sample
    for sample in reversed(state.samples):
        if sample.sha256 == state.decided_hash:
            return sample
    return state.samples[-1]


def _load_if_present(path: Path) -> InventoryReport | None:
    """Return the inventory at *path*, or None when missing or unreadable."""
    if not path.is_file():
        return None
    try:
        return load_inventory(path)
    except Exception:
        return None


def _run_one_verify_attempt(
    *,
    hooks: MaintenanceHooks,
    repo_root: Path,
    run_id: str,
    run_dir: Path,
    attempt_index: int,
    owners: Sequence[str],
    workers: int | None,
) -> tuple[AttemptRecord, Path, InventoryReport | None]:
    """Run one targeted recapture into a fresh directory.

    Update-mode agreement and check-mode recapture share this pytest pass.
    """
    dir_name = "verify" if attempt_index == 1 else f"verify-{attempt_index}"
    attempt_dir = run_dir / dir_name
    attempt_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{dir_name}.log"
    log_rel = posix_relative(log_path, repo_root)
    attempt_run_id = (
        f"{run_id}-verify" if attempt_index == 1 else f"{run_id}-verify-{attempt_index}"
    )
    child_exit = run_pytest(
        hooks,
        repo_root=repo_root,
        capture_dir=attempt_dir,
        run_id=attempt_run_id,
        scope="targeted",
        pytest_args=tuple(owners),
        log_path=log_path,
        workers=workers,
    )
    attempt = AttemptRecord(
        label=dir_name,
        run_id=attempt_run_id,
        capture_dir=posix_relative(attempt_dir, repo_root),
        log=log_rel,
        workers=workers,
        child_exit_code=child_exit,
    )
    return attempt, attempt_dir, _load_if_present(attempt_dir / "inventory.json")


@dataclass
class CheckRecaptureResult:
    """Outcome of check-mode serial recapture of first-pass failures."""

    remaining_failed: tuple[str, ...]
    unstable: tuple[SkippedRecord, ...]
    remaining_changes: tuple[ChangeRecord, ...]
    attempts: tuple[AttemptRecord, ...]
    logs: dict[str, str]
    warnings: tuple[str, ...]
    verify_dir: Path | None
    first_attempt_diffs_dir: str | None


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
) -> CheckRecaptureResult:
    """Re-run first-pass failures serially until they match goldens or attempts end.

    A node is resolved only when one attempt both trusts the node (test
    passed) and classifies every capture as unchanged (exact golden match).
    Resolved nodes are reported as ``unstable``. Check mode never writes
    goldens.
    """
    remaining = set(failed_nodes)
    unstable: list[SkippedRecord] = []
    attempts: list[AttemptRecord] = []
    logs: dict[str, str] = {}
    warnings: list[str] = []
    verify_dir_first: Path | None = None
    for attempt_index in range(1, MAX_CHECK_RECAPTURE_ATTEMPTS + 1):
        if not remaining:
            break
        owners = sorted(remaining)
        attempt, attempt_dir, inventory = _run_one_verify_attempt(
            hooks=hooks,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            attempt_index=attempt_index,
            owners=owners,
            workers=1,
        )
        logs[attempt.label] = attempt.log
        attempts.append(attempt)
        if verify_dir_first is None:
            verify_dir_first = attempt_dir
        if inventory is None:
            continue
        trusted, _ = derive_node_trust(inventory)
        by_node: dict[str, list[CaptureRecord]] = {}
        for record in inventory.captures:
            by_node.setdefault(record.node_id, []).append(record)
        newly_passed: list[str] = []
        for node_id in owners:
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
    resolved = {record.node_id for record in unstable}
    remaining_changes = tuple(
        item
        for item in first_pass_changes
        if item.node_id not in resolved or item.kind not in {KIND_CREATED, KIND_UPDATED}
    )
    diffs_dir = run_dir / FIRST_ATTEMPT_DIFFS_DIRNAME
    diffs_rel = posix_relative(diffs_dir, repo_root) if diffs_dir.is_dir() else None
    return CheckRecaptureResult(
        remaining_failed=tuple(sorted(remaining)),
        unstable=tuple(unstable),
        remaining_changes=remaining_changes,
        attempts=tuple(attempts),
        logs=dict(logs),
        warnings=tuple(warnings),
        verify_dir=verify_dir_first,
        first_attempt_diffs_dir=diffs_rel,
    )


def _diff_slug(value: str) -> str:
    """Return a filesystem-safe directory name for one first-attempt diff."""
    slug = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value
    )
    return slug.strip("-")[:80] or "node"
