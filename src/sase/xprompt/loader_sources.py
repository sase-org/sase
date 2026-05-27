"""Per-source xprompt loaders (filesystem, config, plugins, projects)."""

import importlib.resources
import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config import load_xprompts_by_source
from sase.core.paths import sase_projects_dir
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_xprompt_entries,
    parse_yaml_front_matter,
)
from .models import InputArg, XPrompt
from .tags import parse_tags

log = logging.getLogger(__name__)


def namespace_xprompt(project: str, xp: XPrompt) -> XPrompt:
    """Return a copy of *xp* with its name prefixed by ``{project}/``."""
    namespaced_name = f"{project}/{xp.name}"
    return XPrompt(
        name=namespaced_name,
        content=xp.content,
        inputs=xp.inputs,
        source_path=xp.source_path,
        tags=xp.tags,
        snippet=xp.snippet,
        description=xp.description,
        skill=xp.skill,
        keywords=xp.keywords,
    )


def load_xprompt_from_file(file_path: Path) -> XPrompt | None:
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

    # Parse tags if present
    tags = parse_tags(front_matter.get("tags")) if front_matter else frozenset()

    # Parse snippet field if present
    snippet = front_matter.get("snippet") if front_matter else None

    # Parse description and skill fields if present
    description = front_matter.get("description") if front_matter else None
    skill = front_matter.get("skill") if front_matter else None

    # Parse keywords if present
    keywords = front_matter.get("keywords", []) if front_matter else []

    return XPrompt(
        name=name,
        content=body,
        inputs=inputs,
        source_path=str(file_path),
        tags=tags,
        snippet=snippet,
        description=description,
        skill=skill,
        keywords=keywords,
    )


def get_sase_package_xprompts_dir() -> Path:
    """Get the path to the internal sase xprompts directory.

    The built-in xprompts live at ``src/sase/xprompts/`` inside the package,
    so ``importlib.resources`` resolves them for both wheel and editable
    installs.
    """
    candidate = Path(str(importlib.resources.files("sase").joinpath("xprompts")))
    if candidate.is_dir():
        return candidate

    log.warning(
        "Internal xprompts directory not found via importlib.resources('sase/xprompts')",
    )
    return candidate


def get_sase_package_default_xprompts_dir() -> Path:
    """Get the path to the internal sase default markdown xprompts directory.

    Default file-backed xprompts live at ``src/sase/default_xprompts/`` inside
    the package, so ``importlib.resources`` resolves them for both wheel and
    editable installs.
    """
    candidate = Path(
        str(importlib.resources.files("sase").joinpath("default_xprompts"))
    )
    if candidate.is_dir():
        return candidate

    log.warning(
        "Default xprompts directory not found via "
        "importlib.resources('sase/default_xprompts')",
    )
    return candidate


def get_xprompt_search_paths() -> list[Path]:
    """Get the ordered list of directories to search for xprompt files.

    Priority order (first wins on name conflict):
    1. .xprompts/*.md (CWD, hidden)
    2. xprompts/*.md (CWD, non-hidden)
    3. ~/.xprompts/*.md (home, hidden)
    4. ~/xprompts/*.md (home, non-hidden)
    5. (config is handled separately)
    6. <sase_package>/default_xprompts/*.md (default built-ins, separate)
    7. <sase_package>/xprompts/*.md (internal, separate)

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


def load_xprompts_from_files(project: str | None = None) -> dict[str, XPrompt]:
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
                xprompt = load_xprompt_from_file(md_file)
                if xprompt:
                    if project and is_local:
                        xprompt = namespace_xprompt(project, xprompt)
                    xprompts[xprompt.name] = xprompt

    return xprompts


def load_xprompts_from_config(project: str | None = None) -> dict[str, XPrompt]:
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
                f"{project}/{name}": namespace_xprompt(project, xp)
                for name, xp in parsed.items()
            }
        all_xprompts.update(parsed)

    return all_xprompts


def load_xprompts_from_internal() -> dict[str, XPrompt]:
    """Load xprompts from the internal sase package xprompts directory.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    internal_dir = get_sase_package_xprompts_dir()

    if not internal_dir.is_dir():
        return {}

    skill_dir = internal_dir / "skills"
    md_files = [*sorted(internal_dir.glob("*.md"))]
    if skill_dir.is_dir():
        md_files.extend(sorted(skill_dir.glob("*.md")))

    xprompts: dict[str, XPrompt] = {}
    for md_file in md_files:
        if md_file.is_file():
            xprompt = load_xprompt_from_file(md_file)
            if xprompt and xprompt.name not in xprompts:
                xprompts[xprompt.name] = xprompt

    return xprompts


