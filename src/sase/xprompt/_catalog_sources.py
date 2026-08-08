"""Collection, classification, and source display helpers for xprompt catalogs."""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path

from sase.content_layout import (
    discover_project_root,
    resolve_home_layout,
    resolve_project_config_read_path,
)
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader import (
    get_all_workflows,
    get_all_xprompts,
    get_sase_package_default_xprompts_dir,
    get_sase_package_skills_dir,
    get_sase_package_xprompts_dir,
    load_project_file_xprompts,
    load_project_local_xprompts,
)
from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)
from sase.xprompt.workflow_models import Workflow

from ._catalog_models import CatalogEntry, StructuredCatalogSource

log = logging.getLogger(__name__)


def gather_entries() -> list[CatalogEntry]:
    """Collect all xprompts from every source, classified and de-duplicated."""
    seen: dict[tuple[str, str], CatalogEntry] = {}

    for xp in get_all_xprompts().values():
        entry = classify(xp, project=None)
        seen[(xp.source_path or "", xp.name)] = entry

    for project, workspace in known_project_namespaces().items():
        try:
            project_xprompts = {
                **load_project_local_xprompts(workspace, project),
                **load_project_file_xprompts(workspace, project),
            }
        except Exception:
            log.debug(
                "Failed to load project-local xprompts for %s",
                project,
                exc_info=True,
            )
            continue
        for xp in project_xprompts.values():
            key = (xp.source_path or "", xp.name)
            if key in seen:
                continue
            seen[key] = classify(xp, project=project)

    return sorted(
        seen.values(), key=lambda e: (e.bucket, e.project or "", e.xprompt.name)
    )


def gather_structured_entries() -> list[StructuredCatalogSource]:
    """Collect workflow-like prompts for the mobile structured catalog."""
    seen: dict[tuple[str, str], StructuredCatalogSource] = {}

    workflows = get_all_workflows()
    for name, workflow in workflows.items():
        entry = classify_workflow(name, workflow, project=None)
        seen[(workflow.source_path or "", name)] = entry

    workflow_names = set(workflows)
    for name, xp in get_all_xprompts().items():
        if name in workflow_names:
            continue
        key = (xp.source_path or "", name)
        if key in seen:
            continue
        entry = classify_xprompt_for_structured(xp, project=None)
        seen[key] = entry

    for project, workspace in known_project_namespaces().items():
        try:
            project_xprompts = {
                **load_project_local_xprompts(workspace, project),
                **load_project_file_xprompts(workspace, project),
            }
        except Exception:
            log.debug(
                "Failed to load project-local xprompts for %s",
                project,
                exc_info=True,
            )
            continue
        for name, xp in project_xprompts.items():
            key = (xp.source_path or "", name)
            if key in seen:
                continue
            seen[key] = classify_xprompt_for_structured(xp, project=project)

    return sorted(seen.values(), key=lambda e: (e.bucket, e.project or "", e.name))


def classify_xprompt_for_structured(
    xp: XPrompt, project: str | None
) -> StructuredCatalogSource:
    catalog_entry = classify(xp, project=project)
    return StructuredCatalogSource(
        name=xp.name,
        workflow=xprompt_to_workflow(xp),
        bucket=catalog_entry.bucket,
        project=catalog_entry.project,
        description=xp.description,
        is_skill=bool(xp.skill),
        content=xp.content,
        skill_name=xp.skill_name,
        memory_type=xp.memory_type,
    )


def classify_workflow(
    name: str, workflow: Workflow, project: str | None
) -> StructuredCatalogSource:
    source = workflow.source_path or ""
    catalog_entry = classify(
        XPrompt(
            name=name,
            content=workflow.get_prompt_part_content(),
            inputs=workflow.inputs,
            source_path=source,
            tags=workflow.tags,
            description=workflow.description,
            memory_type=workflow.memory_type,
        ),
        project=project,
    )
    return StructuredCatalogSource(
        name=name,
        workflow=workflow,
        bucket=catalog_entry.bucket,
        project=catalog_entry.project,
        description=workflow.description,
        content=workflow.get_prompt_part_content(),
        memory_type=workflow.memory_type,
    )


def classify(xp: XPrompt, project: str | None) -> CatalogEntry:
    """Classify an xprompt into a source bucket."""
    source = xp.source_path or ""

    if not source:
        return CatalogEntry(xp, bucket="config", project=None)

    if source.startswith(("plugin:", "plugin_config:")):
        return CatalogEntry(xp, bucket="plugin", project=None)

    if source == "default_config":
        return CatalogEntry(xp, bucket="config", project=None)

    if source == "config" or source.startswith(("config:", "config_overlay:")):
        return CatalogEntry(xp, bucket="config", project=None)

    source_path = Path(source)

    if source_path.is_absolute():
        for package_dir in package_xprompt_dirs():
            try:
                source_path.resolve().relative_to(package_dir.resolve())
                return CatalogEntry(xp, bucket="built-in", project=None)
            except (ValueError, OSError):
                pass

        if project is not None:
            return CatalogEntry(xp, bucket="project", project=project)

        workspaces = known_project_namespaces()
        for project_name, ws in workspaces.items():
            try:
                source_path.resolve().relative_to(ws.resolve())
                return CatalogEntry(xp, bucket="project", project=project_name)
            except (ValueError, OSError):
                continue

        config_dir = Path.home() / ".config" / "sase"
        try:
            source_path.resolve().relative_to(config_dir.resolve())
            return CatalogEntry(xp, bucket="config", project=None)
        except (ValueError, OSError):
            pass

    if project is not None:
        return CatalogEntry(xp, bucket="project", project=project)

    # Unknown source: treat as user-scoped config-like content.
    return CatalogEntry(xp, bucket="config", project=None)


