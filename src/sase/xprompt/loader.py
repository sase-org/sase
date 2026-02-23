"""XPrompt discovery and loading from files and configuration."""

import importlib.resources
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from sase.config import load_merged_config
from sase.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_xprompt_entries,
    parse_yaml_front_matter,
)
from .models import InputArg, XPrompt

log = logging.getLogger(__name__)

XPROMPTS_CONFIG_BASENAMES = ("xprompts.yml", "xprompts.yaml")

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import Workflow


def get_sase_package_xprompts_dir() -> Path:
    """Get the path to the internal sase xprompts directory.

    Tries multiple resolution strategies to handle different install layouts:
    1. ``importlib.resources`` — works for wheel installs where xprompts are
       shipped as package data via ``force-include`` in ``pyproject.toml``.
    2. ``__file__`` path traversal — works for editable (``pip install -e``)
       installs where the source tree is used directly.
    3. Ancestor walk — fallback for unusual directory layouts (e.g. extra
       nesting). Uses ``workflow.schema.json`` as a sentinel to avoid false
       positives from unrelated ``xprompts/`` directories.
    """
    import importlib.resources

    # Method 1: importlib.resources (wheel installs with force-include)
    try:
        candidate_resource = importlib.resources.files("sase").joinpath("_xprompts")
        candidate = Path(str(candidate_resource))
        if candidate.is_dir():
            return candidate
    except Exception:
        pass

    # Method 2: __file__ path traversal (editable installs)
    # This file is in src/sase/xprompt/loader.py
    # xprompts dir is at <repo_root>/xprompts/
    loader_path = Path(__file__).resolve()
    repo_root = loader_path.parent.parent.parent.parent
    candidate = repo_root / "xprompts"
    if candidate.is_dir():
        return candidate

    # Method 3: Walk up from __file__ looking for xprompts/ with sentinel
    current = loader_path.parent
    for _ in range(8):
        check = current / "xprompts"
        if check.is_dir() and (check / "workflow.schema.json").is_file():
            return check
        parent = current.parent
        if parent == current:
            break
        current = parent

    log.warning(
        "Internal xprompts directory not found. "
        "Tried importlib.resources('sase/_xprompts') and path traversal from %s",
        loader_path,
    )
    return repo_root / "xprompts"


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


def _load_xprompts_from_directory_config(search_dir: Path) -> dict[str, XPrompt]:
    """Load xprompt entries from an xprompts.yml/yaml config file in a directory.

    Args:
        search_dir: Directory to look for xprompts.yml or xprompts.yaml.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    for basename in XPROMPTS_CONFIG_BASENAMES:
        config_path = search_dir / basename
        if not config_path.is_file():
            continue

        try:
            content = config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
        except (OSError, yaml.YAMLError):
            log.warning("Failed to parse %s", config_path)
            return {}

        if not isinstance(data, dict):
            log.warning("Expected dict in %s, got %s", config_path, type(data).__name__)
            return {}

        return parse_xprompt_entries(data, str(config_path))

    return {}


def _load_xprompts_from_files() -> dict[str, XPrompt]:
    """Load xprompts from file system locations.

    Within each directory, xprompts.yml entries are loaded first, then .md files
    (which override config entries within the same directory). Earlier directories
    in the search path take precedence over later ones.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
        Earlier priority sources override later ones.
    """
    search_paths = get_xprompt_search_paths()
    xprompts: dict[str, XPrompt] = {}

    # Process directories in reverse priority order (lowest first),
    # so higher-priority directories overwrite.
    for search_dir in reversed(search_paths):
        if not search_dir.is_dir():
            continue

        # Load config-file entries first
        config_entries = _load_xprompts_from_directory_config(search_dir)
        xprompts.update(config_entries)

        # .md files override config entries within the same directory
        for md_file in search_dir.glob("*.md"):
            if md_file.is_file():
                xprompt = _load_xprompt_from_file(md_file)
                if xprompt:
                    xprompts[xprompt.name] = xprompt

    return xprompts


def _load_xprompts_from_config() -> dict[str, XPrompt]:
    """Load xprompts from sase.yml configuration file.

    Supports both simple string format and structured dict format:

    Simple format:
        xprompts:
          foo: "Content here"

    Structured format (with inputs):
        xprompts:
          bar:
            input: {name: word, count: {type: int, default: 0}}
            content: "Hello {{ name }}, count is {{ count }}"
            output: {result: text}  # optional

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    data = load_merged_config()

    if not isinstance(data, dict):
        return {}

    config_data = data.get("xprompts")
    if not isinstance(config_data, dict):
        return {}

    return parse_xprompt_entries(config_data, "config")


def _load_xprompts_from_internal() -> dict[str, XPrompt]:
    """Load xprompts from the internal sase package xprompts directory.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    internal_dir = get_sase_package_xprompts_dir()

    if not internal_dir.is_dir():
        return {}

    # Load from xprompts.yml first, then .md files override
    xprompts = _load_xprompts_from_directory_config(internal_dir)

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

    Loads xprompts from ~/.config/sase/xprompts/{project}/ (both xprompts.yml
    entries and *.md files) and namespaces them with the project name
    (e.g., bar.md → foo/bar for project 'foo').

    Args:
        project: The project name to load xprompts for.

    Returns:
        Dictionary mapping namespaced xprompt name to XPrompt object.
        Returns empty dict if directory doesn't exist.
    """
    project_dir = Path.home() / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    def _namespace(name: str, xp: XPrompt) -> XPrompt:
        namespaced_name = f"{project}/{name}"
        return XPrompt(
            name=namespaced_name,
            content=xp.content,
            inputs=xp.inputs,
            source_path=xp.source_path,
        )

    xprompts: dict[str, XPrompt] = {}

    # Load from xprompts.yml first
    for name, xp in _load_xprompts_from_directory_config(project_dir).items():
        xprompts[f"{project}/{name}"] = _namespace(name, xp)

    # .md files override config entries
    for md_file in project_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = _load_xprompt_from_file(md_file)
            if xprompt:
                namespaced_name = f"{project}/{xprompt.name}"
                xprompts[namespaced_name] = _namespace(xprompt.name, xprompt)

    return xprompts


def get_all_xprompts(project: str | None = None) -> dict[str, XPrompt]:
    """Get all xprompts from all sources, respecting priority order.

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
        project: Optional project name to include project-specific xprompts.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    # Start with lowest priority and let higher priority override
    all_xprompts: dict[str, XPrompt] = {}

    # 8. Internal xprompts (lowest priority)
    all_xprompts.update(_load_xprompts_from_internal())

    # 7. Plugin xprompts
    all_xprompts.update(_load_xprompts_from_plugins())

    # 6. Config-based xprompts
    config_xprompts = _load_xprompts_from_config()
    all_xprompts.update(config_xprompts)

    # 5. Project-specific xprompts (if project provided)
    if project:
        project_xprompts = _load_xprompts_from_project(project)
        all_xprompts.update(project_xprompts)

    # 1-4. File-based xprompts (highest priority) - already sorted
    file_xprompts = _load_xprompts_from_files()
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
