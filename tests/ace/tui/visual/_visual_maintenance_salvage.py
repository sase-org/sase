"""Update-mode orchestration with per-node salvage and partial apply."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
)
from tests.ace.tui.visual._visual_maintenance_apply import apply_changes
from tests.ace.tui.visual._visual_maintenance_baseline import (
    detect_concurrent_edits,
)
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_selected_captures,
    preserve_expected_bytes,
)
from tests.ace.tui.visual._visual_maintenance_exec import (
    run_pytest,
)
from tests.ace.tui.visual._visual_maintenance_manifest import (
    build_manifest,
    failure_manifest,
    posix_relative,
    print_summary,
    publish_manifest_and_report,
    try_publish_failure_manifest,
)
from tests.ace.tui.visual._visual_maintenance_salvage_finalize import (
    _SalvageFinalizeMixin,
)
from tests.ace.tui.visual._visual_maintenance_salvage_recovery import (
    _SalvageRecoveryMixin,
    _has_no_usable_inventory,
    _load_if_present,
)
from tests.ace.tui.visual._visual_maintenance_trust import (
    derive_node_trust,
    filter_concurrent_edits,
    stale_records_for,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    JOURNAL_FILENAME,
    STATUS_APPLIED,
    STATUS_CLEAN,
    STATUS_DRIFT,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_PARTIAL,
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
class _UpdateRun(_SalvageRecoveryMixin, _SalvageFinalizeMixin):
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
