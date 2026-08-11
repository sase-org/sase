"""XPrompt discovery and loading from files and configuration.

This module is the public facade for xprompt discovery: it aggregates
xprompts from every source (filesystem, config, plugins, project workspaces,
and built-ins) and exposes the public ``get_all_*`` API. Per-source loaders
live in :mod:`.loader_sources`.
"""

import functools
import logging
from typing import TYPE_CHECKING

from .loader_skills import (
    get_sase_package_skills_dir,
    load_project_skills,
    load_skills_from_files,
    load_skills_from_package,
    load_skills_from_plugins,
)
from .discovery_order import (
    RANK_PACKAGE_DEFAULT_XPROMPTS,
    RANK_PACKAGE_SKILLS,
    RANK_PACKAGE_XPROMPTS,
    RANK_PLUGIN,
    RANK_PLUGIN_SKILLS,
    merge_by_discovery_order,
)
from .loader_memory import (
    load_memory_xprompts,
    load_project_memory_xprompts,
)
from .loader_sources import (
    load_xprompt_from_file,
    load_xprompts_from_config,
    load_xprompts_from_default_files,
    load_xprompts_from_files,
    load_xprompts_from_internal,
    load_xprompts_from_plugins,
    load_xprompts_from_project,
    namespace_xprompt,
    inactive_project_message_for_ref,
    get_known_project_workspaces,
    get_project_lifecycle_record,
    get_sase_package_default_xprompts_dir,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
    load_project_local_xprompts,
    load_project_file_xprompts,
)
from .models import XPrompt
from .project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


__all__ = [
    "detect_project",
    "get_all_project_local_prompts",
    "get_all_prompts",
    "get_all_workflows",
    "get_all_xprompts",
    "get_known_project_workspaces",
    "get_project_lifecycle_record",
    "inactive_project_message_for_ref",
    "get_sase_package_default_xprompts_dir",
    "get_sase_package_skills_dir",
    "get_sase_package_xprompts_dir",
    "get_xprompt_or_workflow",
    "get_xprompt_search_paths",
    "load_project_local_xprompts",
    "load_project_file_xprompts",
    "load_project_memory_xprompts",
    "load_project_skills",
    "load_memory_xprompts",
    "load_skills_from_files",
    "load_skills_from_package",
    "load_skills_from_plugins",
    "load_xprompt_from_file",
    "load_xprompts_from_config",
    "load_xprompts_from_default_files",
    "load_xprompts_from_files",
    "load_xprompts_from_internal",
    "load_xprompts_from_plugins",
    "load_xprompts_from_project",
    "namespace_xprompt",
]


@functools.cache
def detect_project() -> str | None:
    """Auto-detect the current project name from the workspace.

    Uses the workspace provider plugin system.  The result is cached for
    the lifetime of the process so the hook only runs once.
    """
    try:
        import os

        from sase.workspace_provider import get_workspace_name

        return get_workspace_name(os.getcwd()) or None
    except Exception:
        return None


def get_all_project_local_prompts() -> dict[str, "Workflow"]:
    """Load xprompts from ALL known projects' ``sase.yml`` files.

    Calls :func:`known_project_namespaces` then
    :func:`load_project_local_xprompts` for each.  Returns a unified
    dict of Workflow objects (xprompts converted via
    :func:`xprompt_to_workflow`).
    """
    from sase.xprompt.models import xprompt_to_workflow

    all_workflows: dict[str, Workflow] = {}
    for project_name, ws_dir in known_project_namespaces().items():
        xprompts = {
            **load_project_local_xprompts(ws_dir, project_name),
            **load_project_file_xprompts(ws_dir, project_name),
            **load_project_skills(ws_dir, project_name),
        }
        for name, xp in xprompts.items():
            all_workflows[name] = xprompt_to_workflow(xp)
    return all_workflows


def _load_registered_project_xprompts(
    project: str,
    *,
    detected_project: str | None,
) -> dict[str, XPrompt]:
    """Load one enabled registered project's checkout-backed xprompts.

    The current checkout's filesystem sources already represent the requested
    project when its detected identity matches, so avoid reading the registry
    copy in that case.
    """
    if canonical_xprompt_project(detected_project) == project:
        return {}

    workspace = known_project_namespaces().get(project)
    if workspace is None:
        return {}

    return {
        **load_project_local_xprompts(workspace, project),
        **load_project_file_xprompts(workspace, project),
        **load_project_skills(workspace, project),
    }


def _load_contextual_memory_xprompts(
    project: str | None,
    *,
    detected_project: str | None,
) -> dict[str, XPrompt]:
    """Load memory xprompts for the selected context without project leakage."""
    if project is not None and canonical_xprompt_project(detected_project) != project:
        workspace = known_project_namespaces().get(project)
        if workspace is None:
            return load_memory_xprompts(
                project=project,
                include_discovered_project=False,
            )
        return load_project_memory_xprompts(workspace, project)
    return load_memory_xprompts(project=project)