def load_xprompts_from_default_files() -> dict[str, XPrompt]:
    """Load xprompts from the internal sase package default_xprompts directory.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    default_dir = get_sase_package_default_xprompts_dir()

    if not default_dir.is_dir():
        return {}

    xprompts: dict[str, XPrompt] = {}
    for md_file in default_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = load_xprompt_from_file(md_file)
            if xprompt:
                xprompts[xprompt.name] = xprompt

    return xprompts


def load_xprompts_from_plugins() -> dict[str, XPrompt]:
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

            tags = parse_tags(front_matter.get("tags")) if front_matter else frozenset()

            snippet = front_matter.get("snippet") if front_matter else None
            description = front_matter.get("description") if front_matter else None
            skill = front_matter.get("skill") if front_matter else None
            keywords = front_matter.get("keywords", []) if front_matter else []
            source = f"plugin:{module.__name__}/{entry.name}"  # type: ignore[union-attr]
            xprompts[name] = XPrompt(
                name=name,
                content=body,
                inputs=inputs,
                source_path=source,
                tags=tags,
                snippet=snippet,
                description=description,
                skill=skill,
                keywords=keywords,
            )

    return xprompts


def load_xprompts_from_project(project: str) -> dict[str, XPrompt]:
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
            xprompt = load_xprompt_from_file(md_file)
            if xprompt:
                ns = namespace_xprompt(project, xprompt)
                xprompts[ns.name] = ns

    return xprompts


def get_known_project_workspaces() -> dict[str, Path]:
    """Enumerate all known projects and their primary workspace directories.

    Parses project spec files at ``~/.sase/projects/<name>/<name>.sase``
    (preferring the canonical ``.sase`` extension; falling back to legacy
    ``.gp``) for ``WORKSPACE_DIR:`` lines.

    Returns:
        Mapping of project name to workspace directory path.
    """
    from sase.ace.changespec.project_spec_path import (
        project_spec_basename,
        PROJECT_SPEC_EXTENSIONS,
    )

    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return {}

    result: dict[str, Path] = {}
    # Prefer canonical .sase entries; only fall back to legacy .gp where the
    # canonical sibling is absent so a single project does not get listed twice.
    seen_projects: set[str] = set()
    for ext in PROJECT_SPEC_EXTENSIONS:
        for spec_file in sorted(projects_dir.glob(f"*/*{ext}")):
            if spec_file.name.endswith(f"-archive{ext}"):
                continue
            project_name = project_spec_basename(str(spec_file))
            if project_name in seen_projects:
                continue
            try:
                text = spec_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                if line.startswith("WORKSPACE_DIR:"):
                    ws_dir = line.removeprefix("WORKSPACE_DIR:").strip()
                    ws_path = Path(ws_dir)
                    if ws_path.is_dir():
                        result[project_name] = ws_path
                        seen_projects.add(project_name)
                    break

    return result


def load_project_local_xprompts(
    workspace_dir: Path, project: str
) -> dict[str, XPrompt]:
    """Load xprompts from a project's ``sase.yml`` file.

    Reads ``<workspace_dir>/sase.yml`` directly, bypassing the
    ``_include_local_config`` flag.  Returns xprompts namespaced with
    ``{project}/``.
    """
    sase_yml = workspace_dir / "sase.yml"
    if not sase_yml.is_file():
        return {}

    try:
        with open(sase_yml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        log.debug("Failed to load project sase.yml: %s", sase_yml, exc_info=True)
        return {}

    if not isinstance(data, dict):
        return {}

    xprompts_data: dict[str, Any] = data.get("xprompts", {})
    if not isinstance(xprompts_data, dict) or not xprompts_data:
        return {}

    source_label = f"project_local_config:{project}"
    parsed = parse_xprompt_entries(xprompts_data, source_label)
    return {
        f"{project}/{name}": namespace_xprompt(project, xp)
        for name, xp in parsed.items()
    }
