"""XPrompt discovery and loading from files and configuration.

This module is the public facade for xprompt discovery: it aggregates
xprompts from every source (filesystem, config, plugins, project workspaces,
and built-ins) and exposes the public ``get_all_*`` API. Per-source loaders
live in :mod:`.loader_sources`.
"""

import functools
import logging
from typing import TYPE_CHECKING

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
    "get_sase_package_xprompts_dir",
    "get_xprompt_or_workflow",
    "get_xprompt_search_paths",
    "load_project_local_xprompts",
    "load_project_file_xprompts",
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

    Calls :func:`get_known_project_workspaces` then
    :func:`load_project_local_xprompts` for each.  Returns a unified
    dict of Workflow objects (xprompts converted via
    :func:`xprompt_to_workflow`).
    """
    from sase.xprompt.models import xprompt_to_workflow

    all_workflows: dict[str, Workflow] = {}
    for project_name, ws_dir in get_known_project_workspaces().items():
        xprompts = {
            **load_project_local_xprompts(ws_dir, project_name),
            **load_project_file_xprompts(ws_dir, project_name),
        }
        for name, xp in xprompts.items():
            all_workflows[name] = xprompt_to_workflow(xp)
    return all_workflows


def get_all_xprompts(project: str | None = None) -> dict[str, XPrompt]:
    """Get all xprompts from all sources, respecting priority order.

    When *project* is given (or auto-detected via ``detect_project()``),
    xprompts from project-local sources (CWD xprompt directories and the
    local ``sase.yml``) are namespaced with ``{project}/``.

    Priority order (first wins on name conflict):
    1. .xprompts/*.md (CWD, hidden)
    2. xprompts/*.md (CWD, non-hidden)
    3. ~/.xprompts/*.md (home, hidden)
    4. ~/xprompts/*.md (home, non-hidden)
    5. ~/.config/sase/xprompts/{project}/*.md (project-specific, if project given)
    6. sase.yml xprompts:/snippets: section
    7. Plugin packages (via sase_xprompts entry points)
    8. <sase_package>/default_xprompts/*.md (default built-ins)
    9. <sase_package>/xprompts/*.md (internal)

    Args:
        project: Optional project name.  When ``None``, the project is
            auto-detected via :func:`detect_project`.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    effective_project = project if project is not None else detect_project()

    # Start with lowest priority and let higher priority override
    all_xprompts: dict[str, XPrompt] = {}

    # 9. Internal xprompts (lowest priority)
    all_xprompts.update(load_xprompts_from_internal())

    # 8. Default markdown xprompts
    all_xprompts.update(load_xprompts_from_default_files())

    # 7. Plugin xprompts
    all_xprompts.update(load_xprompts_from_plugins())

    # 6. Config-based xprompts
    config_xprompts = load_xprompts_from_config(project=effective_project)
    all_xprompts.update(config_xprompts)

    # 5. Project-specific xprompts (if project provided)
    if effective_project:
        project_xprompts = load_xprompts_from_project(effective_project)
        all_xprompts.update(project_xprompts)

    # 1-4. File-based xprompts (highest priority) - already sorted
    file_xprompts = load_xprompts_from_files(project=effective_project)
    all_xprompts.update(file_xprompts)

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


def get_all_prompts(project: str | None = None) -> dict[str, "Workflow"]:
    """Get all xprompts and workflows as unified Workflow objects.

    XPrompts are converted to single-step workflows with prompt_part.
    Actual workflows are returned as-is.
    Workflows take precedence on name collision.

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

    # Convert xprompts to workflows (workflows take precedence on collision)
    converted = {
        name: xprompt_to_workflow(xp)
        for name, xp in xprompts.items()
        if name not in workflows
    }
    return {**converted, **workflows}


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
