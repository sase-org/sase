"""Per-node salvage, recovery retries, and partial apply for update mode."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
    load_inventory,
)
from tests.ace.tui.visual._visual_maintenance_apply import apply_changes
from tests.ace.tui.visual._visual_maintenance_baseline import (
    detect_concurrent_edits,
)
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_selected_captures,
    preserve_expected_bytes,
)
from tests.ace.tui.visual._visual_maintenance_exec import run_pytest
from tests.ace.tui.visual._visual_maintenance_verify import run_verify_agreement
from tests.ace.tui.visual._visual_maintenance_manifest import (
    build_manifest,
    failure_manifest,
    posix_relative,
    print_summary,
    publish_manifest_and_report,
    try_publish_failure_manifest,
)
from tests.ace.tui.visual._visual_maintenance_trust import (
    STALE_LEFT_BEHIND,
    derive_node_trust,
    extract_failed_lines,
    filter_concurrent_edits,
    protocol_error_skip,
    pruning_gate,
    split_protocol_errors,
    stale_records_for,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    JOURNAL_FILENAME,
    KIND_CREATED,
    KIND_UPDATED,
    REASON_TEST_FAILED,
    SKIP_KIND_NODE,
    STATUS_APPLIED,
    STATUS_CLEAN,
    STATUS_DRIFT,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_PARTIAL,
    STATUS_REFUSED,
    AttemptRecord,
    ChangeManifest,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceError,
    MaintenanceHooks,
    MaintenanceRequest,
    SkippedRecord,
    UsageError,
    has_actionable_changes,
)


MAX_RECOVERY_ATTEMPTS = 2
SERIAL_RECOVERY_NODE_LIMIT = 25

RECOVERY_LOG_NAMES = (
    "capture.log",
    "capture-retry.log",
    "recover-1.log",
    "recover-2.log",
)

NO_TESTS_WARNING = "selection matched no visual tests; nothing was checked or updated"


def run_update(
    request: MaintenanceRequest,
    *,
    repo_root: Path,
    hooks: MaintenanceHooks,
    run_id: str,
    run_dir: Path,
    capture_dir: Path,
    baseline: GoldenBaseline,
    renderer: dict[str, Any],
) -> int:
    """Execute one update-mode run with per-node salvage. Return exit code."""
    state = _UpdateRun(
        request=request,
        repo_root=repo_root,
        hooks=hooks,
        run_id=run_id,
        run_dir=run_dir,
        capture_dir=capture_dir,
        baseline=baseline,
        renderer=renderer,
    )
    try:
        return state.execute()
    except UsageError:
        raise
    except KeyboardInterrupt:
        if state.terminal_manifest is not None:
            raise
        manifest = failure_manifest(
            request,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            verify_dir=state.verify_dir,
            baseline=baseline,
            renderer=renderer,
            child_exit_code=state.child_exit,
            logs=state.logs,
            status=STATUS_INTERRUPTED,
            errors=("interrupted",),
            attempts=tuple(state.attempts),
        )
        try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise
    except MaintenanceError as error:
        if state.terminal_manifest is not None:
            raise
        manifest = failure_manifest(
            request,
            repo_root=repo_root,
            run_id=run_id,
            run_dir=run_dir,
            capture_dir=capture_dir,
            verify_dir=state.verify_dir,
            baseline=baseline,
            renderer=renderer,
            child_exit_code=state.child_exit,
            logs=state.logs,
            status=STATUS_FAILED,
            errors=(str(error),),
            warnings=tuple(state.warnings),
            skipped=tuple(state.skipped),
            attempts=tuple(state.attempts),
        )
        try_publish_failure_manifest(repo_root, run_dir, manifest)
        print_summary(manifest)
        raise


@dataclass
class _UpdateRun:
    """Mutable state for one salvaging update-mode run."""

    request: MaintenanceRequest
    repo_root: Path
    hooks: MaintenanceHooks
    run_id: str
    run_dir: Path
    capture_dir: Path
    baseline: GoldenBaseline
    renderer: dict[str, Any]
    logs: dict[str, str] = field(default_factory=dict)
    attempts: list[AttemptRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[SkippedRecord] = field(default_factory=list)
    child_exit: int | None = None
    verify_dir: Path | None = None
    prune_allowed: bool = False
    pruning_skipped_reason: str | None = None
    terminal_manifest: ChangeManifest | None = None
    dropped_paths: set[str] = field(default_factory=set)
    protocol_errors: list[str] = field(default_factory=list)
    verify_sources: dict[str, tuple[CaptureRecord, Path]] = field(default_factory=dict)

    def execute(self) -> int:
        """Run capture, recovery, classification, verification, and apply."""
        self.logs["capture"] = posix_relative(
            self.run_dir / "capture.log", self.repo_root
        )
        self.child_exit = run_pytest(
            self.hooks,
            repo_root=self.repo_root,
            capture_dir=self.capture_dir,
            run_id=self.run_id,
            scope=self.request.scope,
            pytest_args=self.request.pytest_args,
            log_path=self.run_dir / "capture.log",
            workers=self.request.workers,
        )
        self._note_attempt(
            "capture", self.run_id, self.capture_dir, "capture", self.request.workers
        )
        inventory = _load_if_present(self.capture_dir / "inventory.json")
        if _has_no_usable_inventory(inventory):
            if self.child_exit == 5:
                return self._finish_empty_selection()
            if self.child_exit == 4:
                self._refuse_pytest_usage()
            inventory = self._retry_capture()
        assert inventory is not None
        trusted, recover = derive_node_trust(inventory)
        if (self.child_exit != 0 or inventory.session_exitstatus != 0) and not recover:
            self.warnings.append(
                f"pytest exited {self.child_exit} although no visual test "
                f"failed (often the temp-leak guard); see {self.logs['capture']}"
            )
        recovered = self._recover_nodes(recover)
        trusted = trusted | frozenset(recovered)
        for node_id in sorted(set(recover) - set(recovered)):
            self.skipped.append(self._node_skip(node_id))
        ordered = self._ordered_candidates(inventory, recovered)
        changes, problems = classify_selected_captures(
            ordered, baseline=self.baseline, repo_root=self.repo_root
        )
        self._handle_protocol_problems(inventory, changes, problems)
        candidates: list[ChangeRecord] = [
            change for change in changes if change.path not in self.dropped_paths
        ]
        if self._prune_allowed(inventory, trusted, ordered):
            candidates = sorted(
                candidates
                + list(
                    stale_records_for(
                        [record for record, _ in ordered],
                        baseline=self.baseline,
                        repo_root=self.repo_root,
                    )
                ),
                key=lambda item: (item.kind, item.path, item.node_id or ""),
            )
        preserve_expected_bytes(self.run_dir, candidates, self.repo_root)
        kept, edit_skips = filter_concurrent_edits(
            candidates, detect_concurrent_edits(self.baseline, self.repo_root)
        )
        self.skipped.extend(edit_skips)
        if edit_skips:
            self.warnings.append(
                f"{len(edit_skips)} golden(s) changed on disk during the run "
                "and were left untouched"
            )
        changes_tuple = tuple(kept)
        final_changes = self._verify(changes_tuple, ordered)
        partial = bool(self.skipped) or (
            self.request.scope == "full" and self.pruning_skipped_reason is not None
        )
        status = STATUS_PARTIAL if partial else STATUS_CLEAN
        if has_actionable_changes(final_changes):
            status = STATUS_PARTIAL if partial else STATUS_APPLIED
            self._apply(final_changes, inventory, ordered)
            journal_relpath: str | None = str(
                (self.run_dir / JOURNAL_FILENAME).relative_to(self.repo_root)
            )
        else:
            journal_relpath = None
        manifest = self._manifest(
            final_changes,
            inventory,
            status=status,
            exit_code=EXIT_SUCCESS,
            errors=inventory.errors,
            journal_relpath=journal_relpath,
        )
        publish_manifest_and_report(self.repo_root, self.run_dir, manifest)
        print_summary(manifest)
        return EXIT_SUCCESS

    def _manifest(
        self,
        changes: Sequence[ChangeRecord],
        inventory: InventoryReport,
        *,
        status: str,
        exit_code: int,
        errors: Sequence[str],
        journal_relpath: str | None,
    ) -> ChangeManifest:
        return build_manifest(
            self.request,
            repo_root=self.repo_root,
            run_id=self.run_id,
            run_dir=self.run_dir,
            capture_dir=self.capture_dir,
            verify_dir=self.verify_dir,
            baseline=self.baseline,
            renderer=self.renderer,
            changes=changes,
            status=status,
            exit_code=exit_code,
            child_exit_code=self.child_exit,
            inventory_reasons=inventory.reasons,
            errors=errors,
            logs=self.logs,
            journal_relpath=journal_relpath,
            extra={
                "full_inventory": inventory.full_inventory,
                "pruning_allowed": self.prune_allowed,
                "complete": inventory.complete,
            },
            warnings=tuple(self.warnings),
            skipped=tuple(self.skipped),
            attempts=tuple(self.attempts),
            pruning_skipped_reason=self.pruning_skipped_reason,
        )

    def _note_attempt(
        self,
        label: str,
        attempt_run_id: str,
        attempt_dir: Path,
        log_key: str,
        workers: int | None,
    ) -> None:
        self.attempts.append(
            AttemptRecord(
                label=label,
                run_id=attempt_run_id,
                capture_dir=posix_relative(attempt_dir, self.repo_root),
                log=self.logs[log_key],
                workers=workers,
                child_exit_code=self.child_exit,
            )
        )

    def _finish_empty_selection(self) -> int:
        selectors = " ".join(self.request.pytest_args) or self.request.scope
        manifest = build_manifest(
            self.request,
            repo_root=self.repo_root,
            run_id=self.run_id,
            run_dir=self.run_dir,
            capture_dir=self.capture_dir,
            verify_dir=None,
            baseline=self.baseline,
            renderer=self.renderer,
            changes=(),
            status=STATUS_CLEAN,
            exit_code=EXIT_SUCCESS,
            child_exit_code=self.child_exit,
            inventory_reasons=(),
            errors=(),
            logs=self.logs,
            journal_relpath=None,
            extra={
                "full_inventory": False,
                "pruning_allowed": False,
                "complete": False,
            },
            warnings=(f"{NO_TESTS_WARNING} (selectors: {selectors})",),
            skipped=(),
            attempts=tuple(self.attempts),
            pruning_skipped_reason=None,
        )
        publish_manifest_and_report(self.repo_root, self.run_dir, manifest)
        print_summary(manifest)
        return EXIT_SUCCESS

    def _refuse_pytest_usage(self) -> None:
        manifest = failure_manifest(
            self.request,
            repo_root=self.repo_root,
            run_id=self.run_id,
            run_dir=self.run_dir,
            capture_dir=self.capture_dir,
            verify_dir=None,
            baseline=self.baseline,
            renderer=self.renderer,
            child_exit_code=self.child_exit,
            logs=self.logs,
            status=STATUS_REFUSED,
            errors=(
                "pytest reported a usage error (child exit 4); "
                f"see {self.logs['capture']}",
            ),
            attempts=tuple(self.attempts),
        )
        try_publish_failure_manifest(self.repo_root, self.run_dir, manifest)
        print_summary(manifest)
        raise UsageError(
            f"pytest reported a usage error (child exit 4); see {self.logs['capture']}"
        )

    def _retry_capture(self) -> InventoryReport:
        retry_dir = self.run_dir / "capture-retry"
        retry_dir.mkdir(parents=True, exist_ok=True)
        retry_log = self.run_dir / "capture-retry.log"
        self.logs["capture-retry"] = posix_relative(retry_log, self.repo_root)
        self.child_exit = run_pytest(
            self.hooks,
            repo_root=self.repo_root,
            capture_dir=retry_dir,
            run_id=f"{self.run_id}-retry",
            scope=self.request.scope,
            pytest_args=self.request.pytest_args,
            log_path=retry_log,
            workers=self.request.workers,
        )
        self._note_attempt(
            "capture-retry",
            f"{self.run_id}-retry",
            retry_dir,
            "capture-retry",
            self.request.workers,
        )
        retry_inventory = _load_if_present(retry_dir / "inventory.json")
        if _has_no_usable_inventory(retry_inventory):
            raise MaintenanceError(
                "no usable capture inventory after retrying the capture pass; "
                f"see {self.logs['capture']} and {self.logs['capture-retry']} "
                f"(child_exit_code={self.child_exit})"
            )
        assert retry_inventory is not None
        return retry_inventory

    def _recover_nodes(
        self,
        recover: Sequence[str],
    ) -> dict[str, tuple[tuple[CaptureRecord, ...], Path]]:
        """Rerun recover-set nodes and return newly trusted candidates."""
        recovered: dict[str, tuple[tuple[CaptureRecord, ...], Path]] = {}
        remaining = list(recover)
        for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
            if not remaining:
                break
            recover_dir = self.run_dir / f"recover-{attempt}"
            recover_dir.mkdir(parents=True, exist_ok=True)
            recover_log = self.run_dir / f"recover-{attempt}.log"
            log_key = f"recover-{attempt}"
            self.logs[log_key] = posix_relative(recover_log, self.repo_root)
            workers = (
                1
                if len(remaining) <= SERIAL_RECOVERY_NODE_LIMIT
                else self.request.workers
            )
            recover_run_id = f"{self.run_id}-recover-{attempt}"
            self.child_exit = run_pytest(
                self.hooks,
                repo_root=self.repo_root,
                capture_dir=recover_dir,
                run_id=recover_run_id,
                scope="targeted",
                pytest_args=tuple(remaining),
                log_path=recover_log,
                workers=workers,
            )
            self._note_attempt(log_key, recover_run_id, recover_dir, log_key, workers)
            inventory = _load_if_present(recover_dir / "inventory.json")
            if inventory is None:
                continue
            trusted, _ = derive_node_trust(inventory)
            for node_id in remaining:
                if node_id in trusted:
                    recovered[node_id] = (
                        tuple(
                            record
                            for record in inventory.captures
                            if record.node_id == node_id
                        ),
                        recover_dir,
                    )
            remaining = [node_id for node_id in remaining if node_id not in trusted]
        return recovered

    def _ordered_candidates(
        self,
        inventory: InventoryReport,
        recovered: Mapping[str, tuple[tuple[CaptureRecord, ...], Path]],
    ) -> list[tuple[CaptureRecord, Path]]:
        trusted, _ = derive_node_trust(inventory)
        by_node: dict[str, list[tuple[CaptureRecord, Path]]] = {}
        for record in inventory.captures:
            if record.node_id in recovered or record.node_id not in trusted:
                continue
            by_node.setdefault(record.node_id, []).append((record, self.capture_dir))
        for node_id, (records, source_dir) in recovered.items():
            by_node[node_id] = [(item, source_dir) for item in records]
        return [pair for node_id in sorted(by_node) for pair in by_node[node_id]]

    def _node_skip(self, node_id: str) -> SkippedRecord:
        evidence = sorted({record.log for record in self.attempts if record.log})
        failed_lines = _failed_lines_for_node(node_id, self.run_dir)
        detail = (
            "test failed or was lost and never recovered "
            f"after {len(self.attempts)} attempt(s); "
            "existing goldens left untouched"
        )
        if failed_lines:
            detail += f" ({'; '.join(failed_lines)})"
        return SkippedRecord(
            kind=SKIP_KIND_NODE,
            node_id=node_id,
            path=None,
            reason=REASON_TEST_FAILED,
            detail=detail,
            evidence=tuple(evidence),
            attempts=len(self.attempts),
        )

    def _handle_protocol_problems(
        self,
        inventory: InventoryReport,
        changes: Sequence[ChangeRecord],
        problems: Sequence[str],
    ) -> None:
        attributable, unattributable = split_protocol_errors(inventory.errors)
        recovery_errors: list[str] = []
        for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
            recovery = _load_if_present(
                self.run_dir / f"recover-{attempt}" / "inventory.json"
            )
            if recovery is None or not recovery.errors:
                continue
            recovery_errors.extend(recovery.errors)
            extra_attr, extra_unattr = split_protocol_errors(recovery.errors)
            for error_path, error_details in extra_attr.items():
                attributable.setdefault(error_path, []).extend(error_details)
            unattributable.extend(extra_unattr)
        self.dropped_paths = set(attributable)
        for path in sorted(attributable):
            details = "; ".join(attributable[path])
            self.skipped.append(
                protocol_error_skip(
                    path,
                    f"capture protocol error; left untouched ({details})",
                    evidence=_evidence_for_path(changes, path),
                )
            )
        for problem in problems:
            path, _, detail = problem.partition(":")
            self.skipped.append(
                protocol_error_skip(
                    path.strip() or None,
                    "candidate could not be classified; left untouched "
                    f"({detail.strip()})",
                )
            )
        if unattributable:
            self.warnings.append(
                "capture protocol errors cannot be attributed to one golden "
                f"({'; '.join(sorted(set(unattributable))[:3])}); "
                f"{STALE_LEFT_BEHIND}"
            )
        self.protocol_errors = list(inventory.errors) + recovery_errors

    def _prune_allowed(
        self,
        inventory: InventoryReport,
        trusted: frozenset[str],
        ordered: Sequence[tuple[CaptureRecord, Path]],
    ) -> bool:
        allowed, reason = pruning_gate(
            requested_scope=self.request.scope,
            inventory=inventory,
            trusted=trusted,
            protocol_errors=self.protocol_errors,
            trusted_records=[record for record, _ in ordered],
            baseline=self.baseline,
        )
        self.prune_allowed = allowed
        if not allowed and self.request.scope == "full":
            self.pruning_skipped_reason = reason
            self.warnings.append(reason or STALE_LEFT_BEHIND)
        return allowed

    def _verify(
        self,
        changes: Sequence[ChangeRecord],
        ordered: Sequence[tuple[CaptureRecord, Path]],
    ) -> tuple[ChangeRecord, ...]:
        if not any(item.kind in {KIND_CREATED, KIND_UPDATED} for item in changes):
            return tuple(changes)
        result = run_verify_agreement(
            hooks=self.hooks,
            repo_root=self.repo_root,
            run_id=self.run_id,
            run_dir=self.run_dir,
            baseline=self.baseline,
            ordered=ordered,
            changes=changes,
        )
        self.verify_dir = result.verify_dir
        self.logs.update(result.logs)
        self.attempts.extend(result.attempts)
        self.skipped.extend(result.skipped)
        self.warnings.extend(result.warnings)
        self.verify_sources = dict(result.sources)
        return result.changes

    def _apply(
        self,
        changes: Sequence[ChangeRecord],
        inventory: InventoryReport,
        ordered: Sequence[tuple[CaptureRecord, Path]],
    ) -> None:
        preapply_manifest = self._manifest(
            changes,
            inventory,
            status=STATUS_DRIFT,
            exit_code=EXIT_SUCCESS,
            errors=inventory.errors,
            journal_relpath=None,
        )
        publish_manifest_and_report(self.repo_root, self.run_dir, preapply_manifest)
        try:
            apply_changes(
                self.run_dir,
                changes,
                repo_root=self.repo_root,
                capture_dir=self._apply_capture_dir(ordered),
                run_id=self.run_id,
            )
        except KeyboardInterrupt:
            self.terminal_manifest = self._manifest(
                changes,
                inventory,
                status=STATUS_INTERRUPTED,
                exit_code=EXIT_FAILURE,
                errors=("interrupted during apply",),
                journal_relpath=None,
            )
            publish_manifest_and_report(
                self.repo_root, self.run_dir, self.terminal_manifest
            )
            print_summary(self.terminal_manifest)
            raise
        except MaintenanceError as error:
            self.terminal_manifest = self._manifest(
                changes,
                inventory,
                status=STATUS_FAILED,
                exit_code=EXIT_FAILURE,
                errors=(str(error),),
                journal_relpath=None,
            )
            publish_manifest_and_report(
                self.repo_root, self.run_dir, self.terminal_manifest
            )
            print_summary(self.terminal_manifest)
            raise

    def _apply_capture_dir(
        self,
        ordered: Sequence[tuple[CaptureRecord, Path]],
    ) -> Path:
        from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes

        needed: list[tuple[CaptureRecord, Path]] = list(self.verify_sources.values())
        needed.extend(ordered)
        if not needed:
            return self.capture_dir
        if all(source_dir == self.capture_dir for _, source_dir in needed):
            return self.capture_dir
        merged = self.capture_dir / "merged"
        merged.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for record, source_dir in needed:
            for relpath in (
                record.candidate_png_relpath,
                record.candidate_svg_relpath,
            ):
                if not relpath or relpath in seen:
                    continue
                source = source_dir / relpath
                if source.is_file():
                    atomic_write_bytes(merged / relpath, source.read_bytes())
                    seen.add(relpath)
        return merged


def _load_if_present(path: Path) -> InventoryReport | None:
    if not path.is_file():
        return None
    return load_inventory(path)


def _has_no_usable_inventory(inventory: InventoryReport | None) -> bool:
    if inventory is None:
        return True
    return not inventory.executed_visual_node_ids and not inventory.captures


def _failed_lines_for_node(node_id: str, run_dir: Path) -> tuple[str, ...]:
    for log_name in RECOVERY_LOG_NAMES:
        matching = [
            line for line in extract_failed_lines(run_dir / log_name) if node_id in line
        ]
        if matching:
            return tuple(matching[:2])
    for log_name in RECOVERY_LOG_NAMES:
        lines = extract_failed_lines(run_dir / log_name)
        if lines:
            return tuple(lines[:1])
    return ()


def _evidence_for_path(
    changes: Sequence[ChangeRecord],
    path: str,
) -> tuple[str, ...]:
    for change in changes:
        if change.path == path and change.candidate_png_relpath:
            return (change.candidate_png_relpath,)
    return ()
