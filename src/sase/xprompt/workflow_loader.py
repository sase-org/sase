"""Workflow discovery and loading from YAML files."""

import importlib.resources
import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.content_layout import discover_project_root, resolve_xprompt_file_sources
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader import (
    detect_project,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.load_issues import record_load_issue
from sase.xprompt.models import (
    UNSET,
    InputArg,
    InputType,
    XPromptValidationError,
)
from sase.xprompt.project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)
from sase.xprompt.tags import parse_tags
from sase.xprompt.workflow_loader_parse import (
    parse_workflow_step as _parse_workflow_step,
    parse_workflow_inputs,
    validate_workflow_variables,
)
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)

log = logging.getLogger(__name__)

_REMOVED_AGENT_FAMILY_KIND_ERROR = (
    "kind: agent_family is no longer supported; attach family members manually "
    "with %i(suffix, family=parent). Agent-initiated family launches use "
    "LaunchApproval."
)


def _get_step_search_dirs(
    workflow_source_path: str | None = None,
) -> list[Path]:
    """Get directories to search for step definition files.

    Returns ``steps/`` subdirectories of each xprompt search path, plus the
    internal package ``steps/`` directory.  Order matches the xprompt priority
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
    dirs = [p / "steps" for p in paths]
    if workflow_source_path is not None:
        source = Path(workflow_source_path)
        if source.is_absolute() or source.parent != Path("."):
            source_steps = source.parent / "steps"
            if source_steps not in dirs:
                dirs.append(source_steps)
    dirs.append(get_sase_package_xprompts_dir() / "steps")
    return dirs


def _load_step_definition(
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
    # Reject suspicious paths
    if ".." in use_ref or use_ref.startswith("/"):
        log.warning("Rejecting step import with unsafe path: %s", use_ref)
        if workflow_source_path is not None:
            record_load_issue(
                workflow_source_path,
                f"unsafe step import {use_ref!r}",
                kind="step_import",
            )
        return None

    for search_dir in _get_step_search_dirs(workflow_source_path):
        for ext in (".yml", ".yaml"):
            candidate = search_dir / f"{use_ref}{ext}"
            if candidate.is_file():
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


def _resolve_step_imports(
    step_data: dict[str, Any],
    *,
    workflow_source_path: str | None = None,
) -> dict[str, Any] | None:
    """Resolve ``use:`` imports in *step_data*, including nested parallel steps.

    Local fields in *step_data* override fields from the imported definition.

    Returns:
        The resolved step data dict, or ``None`` if resolution failed.
    """
    use_ref = step_data.get("use")
    if use_ref:
        base = _load_step_definition(
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

    # Recursively resolve nested parallel steps
    parallel_data = step_data.get("parallel")
    if isinstance(parallel_data, list):
        resolved_parallel: list[Any] = []
        for nested in parallel_data:
            if isinstance(nested, dict):
                resolved = _resolve_step_imports(
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


def _namespace_workflow(project: str, wf: Workflow) -> Workflow:
    """Return a copy of *wf* with its name prefixed by ``{project}/``."""
    namespaced_name = f"{project}/{wf.name}"
    return Workflow(
        name=namespaced_name,
        inputs=wf.inputs,
        steps=wf.steps,
        source_path=wf.source_path,
        xprompts=wf.xprompts,
        wraps_all=wf.wraps_all,
        hidden=wf.hidden,
        tags=wf.tags,
        environment=wf.environment,
        description=wf.description,
        skill_name=wf.skill_name,
        memory_type=wf.memory_type,
        ref=wf.ref,
        ref_kind=wf.ref_kind,
        ref_sidecar_role=wf.ref_sidecar_role,
        ref_path_globs=wf.ref_path_globs,
        ref_shadowed_sources=wf.ref_shadowed_sources,
    )


def _load_workflow_from_mapping(
    name: str, data: dict[str, Any], source_path: str
) -> Workflow | None:
    """Load a single workflow from parsed YAML data.

    Args:
        name: Workflow name.
        data: Parsed workflow definition.
        source_path: File path or source label where the workflow was loaded from.

    Returns:
        Workflow object if successfully loaded, None otherwise.
    """
    # Parse wraps_all
    wraps_all = bool(data.get("wraps_all", False))
    hidden = bool(data.get("hidden", False))
    description_value = data.get("description")
    description = None if description_value is None else str(description_value)

    # Parse tags (with wraps_all backward compat)
    from sase.xprompt.tags import XPromptTag

    tags = parse_tags(data.get("tags"))
    if wraps_all and XPromptTag.vcs not in tags:
        tags = tags | frozenset({XPromptTag.vcs})
    if XPromptTag.vcs in tags:
        wraps_all = True

    # Parse inputs
    try:
        inputs = parse_workflow_inputs(data.get("input"))
    except XPromptValidationError as exc:
        record_load_issue(source_path, exc, kind="workflow")
        return None

    # Parse workflow-local xprompts
    xprompts_data = data.get("xprompts")
    parsed_xprompts = (
        parse_xprompt_entries(xprompts_data, source_path)
        if isinstance(xprompts_data, dict)
        else {}
    )

    # Parse environment
    environment_data = data.get("environment")
    environment: dict[str, str] = {}
    if isinstance(environment_data, dict):
        environment = {str(k): str(v) for k, v in environment_data.items()}

    # Parse steps
    steps_data = data.get("steps", [])
    if not isinstance(steps_data, list):
        record_load_issue(source_path, "steps must be a list", kind="workflow")
        return None

    steps: list[WorkflowStep] = []
    try:
        for step_index, step_data in enumerate(steps_data):
            if not isinstance(step_data, dict):
                continue
            # Resolve step imports (use: field) before parsing
            if "use" in step_data:
                resolved = _resolve_step_imports(
                    step_data,
                    workflow_source_path=source_path,
                )
                if resolved is None:
                    continue
                step_data = resolved
            step = _parse_workflow_step(step_data, step_index)
            steps.append(step)

        # Validate at most one prompt_part step per workflow
        prompt_part_count = sum(1 for step in steps if step.is_prompt_part_step())
        if prompt_part_count > 1:
            raise WorkflowValidationError(
                f"Workflow '{name}' has {prompt_part_count} prompt_part steps, "
                "but at most one is allowed"
            )
    except WorkflowValidationError as exc:
        record_load_issue(source_path, exc, kind="workflow")
        return None

    if not steps:
        record_load_issue(
            source_path, "no valid workflow steps parsed", kind="workflow"
        )
        return None

    # Generate implicit inputs for each step with an output schema
    # These allow users to provide step outputs directly, skipping those steps
    explicit_input_names = {inp.name for inp in inputs}
    for step in steps:
        if step.output is not None and step.name not in explicit_input_names:
            implicit_input = InputArg(
                name=step.name,
                type=InputType.LINE,  # Type doesn't matter for step inputs
                default=UNSET,  # Not required by default
                is_step_input=True,
                output_schema=step.output,
            )
            inputs.append(implicit_input)

    workflow = Workflow(
        name=str(name),
        inputs=inputs,
        steps=steps,
        source_path=source_path,
        xprompts=parsed_xprompts,
        wraps_all=wraps_all,
        hidden=hidden,
        tags=tags,
        environment=environment,
        description=description,
    )

    # Validate variable usage
    try:
        validate_workflow_variables(workflow)
    except WorkflowValidationError:
        # For now, just return the workflow even if validation fails
        # The error will be raised at runtime with more context
        pass

    return workflow


def _load_workflow_from_file(file_path: Path) -> Workflow | None:
    """Load a single workflow from a YAML file.

    Args:
        file_path: Path to the .yml/.yaml file.

    Returns:
        Workflow object if successfully loaded, None otherwise.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except OSError as exc:
        record_load_issue(file_path, exc, kind="workflow")
        return None
    except yaml.YAMLError as exc:
        record_load_issue(file_path, exc, kind="workflow")
        return None

    if not isinstance(data, dict):
        record_load_issue(file_path, "top-level YAML is not a mapping", kind="workflow")
        return None
    if data.get("kind") == "agent_family":
        raise WorkflowValidationError(_REMOVED_AGENT_FAMILY_KIND_ERROR)

    return _load_workflow_from_mapping(file_path.stem, data, str(file_path))


