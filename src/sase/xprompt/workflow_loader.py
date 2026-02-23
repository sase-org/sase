"""Workflow discovery and loading from YAML files."""

import importlib.resources
import logging
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from sase.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader import (
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
    parse_xprompt_entries,
)
from sase.xprompt.models import UNSET, InputArg, InputType
from sase.xprompt.workflow_loader_parse import (
    _parse_workflow_step as _parse_workflow_step,
    parse_workflow_inputs,
    validate_workflow_variables,
)
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)

log = logging.getLogger(__name__)


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
    except (OSError, yaml.YAMLError):
        return None

    if not isinstance(data, dict):
        return None

    # Derive workflow name from filename
    name = file_path.stem

    # Parse wraps_all
    wraps_all = bool(data.get("wraps_all", False))

    # Parse inputs
    inputs = parse_workflow_inputs(data.get("input"))

    # Parse workflow-local xprompts
    xprompts_data = data.get("xprompts")
    parsed_xprompts = (
        parse_xprompt_entries(xprompts_data, str(file_path))
        if isinstance(xprompts_data, dict)
        else {}
    )

    # Parse steps
    steps_data = data.get("steps", [])
    if not isinstance(steps_data, list):
        return None

    steps: list[WorkflowStep] = []
    try:
        for step_index, step_data in enumerate(steps_data):
            if not isinstance(step_data, dict):
                continue
            step = _parse_workflow_step(step_data, step_index)
            steps.append(step)

        # Validate at most one prompt_part step per workflow
        prompt_part_count = sum(1 for step in steps if step.is_prompt_part_step())
        if prompt_part_count > 1:
            raise WorkflowValidationError(
                f"Workflow '{name}' has {prompt_part_count} prompt_part steps, "
                "but at most one is allowed"
            )
    except WorkflowValidationError:
        return None

    if not steps:
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
        source_path=str(file_path),
        xprompts=parsed_xprompts,
        wraps_all=wraps_all,
    )

    # Validate variable usage
    try:
        validate_workflow_variables(workflow)
    except WorkflowValidationError:
        # For now, just return the workflow even if validation fails
        # The error will be raised at runtime with more context
        pass

    return workflow


def _discover_workflow_files() -> list[tuple[Path, int]]:
    """Find all workflow files in search paths with priority info.

    Returns:
        List of (file_path, priority) tuples, where lower priority wins.
    """
    search_paths = get_xprompt_search_paths()
    results: list[tuple[Path, int]] = []

    for priority, search_dir in enumerate(search_paths):
        if not search_dir.is_dir():
            continue

        for yml_file in search_dir.glob("*.yml"):
            if yml_file.is_file():
                results.append((yml_file, priority))

        for yaml_file in search_dir.glob("*.yaml"):
            if yaml_file.is_file():
                results.append((yaml_file, priority))

    return results


def _load_workflows_from_files() -> dict[str, Workflow]:
    """Load workflows from file system locations.

    Returns:
        Dictionary mapping workflow name to Workflow object.
        Earlier priority sources override later ones.
    """
    discovered = _discover_workflow_files()

    # Sort by priority (lower is higher priority)
    discovered.sort(key=lambda x: x[1])

    workflows: dict[str, Workflow] = {}
    for file_path, _ in discovered:
        workflow = _load_workflow_from_file(file_path)
        if workflow and workflow.name not in workflows:
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

            tmpdir = Path(tempfile.mkdtemp())
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
                    )
            finally:
                tmp_path.unlink(missing_ok=True)
                tmpdir.rmdir()

    return workflows


def _load_workflows_from_project(project: str) -> dict[str, Workflow]:
    """Load workflows from a project-specific directory.

    Loads workflows from ~/.config/sase/xprompts/{project}/*.yml and namespaces
    them with the project name (e.g., bar.yml → foo/bar for project 'foo').

    Args:
        project: The project name to load workflows for.

    Returns:
        Dictionary mapping namespaced workflow name to Workflow object.
        Returns empty dict if directory doesn't exist.
    """
    project_dir = Path.home() / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    workflows: dict[str, Workflow] = {}
    for yml_file in project_dir.glob("*.yml"):
        if yml_file.is_file():
            workflow = _load_workflow_from_file(yml_file)
            if workflow:
                # Use file stem for project workflows to avoid duplicate prefixes
                # (the YAML's name field might already include the project prefix)
                base_name = yml_file.stem
                namespaced_name = f"{project}/{base_name}"
                workflows[namespaced_name] = Workflow(
                    name=namespaced_name,
                    inputs=workflow.inputs,
                    steps=workflow.steps,
                    source_path=workflow.source_path,
                    xprompts=workflow.xprompts,
                    wraps_all=workflow.wraps_all,
                )

    for yaml_file in project_dir.glob("*.yaml"):
        if yaml_file.is_file():
            workflow = _load_workflow_from_file(yaml_file)
            if workflow:
                # Use file stem for project workflows to avoid duplicate prefixes
                # (the YAML's name field might already include the project prefix)
                base_name = yaml_file.stem
                namespaced_name = f"{project}/{base_name}"
                if namespaced_name not in workflows:  # .yml takes precedence
                    workflows[namespaced_name] = Workflow(
                        name=namespaced_name,
                        inputs=workflow.inputs,
                        steps=workflow.steps,
                        source_path=workflow.source_path,
                        xprompts=workflow.xprompts,
                        wraps_all=workflow.wraps_all,
                    )
    return workflows


def get_all_workflows(project: str | None = None) -> dict[str, Workflow]:
    """Get all workflows from all sources, respecting priority order.

    Priority order (first wins on name conflict):
    1. .xprompts/*.yml (CWD, hidden)
    2. xprompts/*.yml (CWD, non-hidden)
    3. ~/.xprompts/*.yml (home, hidden)
    4. ~/xprompts/*.yml (home, non-hidden)
    5. ~/.config/sase/xprompts/{project}/*.yml (project-specific, if project given)
    6. Plugin packages (via sase_xprompts entry points)
    7. <sase_package>/xprompts/*.yml (internal)

    Args:
        project: Optional project name to include project-specific workflows.

    Returns:
        Dictionary mapping workflow name to Workflow object.
    """
    all_workflows: dict[str, Workflow] = {}

    # 7. Internal workflows (lowest priority)
    all_workflows.update(_load_workflows_from_internal())

    # 6. Plugin workflows
    all_workflows.update(_load_workflows_from_plugins())

    # 5. Project-specific workflows (if project provided)
    if project:
        project_workflows = _load_workflows_from_project(project)
        all_workflows.update(project_workflows)

    # File-based workflows (highest priority) - already sorted
    file_workflows = _load_workflows_from_files()
    all_workflows.update(file_workflows)

    return all_workflows
