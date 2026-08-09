"""Step-definition imports used while loading xprompt workflows."""

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.content_layout import discover_project_root
from sase.xprompt.loader import (
    detect_project,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)
from sase.xprompt.load_issues import record_load_issue

log = logging.getLogger(__name__)


def get_step_search_dirs(
    workflow_source_path: str | None = None,
) -> list[Path]:
    """Get directories to search for step definition files.

    Returns ``steps/`` subdirectories of each xprompt search path, plus the
    internal package ``steps/`` directory. Order matches the xprompt priority
    (CWD dirs first, internal last).
    """
    project = detect_project()
    source_root = (
        discover_project_root(Path(workflow_source_path).parent)
        if workflow_source_path is not None
        else None
    )
    if project is None and source_root is None:
        paths = get_xprompt_search_paths()
    else:
        paths = get_xprompt_search_paths(project, project_root=source_root)
    dirs = [path / "steps" for path in paths]
    if workflow_source_path is not None:
        source = Path(workflow_source_path)
        if source.is_absolute() or source.parent != Path("."):
            source_steps = source.parent / "steps"
            if source_steps not in dirs:
                dirs.append(source_steps)
    dirs.append(get_sase_package_xprompts_dir() / "steps")
    return dirs


def load_step_definition(
    use_ref: str,
    *,
    workflow_source_path: str | None = None,
) -> dict[str, Any] | None:
    """Load a step definition file referenced by a ``use:`` field.

    Args:
        use_ref: Slash-separated path relative to a ``steps/`` directory
            (e.g. ``shared/check_changes``).

    Returns:
        Parsed YAML dict for the step, or ``None`` if not found.
    """
    if ".." in use_ref or use_ref.startswith("/"):
        log.warning("Rejecting step import with unsafe path: %s", use_ref)
        if workflow_source_path is not None:
            record_load_issue(
                workflow_source_path,
                f"unsafe step import {use_ref!r}",
                kind="step_import",
            )
        return None

    for search_dir in get_step_search_dirs(workflow_source_path):
        for ext in (".yml", ".yaml"):
            candidate = search_dir / f"{use_ref}{ext}"
            if not candidate.is_file():
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    return data
                if workflow_source_path is not None:
                    record_load_issue(
                        workflow_source_path,
                        f"step import {use_ref!r} did not parse to a mapping",
                        kind="step_import",
                    )
            except (OSError, yaml.YAMLError) as exc:
                if workflow_source_path is not None:
                    record_load_issue(
                        workflow_source_path,
                        f"failed to load step import {use_ref!r}: {exc}",
                        kind="step_import",
                    )
                continue
    return None


def resolve_step_imports(
    step_data: dict[str, Any],
    *,
    workflow_source_path: str | None = None,
) -> dict[str, Any] | None:
    """Resolve ``use:`` imports in *step_data*, including parallel steps.

    Local fields in *step_data* override fields from the imported definition.
    ``None`` is returned when an import cannot be resolved.
    """
    use_ref = step_data.get("use")
    if use_ref:
        base = load_step_definition(
            str(use_ref),
            workflow_source_path=workflow_source_path,
        )
        if base is None:
            log.warning("Step import '%s' not found", use_ref)
            if workflow_source_path is not None:
                record_load_issue(
                    workflow_source_path,
                    f"step import {use_ref!r} not found",
                    kind="step_import",
                )
            return None
        merged = dict(base)
        for key, value in step_data.items():
            if key != "use":
                merged[key] = value
        step_data = merged

    parallel_data = step_data.get("parallel")
    if isinstance(parallel_data, list):
        resolved_parallel: list[Any] = []
        for nested in parallel_data:
            if isinstance(nested, dict):
                resolved = resolve_step_imports(
                    nested,
                    workflow_source_path=workflow_source_path,
                )
                if resolved is None:
                    return None
                resolved_parallel.append(resolved)
            else:
                resolved_parallel.append(nested)
        step_data = dict(step_data, parallel=resolved_parallel)

    return step_data
