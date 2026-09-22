"""Capture retries and per-node recovery for update mode."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
    load_inventory,
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
from tests.ace.tui.visual._visual_maintenance_trust import (
    derive_node_trust,
    extract_failed_lines,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_SUCCESS,
    REASON_TEST_FAILED,
    SKIP_KIND_NODE,
    STATUS_CLEAN,
    STATUS_REFUSED,
    MaintenanceError,
    SkippedRecord,
    UsageError,
)

if TYPE_CHECKING:
    from tests.ace.tui.visual._visual_maintenance_salvage import _UpdateRun


MAX_RECOVERY_ATTEMPTS = 2
SERIAL_RECOVERY_NODE_LIMIT = 25

RECOVERY_LOG_NAMES = (
    "capture.log",
    "capture-retry.log",
    "recover-1.log",
    "recover-2.log",
)

NO_TESTS_WARNING = "selection matched no visual tests; nothing was checked or updated"


class _SalvageRecoveryMixin:
    """Capture-retry and node-recovery steps for an update-mode run."""

    def _finish_empty_selection(self: _UpdateRun) -> int:
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

    def _refuse_pytest_usage(self: _UpdateRun) -> None:
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

    def _retry_capture(self: _UpdateRun) -> InventoryReport:
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
        self: _UpdateRun,
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
        self: _UpdateRun,
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

    def _node_skip(self: _UpdateRun, node_id: str) -> SkippedRecord:
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