def get_all_xprompts(
    project: str | None = None,
) -> dict[str, XPrompt]:
    """Get all xprompts from all sources, respecting priority order.

    When *project* is given (or auto-detected via ``detect_project()``),
    xprompts from project-local sources (CWD xprompt directories and the
    local ``sase.yml``) are namespaced with ``{project}/``. When the requested
    project is registered but is not the current checkout, its enabled primary
    workspace is also consulted through the project registry.

    The first-wins order comes from the shared content-layout contract:
    canonical project and home sources precede their legacy fallbacks,
    project-specific home sources precede config sources, the registry-backed
    project copy fills in checkout-local content when CWD is elsewhere, and
    plugin/package resources come last. CWD/project filesystem sources retain
    the highest priority, so an edited alternate checkout overrides the
    registry copy. See ``resolve_xprompt_file_sources`` for the filesystem
    portion.

    Args:
        project: Optional project name.  When ``None``, the project is
            auto-detected via :func:`detect_project`.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    detected_project = detect_project()
    requested_project = project if project is not None else detected_project
    effective_project = canonical_xprompt_project(requested_project)

    # Start with lowest priority and let higher priority override
    all_xprompts: dict[str, XPrompt] = {}

    # 9. Internal xprompts (lowest priority)
    merge_by_discovery_order(
        all_xprompts,
        load_xprompts_from_internal(),
        fallback_rank=RANK_PACKAGE_XPROMPTS,
    )

    # 8. Default markdown xprompts
    merge_by_discovery_order(
        all_xprompts,
        load_xprompts_from_default_files(),
        fallback_rank=RANK_PACKAGE_DEFAULT_XPROMPTS,
    )

    # 7. Plugin xprompts
    merge_by_discovery_order(
        all_xprompts,
        load_xprompts_from_plugins(),
        fallback_rank=RANK_PLUGIN,
    )

    # 6. Config-based xprompts
    config_xprompts = load_xprompts_from_config(project=effective_project)
    merge_by_discovery_order(all_xprompts, config_xprompts)

    # 5. Project-specific xprompts (if project provided)
    if effective_project:
        project_xprompts = load_xprompts_from_project(effective_project)
        merge_by_discovery_order(all_xprompts, project_xprompts)

        registry_xprompts = _load_registered_project_xprompts(
            effective_project,
            detected_project=detected_project,
        )
        merge_by_discovery_order(all_xprompts, registry_xprompts)

    # 1-4. File-based xprompts (highest priority) - already sorted
    file_xprompts = load_xprompts_from_files(project=effective_project)
    merge_by_discovery_order(all_xprompts, file_xprompts)

    memory_xprompts = _load_contextual_memory_xprompts(
        effective_project,
        detected_project=detected_project,
    )
    merge_by_discovery_order(all_xprompts, memory_xprompts)

    # Skills occupy their own ``skill/`` reference namespace, so they can
    # never shadow (or be shadowed by) an ordinary xprompt of the same bare
    # name. Lowest priority first, so canonical directory sources win.
    merge_by_discovery_order(
        all_xprompts,
        load_skills_from_package(),
        fallback_rank=RANK_PACKAGE_SKILLS,
    )
    merge_by_discovery_order(
        all_xprompts,
        load_skills_from_plugins(),
        fallback_rank=RANK_PLUGIN_SKILLS,
    )
    merge_by_discovery_order(
        all_xprompts,
        load_skills_from_files(project=effective_project),
    )

    return all_xprompts


def get_all_workflows(project: str | None = None) -> dict[str, "Workflow"]:
    """Get all workflows from all sources, respecting priority order.

    This is a wrapper around workflow_loader.get_all_workflows() to provide
    a unified interface in the loader module.

    Args:
        project: Optional project name to include project-specific workflows.

    Returns:
        Dictionary mapping workflow name to Workflow object.
    """
    from sase.xprompt.workflow_loader import get_all_workflows as _get_all_workflows

    return _get_all_workflows(project=project)


def get_all_prompts(
    project: str | None = None,
) -> dict[str, "Workflow"]:
    """Get all xprompts and workflows as unified Workflow objects.

    XPrompts are converted to single-step workflows with prompt_part.
    Actual workflows are returned as-is.
    Discovery precedence decides xprompt/workflow name collisions across
    different sources. YAML workflows take precedence only when they come from
    the same effective source rank as a markdown/config xprompt.

    This enables uniform handling - all prompts can be treated as workflows:
    - Simple xprompt #foo → workflow with single prompt_part step
    - Complex workflow #split → workflow with multiple steps

    Args:
        project: Optional project name to include project-specific xprompts.

    Returns:
        Dictionary mapping name to Workflow object.
    """
    from sase.xprompt.models import xprompt_to_workflow

    workflows = get_all_workflows(project=project)
    xprompts = get_all_xprompts(project=project)

    # Convert xprompts to workflows. Discovery rank decides cross-source
    # collisions; YAML workflows win only when the source rank ties.
    converted = {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}
    return _merge_prompt_kinds(converted, workflows)


def _merge_prompt_kinds(
    xprompts: dict[str, "Workflow"],
    workflows: dict[str, "Workflow"],
) -> dict[str, "Workflow"]:
    """Merge converted xprompts and workflows in discovery-precedence order."""
    from .discovery_order import discovery_rank

    entries = []
    for kind_rank, source in enumerate((xprompts, workflows)):
        for index, (name, workflow) in enumerate(source.items()):
            entries.append((discovery_rank(workflow), kind_rank, name, workflow))

    merged: dict[str, Workflow] = {}
    for _, _, name, workflow in sorted(entries, key=lambda item: (item[0], item[1])):
        if name in merged:
            del merged[name]
        merged[name] = workflow
    return merged


def get_xprompt_or_workflow(
    name: str, project: str | None = None
) -> "XPrompt | Workflow | None":
    """Look up an xprompt or workflow by name.

    Checks xprompts first, then workflows. This allows the same #name(args)
    syntax to work for both.

    Args:
        name: The name to look up.
        project: Optional project name to include project-specific xprompts.

    Returns:
        XPrompt or Workflow object if found, None otherwise.
    """
    # Check xprompts first
    xprompts = get_all_xprompts(project=project)
    if name in xprompts:
        return xprompts[name]

    # Check workflows
    workflows = get_all_workflows(project=project)
    if name in workflows:
        return workflows[name]

    return None