def entry_source_path(entry: CatalogEntry | StructuredCatalogSource) -> str | None:
    if isinstance(entry, CatalogEntry):
        return entry.xprompt.source_path
    return entry.workflow.source_path


def source_path_display(
    entry: CatalogEntry | StructuredCatalogSource,
) -> str | None:
    source = entry_source_path(entry)
    if not source:
        return None
    if source == "default_config":
        return "sase default_config.yml"
    if source == "config":
        return "~/.config/sase/sase.yml"
    if source.startswith("config_overlay:"):
        return f"~/.config/sase/{source.removeprefix('config_overlay:')}"
    if source == "local_config" or source.startswith("project_local_config:"):
        return "sase/sase.yml"
    if source.startswith(("config:", "plugin:", "plugin_config:")):
        return source

    path = Path(source)
    if not path.is_absolute():
        return source

    for project, workspace in known_project_namespaces().items():
        try:
            rel = path.resolve().relative_to(workspace.resolve())
        except (ValueError, OSError):
            continue
        if entry.project is None or project == entry.project:
            return rel.as_posix()

    for package_dir in package_xprompt_dirs():
        try:
            rel = path.resolve().relative_to(package_dir.resolve())
        except (ValueError, OSError):
            continue
        return f"{package_dir.name}/{rel.as_posix()}"

    try:
        home_layout = resolve_home_layout()
    except Exception:
        home_layout = None
    if home_layout is not None:
        for memory_root in home_layout.memory.candidates:
            try:
                path.resolve().relative_to(memory_root.resolve())
            except (ValueError, OSError):
                continue
            return safe_path_display(path)

    config_dir = Path.home() / ".config" / "sase"
    try:
        rel = path.resolve().relative_to(config_dir.resolve())
    except (ValueError, OSError):
        return None
    return f"~/.config/sase/{rel.as_posix()}"


def definition_path(entry: CatalogEntry | StructuredCatalogSource) -> str | None:
    """Return an absolute local file path suitable for editor navigation."""
    source = entry_source_path(entry)
    if not source:
        return None

    path = _source_definition_path(source, entry.project)
    if path is None or not path.is_file():
        return None
    try:
        return str(path.resolve())
    except OSError:
        return None


def _source_definition_path(source: str, project: str | None) -> Path | None:
    if source.startswith("plugin:"):
        return _plugin_xprompt_definition_path(source)

    if source.startswith("plugin_config:"):
        return _plugin_config_definition_path(source)

    if source == "default_config":
        try:
            ref = importlib.resources.files("sase").joinpath("default_config.yml")
            return Path(str(ref))
        except Exception:
            return None

    if source == "local_config":
        root = discover_project_root() or Path.cwd()
        return resolve_project_config_read_path(root)

    if source.startswith("project_local_config:"):
        project_name = source.removeprefix("project_local_config:")
        namespace = canonical_xprompt_project(project_name) or project_name
        workspace = known_project_namespaces().get(namespace)
        if workspace is None:
            return None
        return resolve_project_config_read_path(
            workspace,
            label=f"project config for {namespace}",
        )

    config_dir = Path.home() / ".config" / "sase"
    if source == "config":
        return config_dir / "sase.yml"

    if source.startswith("config_overlay:"):
        filename = source.removeprefix("config_overlay:")
        return config_dir / filename

    if source.startswith("config:"):
        return None

    path = Path(source)
    if path.is_absolute():
        return path

    if project is not None:
        workspace = known_project_namespaces().get(project)
        if workspace is not None:
            project_path = workspace / path
            if project_path.is_file():
                return project_path

    return Path.cwd() / path


def _plugin_xprompt_definition_path(source: str) -> Path | None:
    if is_plugin_disabled("XPROMPTS"):
        return None

    remainder = source.removeprefix("plugin:")
    if "/" not in remainder:
        return None
    module_name, filename = remainder.split("/", 1)
    if not module_name or not filename:
        return None

    for module in discover_plugin_resources("sase_xprompts"):
        if getattr(module, "__name__", None) != module_name:
            continue
        try:
            ref = importlib.resources.files(module).joinpath("xprompts", filename)
        except (TypeError, AttributeError):
            return None
        return Path(str(ref))
    return None


def _plugin_config_definition_path(source: str) -> Path | None:
    if is_plugin_disabled("CONFIG"):
        return None

    module_name = source.removeprefix("plugin_config:")
    if not module_name:
        return None

    for module in discover_plugin_resources("sase_config"):
        if getattr(module, "__name__", None) != module_name:
            continue
        try:
            ref = importlib.resources.files(module).joinpath("default_config.yml")
        except (TypeError, AttributeError):
            return None
        return Path(str(ref))
    return None


def safe_path_display(path: Path) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    home = Path.home()
    try:
        rel = resolved.relative_to(home.resolve())
    except (ValueError, OSError):
        return None
    return f"~/{rel.as_posix()}"


def safe_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def package_xprompt_dirs() -> list[Path]:
    package_dirs: list[Path] = []
    for get_package_dir in (
        get_sase_package_xprompts_dir,
        get_sase_package_default_xprompts_dir,
        get_sase_package_skills_dir,
    ):
        try:
            package_dirs.append(get_package_dir())
        except Exception:
            pass
    return package_dirs


_gather_entries = gather_entries
_gather_structured_entries = gather_structured_entries
_classify_xprompt_for_structured = classify_xprompt_for_structured
_classify_workflow = classify_workflow
_classify = classify
_entry_source_path = entry_source_path
_source_path_display = source_path_display
_definition_path = definition_path
_safe_path_display = safe_path_display
_safe_file_size = safe_file_size
_package_xprompt_dirs = package_xprompt_dirs
