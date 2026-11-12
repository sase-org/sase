"""Discover and load YAML workflows from each supported source."""

import importlib.resources
import tempfile
from dataclasses import replace
from pathlib import Path

from sase.content_layout import resolve_macro_file_sources
from sase.core.paths import get_sase_managed_tmpdir
from sase.main.plugin_discovery import (
    discover_macro_plugin_modules,
    macro_plugin_definition_dirname,
    macro_plugins_disabled,
)
from sase.macro.discovery_order import (
    RANK_CONFIG_BASE,
    RANK_FILESYSTEM_BASE,
    RANK_PACKAGE_MACROS,
    RANK_PLUGIN,
    RANK_REGISTERED_PROJECT_BASE,
    merge_by_discovery_order,
    source_rank,
)
from sase.macro.loader import (
    get_sase_package_macros_dir,
    get_macro_search_paths,
)
from sase.macro.project_identity import (
    canonical_macro_project,
    known_project_namespaces,
)
from sase.macro.workflow_loader_definition import (
    load_workflow_from_file,
    load_workflow_from_mapping,
    namespace_workflow,
)
from sase.macro.workflow_models import Workflow


def discover_workflow_files(
    project: str | None = None,
) -> list[tuple[Path, int, bool]]:
    """Find workflow files with source priority and locality information."""
    sources = resolve_macro_file_sources(project=project)
    namespaced_dirs = {
        source.path
        for source in sources
        if source.path is not None and source.project_namespaced
    }
    search_paths = (
        get_macro_search_paths() if project is None else get_macro_search_paths(project)
    )
    if not namespaced_dirs:
        # Retired directories are always accepted as aliases.
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
    internal_dir = get_sase_package_macros_dir()
    if not internal_dir.is_dir():
        return {}

    workflows: dict[str, Workflow] = {}
    for extension in ("*.yml", "*.yaml"):
        for workflow_file in internal_dir.glob(extension):
            if not workflow_file.is_file():
                continue
            workflow = load_workflow_from_file(workflow_file)
            if workflow:
                workflow.discovery_rank = RANK_PACKAGE_MACROS
                workflows[workflow.name] = workflow

    return workflows


def load_workflows_from_plugins() -> dict[str, Workflow]:
    """Load workflows from plugin ``sase_macros`` resources.

    Probes each plugin's ``macros/`` directory first and always accepts
    the retired directory as an alias.
    """
    if macro_plugins_disabled():
        return {}

    workflows: dict[str, Workflow] = {}
    for module in discover_macro_plugin_modules():
        resource_dir = macro_plugin_definition_dirname(module)
        if resource_dir is None:
            continue
        try:
            macros_dir = importlib.resources.files(module).joinpath(resource_dir)
        except (TypeError, AttributeError):
            continue

        try:
            entries = list(macros_dir.iterdir())  # type: ignore[union-attr]
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


def load_workflows_from_config(project: str | None = None) -> dict[str, Workflow]:
    """Load command-bearing config macros as workflows.

    Prompt-only config macros stay in :func:`load_macros_from_config`. Local
    executable entries are trust-filtered by the shared effective-local
    adapter before this conversion, and carry a descriptor for dispatch
    revalidation.
    """
    from sase.config import load_macros_by_source
    from sase.macro.local_trust import (
        attach_local_trust,
        partition_config_macros,
        workflow_mapping_from_macro_entry,
    )

    all_workflows: dict[str, Workflow] = {}
    sources = load_macros_by_source()
    local_snapshot = getattr(sources, "local_snapshot", None)
    local_evaluation = getattr(sources, "local_trust", None)
    lower_config: dict[str, object] = {}
    composed_local_macros: dict[str, object] = {}
    try:
        from sase.config.core import (
            load_merged_config_for_local_snapshot,
            load_merged_config_for_local_path,
        )

        lower_config = load_merged_config_for_local_path(None)
        if local_snapshot is not None:
            local_config, _ = load_merged_config_for_local_snapshot(
                local_snapshot.path, local_snapshot
            )
            raw_composed = local_config.get("macros")
            if isinstance(raw_composed, dict):
                composed_local_macros = raw_composed
    except Exception:
        # A missing composition capability cannot safely turn a sparse local
        # override into an executable workflow.
        composed_local_macros = {}
    lower_raw = lower_config.get("macros")
    lower_macros = dict(lower_raw) if isinstance(lower_raw, dict) else {}

    for index, (source_label, macros_data) in enumerate(sources):
        _prompt_only, executable = partition_config_macros(
            macros_data,
            lower_macros=(lower_macros if source_label == "local_config" else None),
            source=source_label,
        )
        parsed: dict[str, Workflow] = {}
        for name, value in executable.items():
            composed = (
                composed_local_macros.get(name, value)
                if source_label == "local_config"
                else value
            )
            mapping = workflow_mapping_from_macro_entry(composed)
            if mapping is None:
                continue
            workflow = load_workflow_from_mapping(name, mapping, source_label)
            if workflow is None:
                continue
            if source_label == "local_config" and project:
                workflow = namespace_workflow(project, workflow)
            if source_label == "local_config" and local_evaluation is not None:
                attach_local_trust(workflow, local_evaluation)
            parsed[workflow.name] = workflow
        merge_by_discovery_order(
            all_workflows,
            parsed,
            fallback_rank=source_rank(RANK_CONFIG_BASE, index, len(sources)),
        )
    return all_workflows


def load_workflows_from_project(project: str) -> dict[str, Workflow]:
    """Load and namespace project-specific workflows from home sources."""
    workflows: dict[str, Workflow] = {}
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
    if canonical_macro_project(detected_project) == project:
        return {}

    workspace_dir = known_project_namespaces().get(project)
    if workspace_dir is None:
        return {}

    workflows: dict[str, Workflow] = {}
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
    for macro_dir in reversed(project_dirs):
        if not macro_dir.is_dir():
            continue

        for extension in ("*.yml", "*.yaml"):
            for workflow_file in sorted(macro_dir.glob(extension)):
                if not workflow_file.is_file():
                    continue
                workflow = load_workflow_from_file(workflow_file)
                if not workflow:
                    continue
                namespaced = namespace_workflow(project, workflow)
                namespaced.discovery_rank = rank_by_path[macro_dir]
                if (
                    namespaced.name in workflows
                    and workflows[namespaced.name].discovery_rank
                    == namespaced.discovery_rank
                ):
                    continue
                if namespaced.name in workflows:
                    del workflows[namespaced.name]
                workflows[namespaced.name] = namespaced

    from sase.macro.loader_sources import load_project_local_workflows

    merge_by_discovery_order(
        workflows,
        load_project_local_workflows(workspace_dir, project),
    )
    return workflows