def _discover_workflow_files(
    project: str | None = None,
) -> list[tuple[Path, int, bool]]:
    """Find all workflow files in search paths with priority and locality info.

    Returns:
        List of ``(file_path, priority, is_local)`` tuples.
        Lower *priority* wins.  *is_local* is ``True`` for CWD directories.
    """
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
        for yml_file in search_dir.glob("*.yml"):
            if yml_file.is_file():
                results.append((yml_file, priority, is_local))

        for yaml_file in search_dir.glob("*.yaml"):
            if yaml_file.is_file():
                results.append((yaml_file, priority, is_local))

    return results


def _load_workflows_from_files(project: str | None = None) -> dict[str, Workflow]:
    """Load workflows from file system locations.

    When *project* is given, workflows from CWD directories are namespaced
    with ``{project}/``.

    Returns:
        Dictionary mapping workflow name to Workflow object.
        Earlier priority sources override later ones.
    """
    discovered = _discover_workflow_files(project)

    # Sort by priority (lower is higher priority)
    discovered.sort(key=lambda x: x[1])

    workflows: dict[str, Workflow] = {}
    for file_path, _, is_local in discovered:
        workflow = _load_workflow_from_file(file_path)
        if workflow:
            if project and is_local:
                workflow = _namespace_workflow(project, workflow)
            if workflow.name not in workflows:
                # First occurrence wins
                workflows[workflow.name] = workflow

    return workflows


