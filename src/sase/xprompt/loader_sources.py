"""Per-source xprompt loaders (filesystem, config, plugins, projects)."""

import importlib.resources
import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config import load_xprompts_by_source
from sase.content_layout import (
    resolve_project_config_read_path,
    resolve_xprompt_file_sources,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
)
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_local_xprompt_entries,
    parse_xprompt_entries,
    parse_yaml_front_matter,
    parse_yaml_front_matter_with_error,
)
from .load_issues import record_load_issue
from .loader_skills import (
    plugin_skill_destination,
    reject_misplaced_skill,
    skill_destination_for_xprompt_dir,
)
from .models import InputArg, XPrompt
from .reserved_namespaces import reject_reserved_memory_namespace
from .tags import parse_tags

log = logging.getLogger(__name__)


def namespace_xprompt(project: str, xp: XPrompt) -> XPrompt:
    """Return a copy of *xp* with its name prefixed by ``{project}/``.

    Skills are namespaced by :func:`sase.content_layout.skill_reference_name`
    instead, but ``skill_name`` is carried through so a copy never loses the
    provider-visible name.
    """
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
        skill_name=xp.skill_name,
        log_skill_use=xp.log_skill_use,
        local_xprompts=xp.local_xprompts,
        memory_type=xp.memory_type,
    )


def _load_ordinary_xprompts_from_dir(directory: Path) -> Iterator[XPrompt]:
    """Yield loadable non-skill definitions from an ordinary xprompt dir.

    A ``skill:`` declaration here is rejected with a migration diagnostic
    naming the scope's canonical ``sase/skills/`` directory, so a misplaced
    skill is reported rather than loaded under its bare name.
    """
    destination = skill_destination_for_xprompt_dir(directory)
    for md_file in sorted(directory.glob("*.md")):
        if not md_file.is_file():
            continue
        xprompt = load_xprompt_from_file(md_file)
        if xprompt is None:
            continue
        if reject_reserved_memory_namespace(xprompt.name, source=md_file):
            continue
        if reject_misplaced_skill(xprompt, source=md_file, migrate_to=destination):
            continue
        yield xprompt


def _parse_markdown_local_xprompts(
    front_matter: dict[str, Any] | None, source_path: str
) -> dict[str, XPrompt]:
    if not front_matter:
        return {}
    xprompts_data = front_matter.get("xprompts")
    if not isinstance(xprompts_data, dict):
        return {}
    return parse_local_xprompt_entries(xprompts_data, source_path)


