"""Public facade for linked SDD prompt and plan helpers.

The implementation is split by responsibility across the private ``_link_*``
modules. Imports from this module remain supported for callers and tests.
"""

from __future__ import annotations

from pathlib import Path

from sase.sdd._link_files import list_sdd_files, resolve_sdd_root
from sase.sdd._link_models import (
    RepairAction,
    RepairReport,
    Severity,
    SddFile,
    SddIssue,
    SddValidation,
    repair_to_json,
    validation_to_json,
)
from sase.sdd._link_repair import repair_sdd_links
from sase.sdd._link_support import (
    LIST_KINDS,
    PLAN_KINDS,
    expected_link_type,
    infer_counterpart,
    link_reference,
    mixed_link_agrees,
    relpath,
    resolve_legacy_link_path,
    resolve_link_path,
)
from sase.sdd._link_validation import (
    collect_sdd_links,
    validate_sdd_tree as _validate_sdd_tree,
)
from sase.sdd.artifact_links import (
    SddArtifactLink,
    SddArtifactLinkKind,
    SddArtifactLinkType,
    canonical_sdd_artifact_link,
    parse_sdd_artifact_link,
    update_source_aware_artifact_link,
)

# Closed quarantine for historical invalid SDD files only; do not add new files.
LEGACY_INVALID_SDD_ERROR_ALLOWLIST: frozenset[str] = frozenset(
    {
        "plans/202605/prompts/recover_uncommitted_audit_work_1.md",
        "plans/202605/prompts/sase_mobile_mvp_legend.md",
    }
)

# Compatibility aliases for names historically available from this module.
_SddIssue = SddIssue
_SddFile = SddFile
_SddValidation = SddValidation
_RepairAction = RepairAction
_RepairReport = RepairReport
_list_sdd_files = list_sdd_files
_resolve_link_path = resolve_link_path
_mixed_link_agrees = mixed_link_agrees
_link_reference = link_reference
_resolve_legacy_link_path = resolve_legacy_link_path
_infer_counterpart = infer_counterpart
_expected_link_type = expected_link_type
_relpath = relpath


def validate_sdd_tree(
    path: str | None = None, *, strict: bool = False
) -> SddValidation:
    """Validate artifact metadata and bidirectional links under an SDD root."""
    return _validate_sdd_tree(
        path,
        strict=strict,
        legacy_error_allowlist=LEGACY_INVALID_SDD_ERROR_ALLOWLIST,
    )