def _load_workflows_from_internal() -> dict[str, Workflow]:
    """Load workflows from the internal sase package xprompts directory.

    Returns:
        Dictionary mapping workflow name to Workflow object.
    """
    internal_dir = get_sase_package_xprompts_dir()

    if not internal_dir.is_dir():
        return {}

    workflows: dict[str, Workflow] = {}
    for yml_file in internal_dir.glob("*.yml"):
        if yml_file.is_file():
            workflow = _load_workflow_from_file(yml_file)
            if workflow:
                workflows[workflow.name] = workflow

    for yaml_file in internal_dir.glob("*.yaml"):
        if yaml_file.is_file():
            workflow = _load_workflow_from_file(yaml_file)
            if workflow:
                workflows[workflow.name] = workflow

    return workflows


def _load_workflows_from_plugins() -> dict[str, Workflow]:
    """Load workflows from plugin packages via ``sase_xprompts`` entry points.

    Each entry point should reference a module whose package contains an
    ``xprompts/`` resource directory with ``.yml``/``.yaml`` files.

    Returns:
        Dictionary mapping workflow name to Workflow object.
    """
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
            if not (entry_name.endswith(".yml") or entry_name.endswith(".yaml")):
                continue
            try:
                text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, UnicodeDecodeError):
                continue

            # Write to a temp dir with the original filename so
            # _load_workflow_from_file derives the correct workflow name.
            import tempfile

            from sase.core.paths import get_sase_managed_tmpdir

            tmpdir = Path(
                tempfile.mkdtemp(dir=get_sase_managed_tmpdir("workflow-loader"))
            )
            tmp_path = tmpdir / entry_name
            try:
                tmp_path.write_text(text, encoding="utf-8")
                workflow = _load_workflow_from_file(tmp_path)
                if workflow:
                    source = f"plugin:{module.__name__}/{entry_name}"
                    workflows[workflow.name] = Workflow(
                        name=workflow.name,
                        inputs=workflow.inputs,
                        steps=workflow.steps,
                        source_path=source,
                        xprompts=workflow.xprompts,
                        wraps_all=workflow.wraps_all,
                        hidden=workflow.hidden,
                        tags=workflow.tags,
                        environment=workflow.environment,
                        description=workflow.description,
                        skill_name=workflow.skill_name,
                        memory_type=workflow.memory_type,
                        ref=workflow.ref,
                        ref_kind=workflow.ref_kind,
                        ref_sidecar_role=workflow.ref_sidecar_role,
                        ref_path_globs=workflow.ref_path_globs,
                        ref_shadowed_sources=workflow.ref_shadowed_sources,
                    )
            finally:
                tmp_path.unlink(missing_ok=True)
                tmpdir.rmdir()

    return workflows