def load_xprompt_from_file(file_path: Path) -> XPrompt | None:
    """Load a single xprompt from a markdown file.

    Args:
        file_path: Path to the .md file.

    Returns:
        XPrompt object if successfully loaded, None otherwise.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        record_load_issue(file_path, exc, kind="frontmatter")
        return None

    front_matter, body, frontmatter_error = parse_yaml_front_matter_with_error(content)
    if frontmatter_error is not None:
        record_load_issue(
            file_path,
            f"invalid YAML frontmatter (treated as plain body): {frontmatter_error}",
            kind="frontmatter",
        )

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
    log_skill_use = front_matter.get("log_skill_use", True) if front_matter else True

    local_xprompts = _parse_markdown_local_xprompts(front_matter, str(file_path))

    if reject_reserved_memory_namespace(name, source=file_path):
        return None

    return XPrompt(
        name=name,
        content=body,
        inputs=inputs,
        source_path=str(file_path),
        tags=tags,
        snippet=snippet,
        description=description,
        skill=skill,
        log_skill_use=log_skill_use,
        local_xprompts=local_xprompts,
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


def get_xprompt_search_paths(
    project: str | None = None,
    *,
    project_root: Path | None = None,
) -> list[Path]:
    """Get the ordered list of directories to search for xprompt files.

    The Rust content-layout contract owns the first-wins order: canonical
    project, legacy project, canonical home, legacy home, project-specific
    home, and package filesystem sources. Config and plugin-only entries are
    handled by their dedicated loaders.

    Returns:
        List of directory paths to search, in priority order.
    """
    return [
        source.path
        for source in resolve_xprompt_file_sources(
            project_root=project_root,
            project=project,
        )
        if source.path is not None
    ]


def load_xprompts_from_files(project: str | None = None) -> dict[str, XPrompt]:
    """Load xprompts from file system locations.

    Scans each search directory for ``.md`` files. Earlier directories in the
    search path take precedence over later ones.

    When *project* is given, xprompts from project directories (canonical
    ``sase/xprompts/`` and legacy fallbacks) are namespaced with
    ``{project}/``.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
        Earlier priority sources override later ones.
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
    xprompts: dict[str, XPrompt] = {}

    # Process directories in reverse priority order (lowest first),
    # so higher-priority directories overwrite.
    for search_dir in reversed(search_paths):
        if not search_dir.is_dir():
            continue

        is_local = search_dir in namespaced_dirs
        for xprompt in _load_ordinary_xprompts_from_dir(search_dir):
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

    When *project* is given, xprompts from the local ``sase/sase.yml``
    (``local_config`` source) are namespaced with ``{project}/``.

    Priority order (within config sources, later overrides earlier):
    1. Built-in ``default_config.yml``
    2. Plugin ``default_config.yml`` files
    3. User ``sase.yml``
    4. Overlay ``sase_*.yml`` files
    5. Local ``sase/sase.yml`` (root ``sase.yml`` is a legacy fallback)

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

    xprompts: dict[str, XPrompt] = {}
    for xprompt in _load_ordinary_xprompts_from_dir(internal_dir):
        if xprompt.name not in xprompts:
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

    return {
        xprompt.name: xprompt
        for xprompt in _load_ordinary_xprompts_from_dir(default_dir)
    }


def load_plugin_markdown_xprompts(
    module: Any, resource_dir: str
) -> Iterator[tuple[str, XPrompt]]:
    """Yield ``(source, xprompt)`` for one plugin resource directory.

    Skill placement is *not* applied here: ``xprompts/`` and ``skills/`` are
    sibling resource directories parsed identically, and each caller applies
    the rule for the directory it asked for.
    """
    try:
        resource = importlib.resources.files(module).joinpath(resource_dir)
    except (TypeError, AttributeError):
        return

    try:
        entries = list(resource.iterdir())  # type: ignore[union-attr]
    except (FileNotFoundError, OSError, TypeError, NotADirectoryError):
        return

    for entry in sorted(entries, key=lambda item: item.name):  # type: ignore[union-attr]
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
        source = f"plugin:{module.__name__}/{entry.name}"  # type: ignore[union-attr]
        yield (
            source,
            XPrompt(
                name=name,
                content=body,
                inputs=inputs,
                source_path=source,
                tags=tags,
                snippet=front_matter.get("snippet") if front_matter else None,
                description=(front_matter.get("description") if front_matter else None),
                skill=front_matter.get("skill") if front_matter else None,
                log_skill_use=(
                    front_matter.get("log_skill_use", True) if front_matter else True
                ),
                local_xprompts=_parse_markdown_local_xprompts(front_matter, source),
            ),
        )


