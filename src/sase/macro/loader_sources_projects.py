"""Registered-project macro loaders (home entries, workspaces, locals)."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

from sase.content_layout import (
    resolve_project_config_read_path,
    resolve_macro_file_sources,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
)

from ._loader_sources_common import (
    load_ordinary_macros_from_dir,
    namespace_macro,
)
from .discovery_order import (
    RANK_FILESYSTEM_BASE,
    RANK_PROJECT_CONFIG,
    RANK_REGISTERED_PROJECT_BASE,
    assign_discovery_rank,
    source_rank,
)
from .load_issues import record_load_issue
from .loader_parsing import parse_macro_entries
from .models import Macro

if TYPE_CHECKING:
    from sase.macro.workflow_models import Workflow

log = logging.getLogger(__name__)


def load_macros_from_project(project: str) -> dict[str, Macro]:
    """Load macros from a project-specific directory.

    Loads macros from canonical ``~/sase/macros/{project}/`` and the
    legacy config-directory fallback, then namespaces them with the project
    name (e.g., bar.md → foo/bar for project 'foo').

    Args:
        project: The project name to load macros for.

    Returns:
        Dictionary mapping namespaced macro name to Macro object.
        Returns empty dict if directory doesn't exist.
    """
    macros: dict[str, Macro] = {}
    project_dirs = [
        source.path
        for source in resolve_macro_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    ]
    rank_by_path = {
        project_dir: source_rank(RANK_FILESYSTEM_BASE, index, len(project_dirs))
        for index, project_dir in enumerate(project_dirs)
    }
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for macro_def in load_ordinary_macros_from_dir(project_dir):
            ns = namespace_macro(project, macro_def)
            ns.discovery_rank = rank_by_path[project_dir]
            if ns.name in macros:
                del macros[ns.name]
            macros[ns.name] = ns

    return macros


def _project_ref_candidates(ref: str) -> tuple[str, ...]:
    candidates = [ref]
    if "/" in ref:
        candidates.append(ref.rsplit("/", 1)[-1])
    return tuple(dict.fromkeys(candidates))


def get_project_lifecycle_record(project: str) -> ProjectRecordWire | None:
    """Return the lifecycle record for *project*, including hidden projects."""
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return None
    for record in list_project_records(projects_dir, "all", include_home=False):
        if record.project_name == project:
            return record
    return None


def inactive_project_message_for_ref(ref: str) -> str | None:
    """Return a launch-blocking message when *ref* points at a disabled project."""
    for candidate in _project_ref_candidates(ref):
        record = get_project_lifecycle_record(candidate)
        if record is None or not is_disabled_project_lifecycle_state(record.state):
            continue
        return (
            f"project '{record.project_name}' is {record.state}; run "
            f"'sase project enable {record.project_name}' before launching work"
        )
    return None


def get_known_project_workspaces(
    include_states: Sequence[str] | str = ("enabled",),
) -> dict[str, Path]:
    """Enumerate lifecycle-selected projects and their primary workspaces.

    Normal callers get enabled projects only. Management/history callers can
    pass ``"all"`` or a concrete state list when hidden projects are
    intentionally in scope.

    Returns:
        Mapping of project name to workspace directory path.
    """
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return {}

    result: dict[str, Path] = {}
    for record in list_project_records(
        projects_dir,
        include_states,
        include_home=False,
    ):
        if not record.workspace_dir:
            continue
        ws_path = Path(record.workspace_dir).expanduser()
        if ws_path.is_dir():
            result[record.project_name] = ws_path

    return result


def load_project_local_macros(workspace_dir: Path, project: str) -> dict[str, Macro]:
    """Load macros from a project's ``sase.yml`` file.

    Reads ``<workspace_dir>/sase.yml`` directly, bypassing the
    ``_include_local_config`` flag.  Returns macros namespaced with
    ``{project}/``.
    """
    sase_yml = resolve_project_config_read_path(
        workspace_dir,
        label=f"project config for {project}",
    )
    if sase_yml is None:
        return {}

    try:
        with open(sase_yml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        log.debug("Failed to load project sase.yml: %s", sase_yml, exc_info=True)
        record_load_issue(sase_yml, exc, kind="config")
        return {}

    if not isinstance(data, dict):
        return {}

    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros
    from sase.macro.local_trust import partition_config_macros

    try:
        from sase.config.local_trust_enforcement import effective_local_layer

        effective, _evaluation = effective_local_layer(sase_yml, data)
    except Exception:
        log.debug(
            "Local-command trust filtering failed closed for project macros in %s",
            sase_yml,
            exc_info=True,
        )
        effective = {}

    source_label = f"project_local_config:{project}"
    macros_data: dict[str, Any] = normalize_frontmatter_macros(
        effective, source=source_label
    )
    if not macros_data:
        return {}

    prompt_only, _executable = partition_config_macros(
        macros_data,
        source=source_label,
    )
    parsed = parse_macro_entries(prompt_only, source_label)
    namespaced = {
        f"{project}/{name}": namespace_macro(project, xp) for name, xp in parsed.items()
    }
    return assign_discovery_rank(namespaced, RANK_PROJECT_CONFIG)


def load_project_local_workflows(
    workspace_dir: Path, project: str
) -> dict[str, "Workflow"]:
    """Load executable config macros from a project's ``sase.yml``.

    Reads the selected project config directly, applies the shared trust
    filter, and returns namespaced workflows for command-bearing entries.
    Prompt-only macros stay in :func:`load_project_local_macros`.
    """
    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros
    from sase.macro.local_trust import (
        attach_local_trust,
        partition_config_macros,
        workflow_mapping_from_macro_entry,
    )
    from sase.macro.workflow_loader_definition import (
        load_workflow_from_mapping,
        namespace_workflow,
    )
    from sase.macro.workflow_models import Workflow

    sase_yml = resolve_project_config_read_path(
        workspace_dir,
        label=f"project config for {project}",
    )
    if sase_yml is None:
        return {}

    try:
        with open(sase_yml, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except Exception as exc:
        log.debug("Failed to load project sase.yml: %s", sase_yml, exc_info=True)
        record_load_issue(sase_yml, exc, kind="config")
        return {}

    if not isinstance(data, dict):
        return {}

    try:
        from sase.config.local_trust_enforcement import evaluate_local_trust_for_path

        evaluation = evaluate_local_trust_for_path(sase_yml, data)
        effective = evaluation.effective_layer
    except Exception:
        log.debug(
            "Local-command trust filtering failed closed for project workflows in %s",
            sase_yml,
            exc_info=True,
        )
        return {}

    source_label = f"project_local_config:{project}"
    macros_data = normalize_frontmatter_macros(effective, source=source_label)
    if not macros_data:
        return {}

    _prompt_only, executable = partition_config_macros(
        macros_data,
        source=source_label,
    )
    workflows: dict[str, Workflow] = {}
    for name, value in executable.items():
        mapping = workflow_mapping_from_macro_entry(value)
        if mapping is None:
            continue
        workflow = load_workflow_from_mapping(name, mapping, source_label)
        if workflow is None:
            continue
        namespaced = namespace_workflow(project, workflow)
        attach_local_trust(namespaced, evaluation)
        workflows[namespaced.name] = namespaced
    return assign_discovery_rank(workflows, RANK_PROJECT_CONFIG)


def load_project_file_macros(
    workspace_dir: Path,
    project: str,
) -> dict[str, Macro]:
    """Load namespaced Markdown macros from one known project workspace."""
    project_dirs = [
        source.path
        for source in resolve_macro_file_sources(
            project_root=workspace_dir,
            project=project,
        )
        if source.path is not None and source.scope == "project"
    ]
    rank_by_path = {
        project_dir: source_rank(RANK_REGISTERED_PROJECT_BASE, index, len(project_dirs))
        for index, project_dir in enumerate(project_dirs)
    }
    macros: dict[str, Macro] = {}
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for macro_def in load_ordinary_macros_from_dir(project_dir):
            namespaced = namespace_macro(project, macro_def)
            namespaced.discovery_rank = rank_by_path[project_dir]
            if namespaced.name in macros:
                del macros[namespaced.name]
            macros[namespaced.name] = namespaced
    return macros