def _load_workflows_from_project(project: str) -> dict[str, Workflow]:
    """Load workflows from a project-specific directory.

    Loads workflows from canonical ``~/sase/xprompts/{project}/`` and the
    legacy config-directory fallback, then namespaces them with the project
    name (e.g., bar.yml → foo/bar for project 'foo').

    Args:
        project: The project name to load workflows for.

    Returns:
        Dictionary mapping namespaced workflow name to Workflow object.
        Returns empty dict if directory doesn't exist.
    """
    workflows: dict[str, Workflow] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    ]
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for extension in ("*.yaml", "*.yml"):
            for workflow_file in project_dir.glob(extension):
                if not workflow_file.is_file():
                    continue
                workflow = _load_workflow_from_file(workflow_file)
                if workflow:
                    ns = _namespace_workflow(project, workflow)
                    workflows[ns.name] = ns
    return workflows


def _load_workflows_from_project_workspace(
    project: str,
    *,
    detected_project: str | None,
) -> dict[str, Workflow]:
    """Load workflows from the known primary workspace for *project*.

    This mirrors CWD-local workflow discovery for callers that are currently
    running from another directory but already know the target project name.
    """
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
    for xprompt_dir in project_dirs:
        if not xprompt_dir.is_dir():
            continue

        for extension in ("*.yml", "*.yaml"):
            for workflow_file in sorted(xprompt_dir.glob(extension)):
                if not workflow_file.is_file():
                    continue
                workflow = _load_workflow_from_file(workflow_file)
                if not workflow:
                    continue
                ns = _namespace_workflow(project, workflow)
                workflows.setdefault(ns.name, ns)

    return workflows


def get_all_workflows(project: str | None = None) -> dict[str, Workflow]:
    """Get all workflows from all sources, respecting priority order.

    When *project* is given (or auto-detected via ``detect_project()``),
    workflows from project-local sources (CWD xprompt directories) are
    namespaced with ``{project}/``. When the requested project is registered
    but is not the current checkout, its enabled primary workspace is also
    consulted through the project registry.

    The priority order follows the shared content-layout contract: canonical
    project and home directories precede their legacy fallbacks,
    project-specific home sources precede plugin/package resources, the
    registry-backed project copy fills in checkout-local content when CWD is
    elsewhere, and CWD/project filesystem sources retain the highest priority.

    Args:
        project: Optional project name.  When ``None``, the project is
            auto-detected via :func:`detect_project`.

    Returns:
        Dictionary mapping workflow name to Workflow object.
    """
    detected_project = detect_project()
    requested_project = project if project is not None else detected_project
    effective_project = canonical_xprompt_project(requested_project)

    all_workflows: dict[str, Workflow] = {}

    # Internal workflows (lowest priority)
    all_workflows.update(_load_workflows_from_internal())

    # Plugin workflows
    all_workflows.update(_load_workflows_from_plugins())

    # Project-specific workflows (if project provided)
    if effective_project:
        project_workflows = _load_workflows_from_project(effective_project)
        all_workflows.update(project_workflows)

        project_workspace_workflows = _load_workflows_from_project_workspace(
            effective_project,
            detected_project=detected_project,
        )
        all_workflows.update(project_workspace_workflows)

    # File-based workflows (highest priority) - already sorted
    file_workflows = _load_workflows_from_files(project=effective_project)
    all_workflows.update(file_workflows)

    return all_workflows