def load_xprompts_from_plugins() -> dict[str, XPrompt]:
    """Load xprompts from plugin packages via ``sase_xprompts`` entry points.

    Each entry point should reference a module whose package contains an
    ``xprompts/`` resource directory with ``.md`` files. Plugin skills live in
    a sibling ``skills/`` resource directory instead, so a ``skill:``
    declaration here is rejected with that migration destination.

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    if is_plugin_disabled("XPROMPTS"):
        return {}

    xprompts: dict[str, XPrompt] = {}
    for module in discover_plugin_resources("sase_xprompts"):
        for source, xprompt in load_plugin_markdown_xprompts(module, "xprompts"):
            if reject_reserved_memory_namespace(xprompt.name, source=source):
                continue
            if reject_misplaced_skill(
                xprompt,
                source=source,
                migrate_to=plugin_skill_destination(),
            ):
                continue
            xprompts[xprompt.name] = xprompt

    return xprompts


def load_xprompts_from_project(project: str) -> dict[str, XPrompt]:
    """Load xprompts from a project-specific directory.

    Loads xprompts from canonical ``~/sase/xprompts/{project}/`` and the
    legacy config-directory fallback, then namespaces them with the project
    name (e.g., bar.md → foo/bar for project 'foo').

    Args:
        project: The project name to load xprompts for.

    Returns:
        Dictionary mapping namespaced xprompt name to XPrompt object.
        Returns empty dict if directory doesn't exist.
    """
    xprompts: dict[str, XPrompt] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    ]
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for xprompt in _load_ordinary_xprompts_from_dir(project_dir):
            ns = namespace_xprompt(project, xprompt)
            xprompts[ns.name] = ns

    return xprompts


def _project_ref_candidates(ref: str) -> tuple[str, ...]:
    candidates = [ref]
    if "/" in ref:
        candidates.append(ref.rsplit("/", 1)[-1])
    return tuple(dict.fromkeys(candidates))


def get_project_lifecycle_record(project: str) -> ProjectRecordWire | None:
    """Return the lifecycle record for *project*, including hidden projects."""
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return None
    for record in list_project_records(projects_dir, "all", include_home=False):
        if record.project_name == project:
            return record
    return None


def inactive_project_message_for_ref(ref: str) -> str | None:
    """Return a launch-blocking message when *ref* points at a disabled project."""
    for candidate in _project_ref_candidates(ref):
        record = get_project_lifecycle_record(candidate)
        if record is None or not is_disabled_project_lifecycle_state(record.state):
            continue
        return (
            f"project '{record.project_name}' is {record.state}; run "
            f"'sase project enable {record.project_name}' before launching work"
        )
    return None


def get_known_project_workspaces(
    include_states: Sequence[str] | str = ("enabled",),
) -> dict[str, Path]:
    """Enumerate lifecycle-selected projects and their primary workspaces.

    Normal callers get enabled projects only. Management/history callers can
    pass ``"all"`` or a concrete state list when hidden projects are
    intentionally in scope.

    Returns:
        Mapping of project name to workspace directory path.
    """
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return {}

    result: dict[str, Path] = {}
    for record in list_project_records(
        projects_dir,
        include_states,
        include_home=False,
    ):
        if not record.workspace_dir:
            continue
        ws_path = Path(record.workspace_dir).expanduser()
        if ws_path.is_dir():
            result[record.project_name] = ws_path

    return result


def load_project_local_xprompts(
    workspace_dir: Path, project: str
) -> dict[str, XPrompt]:
    """Load xprompts from a project's ``sase.yml`` file.

    Reads ``<workspace_dir>/sase.yml`` directly, bypassing the
    ``_include_local_config`` flag.  Returns xprompts namespaced with
    ``{project}/``.
    """
    sase_yml = resolve_project_config_read_path(
        workspace_dir,
        label=f"project config for {project}",
    )
    if sase_yml is None:
        return {}

    try:
        with open(sase_yml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        log.debug("Failed to load project sase.yml: %s", sase_yml, exc_info=True)
        record_load_issue(sase_yml, exc, kind="config")
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


def load_project_file_xprompts(
    workspace_dir: Path,
    project: str,
) -> dict[str, XPrompt]:
    """Load namespaced Markdown xprompts from one known project workspace."""
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(
            project_root=workspace_dir,
            project=project,
        )
        if source.path is not None and source.scope == "project"
    ]
    xprompts: dict[str, XPrompt] = {}
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for xprompt in _load_ordinary_xprompts_from_dir(project_dir):
            namespaced = namespace_xprompt(project, xprompt)
            xprompts[namespaced.name] = namespaced
    return xprompts
