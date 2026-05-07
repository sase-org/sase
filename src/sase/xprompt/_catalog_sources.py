"""Collection, classification, and source display helpers for xprompt catalogs."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.xprompt.loader import (
    get_all_workflows,
    get_all_xprompts,
    get_known_project_workspaces,
    get_sase_package_default_xprompts_dir,
    get_sase_package_xprompts_dir,
    load_project_local_xprompts,
)
from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.workflow_models import Workflow

from ._catalog_models import CatalogEntry, StructuredCatalogSource

log = logging.getLogger(__name__)


def gather_entries() -> list[CatalogEntry]:
    """Collect all xprompts from every source, classified and de-duplicated."""
    seen: dict[tuple[str, str], CatalogEntry] = {}

    for xp in get_all_xprompts().values():
        entry = classify(xp, project=None)
        seen[(xp.source_path or "", xp.name)] = entry

    for project, workspace in get_known_project_workspaces().items():
        try:
            project_xprompts = load_project_local_xprompts(workspace, project)
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

    for project, workspace in get_known_project_workspaces().items():
        try:
            project_xprompts = load_project_local_xprompts(workspace, project)
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
            keywords=workflow.keywords,
        ),
        project=project,
    )
    return StructuredCatalogSource(
        name=name,
        workflow=workflow,
        bucket=catalog_entry.bucket,
        project=catalog_entry.project,
        content=workflow.get_prompt_part_content(),
    )


def classify(xp: XPrompt, project: str | None) -> CatalogEntry:
    """Classify an xprompt into a source bucket."""
    source = xp.source_path or ""

    if source.startswith("plugin:"):
        return CatalogEntry(xp, bucket="plugin", project=None)

    if source == "config" or source.startswith("config:"):
        return CatalogEntry(xp, bucket="config", project=None)

    source_path = Path(source) if source else None

    if source_path is not None:
        for package_dir in package_xprompt_dirs():
            try:
                source_path.resolve().relative_to(package_dir.resolve())
                return CatalogEntry(xp, bucket="built-in", project=None)
            except (ValueError, OSError):
                pass

    if source_path is not None and "memory/long" in source_path.as_posix():
        return CatalogEntry(xp, bucket="memory", project=None)

    if project is not None:
        return CatalogEntry(xp, bucket="project", project=project)

    workspaces = get_known_project_workspaces()
    if source_path is not None:
        for project_name, ws in workspaces.items():
            try:
                source_path.resolve().relative_to(ws.resolve())
                return CatalogEntry(xp, bucket="project", project=project_name)
            except (ValueError, OSError):
                continue

    config_dir = Path.home() / ".config" / "sase"
    if source_path is not None:
        try:
            source_path.resolve().relative_to(config_dir.resolve())
            return CatalogEntry(xp, bucket="config", project=None)
        except (ValueError, OSError):
            pass

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
    if source == "config" or source.startswith(
        ("config:", "plugin:", "plugin_config:")
    ):
        return source

    path = Path(source)
    if not path.is_absolute():
        return source

    for project, workspace in get_known_project_workspaces().items():
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

    config_dir = Path.home() / ".config" / "sase"
    try:
        rel = path.resolve().relative_to(config_dir.resolve())
    except (ValueError, OSError):
        return None
    return f"~/.config/sase/{rel.as_posix()}"


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
_safe_path_display = safe_path_display
_safe_file_size = safe_file_size
_package_xprompt_dirs = package_xprompt_dirs
