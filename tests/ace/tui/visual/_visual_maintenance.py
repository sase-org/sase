"""Public façade for TUI screenshot maintenance."""

from __future__ import annotations

from tests.ace.tui.visual._visual_maintenance_apply import (
    apply_changes as apply_changes,
    find_unfinished_journals as find_unfinished_journals,
    recover_journal as recover_journal,
    recover_unfinished_journals as recover_unfinished_journals,
)
from tests.ace.tui.visual._visual_maintenance_baseline import (
    capture_golden_baseline as capture_golden_baseline,
    detect_concurrent_edits as detect_concurrent_edits,
    git_index_fingerprint as git_index_fingerprint,
)
from tests.ace.tui.visual._visual_maintenance_cli import (
    build_parser as build_parser,
    parse_command as parse_command,
    resolve_scope as resolve_scope,
    validate_pytest_args as validate_pytest_args,
)
from tests.ace.tui.visual._visual_maintenance_compare import (
    classify_captures as classify_captures,
    classify_selected_captures as classify_selected_captures,
    compare_verification_captures as compare_verification_captures,
)
from tests.ace.tui.visual._visual_maintenance_lock import (
    exclusive_maintenance_lock as exclusive_maintenance_lock,
    new_run_id as new_run_id,
)
from tests.ace.tui.visual._visual_maintenance_run import (
    REPO_ROOT as REPO_ROOT,
    build_run_pytest_command as build_run_pytest_command,
    main as main,
    print_summary as print_summary,
    run_governed_visual_pytest as run_governed_visual_pytest,
    run_maintenance as run_maintenance,
)
from tests.ace.tui.visual._visual_maintenance_salvage import (
    run_update as run_update,
)
from tests.ace.tui.visual._visual_maintenance_trust import (
    derive_node_trust as derive_node_trust,
)
from tests.ace.tui.visual._visual_maintenance_verify import (
    run_verify_agreement as run_verify_agreement,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    EXIT_DRIFT as EXIT_DRIFT,
    EXIT_FAILURE as EXIT_FAILURE,
    EXIT_SUCCESS as EXIT_SUCCESS,
    EXIT_USAGE as EXIT_USAGE,
    MANIFEST_KIND as MANIFEST_KIND,
    MANIFEST_SCHEMA_VERSION as MANIFEST_SCHEMA_VERSION,
    STATUS_PARTIAL as STATUS_PARTIAL,
    AttemptRecord as AttemptRecord,
    ChangeManifest as ChangeManifest,
    ChangeRecord as ChangeRecord,
    GoldenBaseline as GoldenBaseline,
    MaintenanceError as MaintenanceError,
    MaintenanceHooks as MaintenanceHooks,
    MaintenanceRequest as MaintenanceRequest,
    OverlappingRunError as OverlappingRunError,
    SkippedRecord as SkippedRecord,
    UsageError as UsageError,
)


__all__ = [
    "EXIT_DRIFT",
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "MANIFEST_KIND",
    "MANIFEST_SCHEMA_VERSION",
    "REPO_ROOT",
    "STATUS_PARTIAL",
    "AttemptRecord",
    "ChangeManifest",
    "ChangeRecord",
    "GoldenBaseline",
    "MaintenanceError",
    "MaintenanceHooks",
    "MaintenanceRequest",
    "OverlappingRunError",
    "SkippedRecord",
    "UsageError",
    "apply_changes",
    "build_parser",
    "build_run_pytest_command",
    "capture_golden_baseline",
    "classify_captures",
    "classify_selected_captures",
    "compare_verification_captures",
    "derive_node_trust",
    "detect_concurrent_edits",
    "exclusive_maintenance_lock",
    "find_unfinished_journals",
    "git_index_fingerprint",
    "main",
    "new_run_id",
    "parse_command",
    "print_summary",
    "recover_journal",
    "recover_unfinished_journals",
    "resolve_scope",
    "run_governed_visual_pytest",
    "run_maintenance",
    "run_update",
    "run_verify_agreement",
    "validate_pytest_args",
]
