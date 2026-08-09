"""Compatibility facade for workflow definition and source loading.

The implementation is split by responsibility:

* :mod:`workflow_loader_steps` resolves reusable ``use:`` step definitions.
* :mod:`workflow_loader_definition` parses one YAML workflow definition.
* :mod:`workflow_loader_sources` discovers and merges source-specific files.

Private helpers remain available here because tests and downstream callers have
historically imported and monkeypatched them from this module.
"""

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.content_layout import discover_project_root, resolve_xprompt_file_sources
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.discovery_order import (
    RANK_FILESYSTEM_BASE,
    RANK_PACKAGE_XPROMPTS,
    RANK_PLUGIN,
    RANK_REGISTERED_PROJECT_BASE,
    merge_by_discovery_order,
    source_rank,
)
from sase.xprompt.loader import (
    detect_project,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.load_issues import record_load_issue
from sase.xprompt.models import UNSET, InputArg, InputType, XPromptValidationError
from sase.xprompt.project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)
from sase.xprompt.tags import parse_tags
from sase.xprompt.workflow_loader_definition import (
    _REMOVED_AGENT_FAMILY_KIND_ERROR,
    load_workflow_from_file as _load_workflow_from_file_impl,
    load_workflow_from_mapping as _load_workflow_from_mapping_impl,
    namespace_workflow as _namespace_workflow_impl,
)
from sase.xprompt.workflow_loader_parse import (
    parse_workflow_step as _parse_workflow_step,
    parse_workflow_inputs,
    validate_workflow_variables,
)
from sase.xprompt.workflow_loader_sources import (
    discover_workflow_files as _discover_workflow_files_impl,
    load_workflows_from_files as _load_workflows_from_files_impl,
    load_workflows_from_internal as _load_workflows_from_internal_impl,
    load_workflows_from_plugins as _load_workflows_from_plugins_impl,
    load_workflows_from_project as _load_workflows_from_project_impl,
    load_workflows_from_project_workspace as _load_project_workspace_impl,
)
from sase.xprompt.workflow_loader_steps import (
    get_step_search_dirs as _get_step_search_dirs_impl,
    load_step_definition as _load_step_definition_impl,
    resolve_step_imports as _resolve_step_imports_impl,
)
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)

from . import workflow_loader_definition as _definition
from . import workflow_loader_sources as _sources
from . import workflow_loader_steps as _steps

log = logging.getLogger(__name__)


def _sync_step_dependencies() -> None:
    """Keep legacy monkeypatch targets on this facade effective."""
    _steps.detect_project = detect_project
    _steps.discover_project_root = discover_project_root
    _steps.get_sase_package_xprompts_dir = get_sase_package_xprompts_dir
    _steps.get_xprompt_search_paths = get_xprompt_search_paths
    _steps.record_load_issue = record_load_issue
    _steps.yaml = yaml
    _steps.log = log
    _steps.get_step_search_dirs = _get_step_search_dirs
    _steps.load_step_definition = _load_step_definition


def _sync_definition_dependencies() -> None:
    """Forward parsing dependencies through the compatibility facade."""
    _definition.parse_xprompt_entries = parse_xprompt_entries
    _definition.record_load_issue = record_load_issue
    _definition.parse_workflow_inputs = parse_workflow_inputs
    _definition.validate_workflow_variables = validate_workflow_variables
    _definition.parse_tags = parse_tags
    _definition._parse_workflow_step = _parse_workflow_step
    _definition.resolve_step_imports = _resolve_step_imports
    _definition.load_workflow_from_mapping = _load_workflow_from_mapping
    _definition.yaml = yaml


