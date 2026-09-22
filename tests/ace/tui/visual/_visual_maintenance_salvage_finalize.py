"""Protocol errors, pruning gate, and verification for update mode."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from tests.ace.tui.visual._visual_capture import (
    CaptureRecord,
    InventoryReport,
)
from tests.ace.tui.visual._visual_maintenance_verify import (
    run_verify_agreement,
)
from tests.ace.tui.visual._visual_maintenance_salvage_recovery import (
    MAX_RECOVERY_ATTEMPTS,
    _load_if_present,
)
from tests.ace.tui.visual._visual_maintenance_trust import (
    STALE_LEFT_BEHIND,
    pruning_gate,
    protocol_error_skip,
    split_protocol_errors,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_UPDATED,
    ChangeRecord,
)

if TYPE_CHECKING:
    from tests.ace.tui.visual._visual_maintenance_salvage import _UpdateRun


class _SalvageFinalizeMixin:
    """Pre-apply safety checks for an update-mode run."""

    def _handle_protocol_problems(
        self: _UpdateRun,
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
        self: _UpdateRun,
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
        self: _UpdateRun,
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


def _evidence_for_path(
    changes: Sequence[ChangeRecord],
    path: str,
) -> tuple[str, ...]:
    for change in changes:
        if change.path == path and change.candidate_png_relpath:
            return (change.candidate_png_relpath,)
    return ()
