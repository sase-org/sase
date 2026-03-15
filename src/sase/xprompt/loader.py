"""XPrompt discovery and loading from files and configuration."""

import functools
import importlib.resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sase.config import load_xprompts_by_source
from sase.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_xprompt_entries,
    parse_yaml_front_matter,
)
from .models import InputArg, XPrompt

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


@functools.cache
def detect_project() -> str | None:
    """Auto-detect the current project name from the workspace.

    Uses the ``workspace_name`` shell command.  The result is cached for
    the lifetime of the process so the subprocess only runs once.
    """
    try:
        from sase.sase_utils import run_shell_command

        result = run_shell_command("workspace_name", capture_output=True)
        if result.returncode != 0:
            return None
        name = result.stdout.strip()
        return name if name else None
    except Exception:
        return None


def _namespace_xprompt(project: str, xp: XPrompt) -> XPrompt:
    """Return a copy of *xp* with its name prefixed by ``{project}/``."""
    namespaced_name = f"{project}/{xp.name}"
    return XPrompt(
        name=namespaced_name,
        content=xp.content,
        inputs=xp.inputs,
        source_path=xp.source_path,
    )


def get_sase_package_xprompts_dir() -> Path:
    """Get the path to the internal sase xprompts directory.

    The built-in xprompts live at ``src/sase/xprompts/`` inside the package,
    so ``importlib.resources`` resolves them for both wheel and editable
    installs.
    """
    import importlib.resources

    candidate = Path(str(importlib.resources.files("sase").joinpath("xprompts")))
    if candidate.is_dir():
        return candidate

    log.warning(
        "Internal xprompts directory not found via importlib.resources('sase/xprompts')",
    )
    return candidate


