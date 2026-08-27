"""Compatibility exports for completed-agent loaders.

Completed-agent history intentionally spans all project lifecycle states so
archiving or closing a project does not hide prior agent rows from history
views.
"""

from sase.core.paths import sase_projects_dir

from ..agent import Agent
from . import _done_filesystem_loaders as _filesystem_loaders
from ._done_common import (
    commit_record_key as _commit_record_key,
    commit_results_marker_exists as _commit_results_marker_exists,
    completed_import_transaction as _completed_import_transaction,
    done_extra_files as _done_extra_files,
    enrich_agent_revert_state as _enrich_agent_revert_state,
    enrich_missing_commit_metadata as _enrich_missing_commit_metadata,
    import_transaction_is_visible as _import_transaction_is_visible,
    merge_commit_records as _merge_commit_records,
    single_commit_record_from_metadata as _single_commit_record_from_metadata,
)
from ._done_filesystem_loaders import (
    _DONE_AGENT_WORKFLOW_DIRS,
    _DONE_AGENT_WORKFLOW_PREFIXES,
    iter_artifact_workflow_dirs as _iter_artifact_workflow_dirs,
    load_done_agent_for_dir as _load_done_agent_for_dir,
)
from ._done_snapshot_loaders import (
    build_done_agent_from_record as _build_done_agent_from_record,
    is_done_record as _is_done_record,
    load_done_agents_from_snapshot,
)


def load_done_agents(
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    original_sase_projects_dir = _filesystem_loaders.sase_projects_dir
    _filesystem_loaders.sase_projects_dir = sase_projects_dir
    try:
        return _filesystem_loaders.load_done_agents(bug_by_cl_name, cl_by_cl_name)
    finally:
        _filesystem_loaders.sase_projects_dir = original_sase_projects_dir


__all__ = [
    "_DONE_AGENT_WORKFLOW_DIRS",
    "_DONE_AGENT_WORKFLOW_PREFIXES",
    "_build_done_agent_from_record",
    "_commit_record_key",
    "_commit_results_marker_exists",
    "_completed_import_transaction",
    "_done_extra_files",
    "_enrich_agent_revert_state",
    "_enrich_missing_commit_metadata",
    "_import_transaction_is_visible",
    "_is_done_record",
    "_iter_artifact_workflow_dirs",
    "_load_done_agent_for_dir",
    "_merge_commit_records",
    "_single_commit_record_from_metadata",
    "load_done_agents",
    "load_done_agents_from_snapshot",
]