def _sync_source_dependencies() -> None:
    """Forward discovery dependencies through the compatibility facade."""
    _sources.resolve_xprompt_file_sources = resolve_xprompt_file_sources
    _sources.discover_plugin_resources = discover_plugin_resources
    _sources.is_plugin_disabled = is_plugin_disabled
    _sources.get_sase_package_xprompts_dir = get_sase_package_xprompts_dir
    _sources.get_xprompt_search_paths = get_xprompt_search_paths
    _sources.canonical_xprompt_project = canonical_xprompt_project
    _sources.known_project_namespaces = known_project_namespaces
    _sources.source_rank = source_rank
    _sources.RANK_FILESYSTEM_BASE = RANK_FILESYSTEM_BASE
    _sources.RANK_PACKAGE_XPROMPTS = RANK_PACKAGE_XPROMPTS
    _sources.RANK_PLUGIN = RANK_PLUGIN
    _sources.RANK_REGISTERED_PROJECT_BASE = RANK_REGISTERED_PROJECT_BASE
    _sources.discover_workflow_files = _discover_workflow_files
    _sources.load_workflow_from_file = _load_workflow_from_file
    _sources.namespace_workflow = _namespace_workflow


def _get_step_search_dirs(
    workflow_source_path: str | None = None,
) -> list[Path]:
    _sync_step_dependencies()
    return _get_step_search_dirs_impl(workflow_source_path)


def _load_step_definition(
    use_ref: str,
    *,
    workflow_source_path: str | None = None,
) -> dict[str, Any] | None:
    _sync_step_dependencies()
    return _load_step_definition_impl(
        use_ref,
        workflow_source_path=workflow_source_path,
    )


def _resolve_step_imports(
    step_data: dict[str, Any],
    *,
    workflow_source_path: str | None = None,
) -> dict[str, Any] | None:
    _sync_step_dependencies()
    return _resolve_step_imports_impl(
        step_data,
        workflow_source_path=workflow_source_path,
    )


def _namespace_workflow(project: str, workflow: Workflow) -> Workflow:
    _sync_definition_dependencies()
    return _namespace_workflow_impl(project, workflow)


def _load_workflow_from_mapping(
    name: str,
    data: dict[str, Any],
    source_path: str,
) -> Workflow | None:
    _sync_definition_dependencies()
    return _load_workflow_from_mapping_impl(name, data, source_path)


def _load_workflow_from_file(file_path: Path) -> Workflow | None:
    _sync_definition_dependencies()
    return _load_workflow_from_file_impl(file_path)


def _discover_workflow_files(
    project: str | None = None,
) -> list[tuple[Path, int, bool]]:
    _sync_source_dependencies()
    return _discover_workflow_files_impl(project)


def _load_workflows_from_files(project: str | None = None) -> dict[str, Workflow]:
    _sync_source_dependencies()
    return _load_workflows_from_files_impl(project)


def _load_workflows_from_internal() -> dict[str, Workflow]:
    _sync_source_dependencies()
    return _load_workflows_from_internal_impl()


def _load_workflows_from_plugins() -> dict[str, Workflow]:
    _sync_source_dependencies()
    return _load_workflows_from_plugins_impl()


def _load_workflows_from_project(project: str) -> dict[str, Workflow]:
    _sync_source_dependencies()
    return _load_workflows_from_project_impl(project)


def _load_workflows_from_project_workspace(
    project: str,
    *,
    detected_project: str | None,
) -> dict[str, Workflow]:
    _sync_source_dependencies()
    return _load_project_workspace_impl(
        project,
        detected_project=detected_project,
    )


def get_all_workflows(project: str | None = None) -> dict[str, Workflow]:
    """Get workflows from every source in shared discovery order."""
    detected_project = detect_project()
    requested_project = project if project is not None else detected_project
    effective_project = canonical_xprompt_project(requested_project)

    all_workflows: dict[str, Workflow] = {}
    merge_by_discovery_order(
        all_workflows,
        _load_workflows_from_internal(),
        fallback_rank=RANK_PACKAGE_XPROMPTS,
    )
    merge_by_discovery_order(
        all_workflows,
        _load_workflows_from_plugins(),
        fallback_rank=RANK_PLUGIN,
    )

    if effective_project:
        merge_by_discovery_order(
            all_workflows,
            _load_workflows_from_project(effective_project),
        )
        merge_by_discovery_order(
            all_workflows,
            _load_workflows_from_project_workspace(
                effective_project,
                detected_project=detected_project,
            ),
        )

    merge_by_discovery_order(
        all_workflows,
        _load_workflows_from_files(project=effective_project),
    )
    return all_workflows
