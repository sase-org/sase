"""Discover and load YAML workflows from each supported source."""

import importlib.resources
import tempfile
from dataclasses import replace
from pathlib import Path

from sase.content_layout import resolve_xprompt_file_sources
from sase.core.paths import get_sase_managed_tmpdir
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.discovery_order import (
    RANK_FILESYSTEM_BASE,
    RANK_PACKAGE_XPROMPTS,
    RANK_PLUGIN,
    RANK_REGISTERED_PROJECT_BASE,
    source_rank,
)
from sase.xprompt.loader import (
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)
from sase.xprompt.project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)
from sase.xprompt.workflow_loader_definition import (
    load_workflow_from_file,
    namespace_workflow,
)
from sase.xprompt.workflow_models import Workflow


def discover_workflow_files(
    project: str | None = None,
) -> list[tuple[Path, int, bool]]:
    """Find workflow files with source priority and locality information."""
    sources = resolve_xprompt_file_sources(project=project)
    namespaced_dirs = {
        source.path
        for source in sources
        if source.path is not None and source.project_namespaced
    }
    search_paths = (
        get_xprompt_search_paths()
        if project is None
        else get_xprompt_search_paths(project)
    )
    if not namespaced_dirs:
        cwd = Path.cwd()
        namespaced_dirs = {
            cwd / "sase" / "xprompts",
            cwd / ".xprompts",
            cwd / "xprompts",
        }

    results: list[tuple[Path, int, bool]] = []
    for priority, search_dir in enumerate(search_paths):
        if not search_dir.is_dir():
            continue

        is_local = search_dir in namespaced_dirs
        for extension in ("*.yml", "*.yaml"):
            for workflow_file in search_dir.glob(extension):
                if workflow_file.is_file():
                    results.append((workflow_file, priority, is_local))

    return results


def load_workflows_from_files(project: str | None = None) -> dict[str, Workflow]:
    """Load filesystem workflows, with earlier search paths taking priority."""
    discovered = discover_workflow_files(project)
    discovered.sort(key=lambda item: item[1], reverse=True)
    source_count = max((priority for _, priority, _ in discovered), default=-1) + 1

    workflows: dict[str, Workflow] = {}
    for file_path, priority, is_local in discovered:
        workflow = load_workflow_from_file(file_path)
        if workflow:
            if project and is_local:
                workflow = namespace_workflow(project, workflow)
            rank = source_rank(RANK_FILESYSTEM_BASE, priority, source_count)
            workflow.discovery_rank = rank
            if workflow.name in workflows:
                if workflows[workflow.name].discovery_rank == rank:
                    continue
                del workflows[workflow.name]
            workflows[workflow.name] = workflow

    return workflows


def load_workflows_from_internal() -> dict[str, Workflow]:
    """Load workflows bundled in the SASE package."""
    internal_dir = get_sase_package_xprompts_dir()
    if not internal_dir.is_dir():
        return {}

    workflows: dict[str, Workflow] = {}
    for extension in ("*.yml", "*.yaml"):
        for workflow_file in internal_dir.glob(extension):
            if not workflow_file.is_file():
                continue
            workflow = load_workflow_from_file(workflow_file)
            if workflow:
                workflow.discovery_rank = RANK_PACKAGE_XPROMPTS
                workflows[workflow.name] = workflow

    return workflows


def load_workflows_from_plugins() -> dict[str, Workflow]:
    """Load workflows from plugin ``sase_xprompts`` resources."""
    if is_plugin_disabled("XPROMPTS"):
        return {}

    workflows: dict[str, Workflow] = {}
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            xprompts_dir = importlib.resources.files(module).joinpath("xprompts")
        except (TypeError, AttributeError):
            continue

        try:
            entries = list(xprompts_dir.iterdir())  # type: ignore[union-attr]
        except (FileNotFoundError, OSError, TypeError):
            continue

        for entry in entries:
            entry_name: str = entry.name  # type: ignore[union-attr]
            if not entry_name.endswith((".yml", ".yaml")):
                continue
            try:
                text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, UnicodeDecodeError):
                continue

            tmpdir = Path(
                tempfile.mkdtemp(dir=get_sase_managed_tmpdir("workflow-loader"))
            )
            tmp_path = tmpdir / entry_name
            try:
                tmp_path.write_text(text, encoding="utf-8")
                workflow = load_workflow_from_file(tmp_path)
                if workflow:
                    source = f"plugin:{module.__name__}/{entry_name}"
                    workflows[workflow.name] = replace(
                        workflow,
                        source_path=source,
                        discovery_rank=RANK_PLUGIN,
                    )
            finally:
                tmp_path.unlink(missing_ok=True)
                tmpdir.rmdir()

    return workflows


def load_workflows_from_project(project: str) -> dict[str, Workflow]:
    """Load and namespace project-specific workflows from home sources."""
    workflows: dict[str, Workflow] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    ]
    rank_by_path = {
        project_dir: source_rank(RANK_FILESYSTEM_BASE, index, len(project_dirs))
        for index, project_dir in enumerate(project_dirs)
    }
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for extension in ("*.yaml", "*.yml"):
            for workflow_file in project_dir.glob(extension):
                if not workflow_file.is_file():
                    continue
                workflow = load_workflow_from_file(workflow_file)
                if workflow:
                    namespaced = namespace_workflow(project, workflow)
                    namespaced.discovery_rank = rank_by_path[project_dir]
                    if namespaced.name in workflows:
                        del workflows[namespaced.name]
                    workflows[namespaced.name] = namespaced
    return workflows


def load_workflows_from_project_workspace(
    project: str,
    *,
    detected_project: str | None,
) -> dict[str, Workflow]:
    """Load workflows from a registered project's primary workspace."""
    if canonical_xprompt_project(detected_project) == project:
        return {}

    workspace_dir = known_project_namespaces().get(project)
    if workspace_dir is None:
        return {}

    workflows: dict[str, Workflow] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(
            project_root=workspace_dir,
            project=project,
        )
        if source.path is not None and source.scope == "project"
    ]
    rank_by_path = {
        project_dir: source_rank(RANK_REGISTERED_PROJECT_BASE, index, len(project_dirs))
        for index, project_dir in enumerate(project_dirs)
    }
    for xprompt_dir in reversed(project_dirs):
        if not xprompt_dir.is_dir():
            continue

        for extension in ("*.yml", "*.yaml"):
            for workflow_file in sorted(xprompt_dir.glob(extension)):
                if not workflow_file.is_file():
                    continue
                workflow = load_workflow_from_file(workflow_file)
                if not workflow:
                    continue
                namespaced = namespace_workflow(project, workflow)
                namespaced.discovery_rank = rank_by_path[xprompt_dir]
                if (
                    namespaced.name in workflows
                    and workflows[namespaced.name].discovery_rank
                    == namespaced.discovery_rank
                ):
                    continue
                if namespaced.name in workflows:
                    del workflows[namespaced.name]
                workflows[namespaced.name] = namespaced

    return workflows