def _load_xprompt_from_file(file_path: Path) -> XPrompt | None:
    """Load a single xprompt from a markdown file.

    Args:
        file_path: Path to the .md file.

    Returns:
        XPrompt object if successfully loaded, None otherwise.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return None

    front_matter, body = parse_yaml_front_matter(content)

    # Get name from front matter or fallback to filename
    if front_matter and "name" in front_matter:
        name = str(front_matter["name"])
    else:
        name = file_path.stem  # Filename without extension

    # Parse inputs if present
    inputs: list[InputArg] = []
    if front_matter and "input" in front_matter:
        inputs = parse_inputs_from_front_matter(front_matter["input"])

    return XPrompt(
        name=name,
        content=body,
        inputs=inputs,
        source_path=str(file_path),
    )


def get_xprompt_search_paths() -> list[Path]:
    """Get the ordered list of directories to search for xprompt files.

    Priority order (first wins on name conflict):
    1. .xprompts/*.md (CWD, hidden)
    2. xprompts/*.md (CWD, non-hidden)
    3. ~/.xprompts/*.md (home, hidden)
    4. ~/xprompts/*.md (home, non-hidden)
    5. (config is handled separately)
    6. <sase_package>/xprompts/*.md (internal)

    Returns:
        List of directory paths to search, in priority order.
    """
    cwd = Path.cwd()
    home = Path.home()

    paths = [
        cwd / ".xprompts",
        cwd / "xprompts",
        home / ".xprompts",
        home / "xprompts",
    ]

    return paths


def _load_xprompts_from_files(project: str | None = None) -> dict[str, XPrompt]:
    """Load xprompts from file system locations.

    Scans each search directory for ``.md`` files. Earlier directories in the
    search path take precedence over later ones.

    When *project* is given, xprompts from CWD directories (``.xprompts/``,
    ``xprompts/``) are namespaced with ``{project}/``.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
        Earlier priority sources override later ones.
    """
    cwd = Path.cwd()
    cwd_dirs = {cwd / ".xprompts", cwd / "xprompts"}
    search_paths = get_xprompt_search_paths()
    xprompts: dict[str, XPrompt] = {}

    # Process directories in reverse priority order (lowest first),
    # so higher-priority directories overwrite.
    for search_dir in reversed(search_paths):
        if not search_dir.is_dir():
            continue

        is_local = search_dir in cwd_dirs
        for md_file in search_dir.glob("*.md"):
            if md_file.is_file():
                xprompt = _load_xprompt_from_file(md_file)
                if xprompt:
                    if project and is_local:
                        xprompt = _namespace_xprompt(project, xprompt)
                    xprompts[xprompt.name] = xprompt

    return xprompts


def _load_xprompts_from_config(project: str | None = None) -> dict[str, XPrompt]:
    """Load xprompts from config sources with proper source attribution.

    Loads xprompts from each config source separately (built-in defaults,
    plugin default configs, user sase.yml, overlay files) so that each
    xprompt gets the correct source attribution instead of all being
    tagged as ``"config"``.

    When *project* is given, xprompts from the local ``sase.yml``
    (``local_config`` source) are namespaced with ``{project}/``.

    Priority order (within config sources, later overrides earlier):
    1. Built-in ``default_config.yml``
    2. Plugin ``default_config.yml`` files
    3. User ``sase.yml``
    4. Overlay ``sase_*.yml`` files
    5. Local ``./sase.yml``

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    all_xprompts: dict[str, XPrompt] = {}

    for source_label, xprompts_data in load_xprompts_by_source():
        parsed = parse_xprompt_entries(xprompts_data, source_label)
        if project and source_label == "local_config":
            parsed = {
                f"{project}/{name}": _namespace_xprompt(project, xp)
                for name, xp in parsed.items()
            }
        all_xprompts.update(parsed)

    return all_xprompts


def _load_xprompts_from_internal() -> dict[str, XPrompt]:
    """Load xprompts from the internal sase package xprompts directory.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    internal_dir = get_sase_package_xprompts_dir()

    if not internal_dir.is_dir():
        return {}

    xprompts: dict[str, XPrompt] = {}
    for md_file in internal_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = _load_xprompt_from_file(md_file)
            if xprompt:
                xprompts[xprompt.name] = xprompt

    return xprompts


def _load_xprompts_from_plugins() -> dict[str, XPrompt]:
    """Load xprompts from plugin packages via ``sase_xprompts`` entry points.

    Each entry point should reference a module whose package contains an
    ``xprompts/`` resource directory with ``.md`` files.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    if is_plugin_disabled("XPROMPTS"):
        return {}

    xprompts: dict[str, XPrompt] = {}
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
            if not entry.name.endswith(".md"):  # type: ignore[union-attr]
                continue
            try:
                text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, UnicodeDecodeError):
                continue

            front_matter, body = parse_yaml_front_matter(text)
            name = entry.name.removesuffix(".md")  # type: ignore[union-attr]
            if front_matter and "name" in front_matter:
                name = str(front_matter["name"])

            inputs: list[InputArg] = []
            if front_matter and "input" in front_matter:
                inputs = parse_inputs_from_front_matter(front_matter["input"])

            source = f"plugin:{module.__name__}/{entry.name}"  # type: ignore[union-attr]
            xprompts[name] = XPrompt(
                name=name,
                content=body,
                inputs=inputs,
                source_path=source,
            )

    return xprompts


def _load_xprompts_from_project(project: str) -> dict[str, XPrompt]:
    """Load xprompts from a project-specific directory.

    Loads xprompts from ~/.config/sase/xprompts/{project}/*.md and namespaces
    them with the project name (e.g., bar.md → foo/bar for project 'foo').

    Args:
        project: The project name to load xprompts for.

    Returns:
        Dictionary mapping namespaced xprompt name to XPrompt object.
        Returns empty dict if directory doesn't exist.
    """
    project_dir = Path.home() / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    xprompts: dict[str, XPrompt] = {}

    for md_file in project_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = _load_xprompt_from_file(md_file)
            if xprompt:
                ns = _namespace_xprompt(project, xprompt)
                xprompts[ns.name] = ns

    return xprompts


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
    8. <sase_package>/xprompts/*.md (internal)

    Args:
        project: Optional project name.  When ``None``, the project is
            auto-detected via :func:`detect_project`.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    effective_project = project if project is not None else detect_project()

    # Start with lowest priority and let higher priority override
    all_xprompts: dict[str, XPrompt] = {}

    # 8. Internal xprompts (lowest priority)
    all_xprompts.update(_load_xprompts_from_internal())

    # 7. Plugin xprompts
    all_xprompts.update(_load_xprompts_from_plugins())

    # 6. Config-based xprompts
    config_xprompts = _load_xprompts_from_config(project=effective_project)
    all_xprompts.update(config_xprompts)

    # 5. Project-specific xprompts (if project provided)
    if effective_project:
        project_xprompts = _load_xprompts_from_project(effective_project)
        all_xprompts.update(project_xprompts)

    # 1-4. File-based xprompts (highest priority) - already sorted
    file_xprompts = _load_xprompts_from_files(project=effective_project)
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
