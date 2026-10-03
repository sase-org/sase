"""Per-source macro loaders (filesystem, config, plugins, projects)."""

import importlib.resources
import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.config import load_macros_by_source
from sase.content_layout import (
    resolve_project_config_read_path,
    resolve_macro_file_sources,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
)
from sase.main.plugin_discovery import (
    discover_macro_plugin_modules,
    macro_plugin_definition_dirname,
    macro_plugins_disabled,
)

from .discovery_order import (
    RANK_CONFIG_BASE,
    RANK_FILESYSTEM_BASE,
    RANK_PACKAGE_DEFAULT_MACROS,
    RANK_PACKAGE_MACROS,
    RANK_PLUGIN,
    RANK_PROJECT_CONFIG,
    RANK_REGISTERED_PROJECT_BASE,
    assign_discovery_rank,
    merge_by_discovery_order,
    source_rank,
)
from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_local_macro_entries,
    parse_macro_entries,
    parse_yaml_front_matter,
    parse_yaml_front_matter_with_error,
)
from .load_issues import record_load_issue
from .loader_skills import (
    plugin_skill_destination,
    reject_misplaced_skill,
    skill_destination_for_macro_dir,
)
from .models import InputArg, Macro
from .reserved_namespaces import reject_reserved_memory_namespace
from .tags import parse_tags

log = logging.getLogger(__name__)


def namespace_macro(project: str, xp: Macro) -> Macro:
    """Return a copy of *xp* with its name prefixed by ``{project}/``.

    Skills are namespaced by :func:`sase.content_layout.skill_reference_name`
    instead, but ``skill_name`` is carried through so a copy never loses the
    provider-visible name.
    """
    namespaced_name = f"{project}/{xp.name}"
    return Macro(
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
        local_macros=xp.local_macros,
        memory_type=xp.memory_type,
        discovery_rank=xp.discovery_rank,
    )


def _load_ordinary_macros_from_dir(directory: Path) -> Iterator[Macro]:
    """Yield loadable non-skill definitions from an ordinary macro dir.

    A ``skill:`` declaration here is rejected with a migration diagnostic
    naming the scope's canonical ``sase/skills/`` directory, so a misplaced
    skill is reported rather than loaded under its bare name.
    """
    destination = skill_destination_for_macro_dir(directory)
    for md_file in sorted(directory.glob("*.md")):
        if not md_file.is_file():
            continue
        macro_def = load_macro_from_file(md_file)
        if macro_def is None:
            continue
        if reject_reserved_memory_namespace(macro_def.name, source=md_file):
            continue
        if reject_misplaced_skill(macro_def, source=md_file, migrate_to=destination):
            continue
        yield macro_def


def _parse_markdown_local_macros(
    front_matter: dict[str, Any] | None, source_path: str
) -> dict[str, Macro]:
    if not front_matter:
        return {}
    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

    macros_data = normalize_frontmatter_macros(front_matter, source=source_path)
    if not macros_data:
        return {}
    return parse_local_macro_entries(macros_data, source_path)


def load_macro_from_file(file_path: Path) -> Macro | None:
    """Load a single macro from a markdown file.

    Args:
        file_path: Path to the .md file.

    Returns:
        Macro object if successfully loaded, None otherwise.
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

    local_macros = _parse_markdown_local_macros(front_matter, str(file_path))

    if reject_reserved_memory_namespace(name, source=file_path):
        return None

    return Macro(
        name=name,
        content=body,
        inputs=inputs,
        source_path=str(file_path),
        tags=tags,
        snippet=snippet,
        description=description,
        skill=skill,
        log_skill_use=log_skill_use,
        local_macros=local_macros,
    )


def get_sase_package_macros_dir() -> Path:
    """Get the path to the internal sase macros directory.

    The built-in macros live at ``src/sase/macros/`` inside the package,
    so ``importlib.resources`` resolves them for both wheel and editable
    installs.
    """
    candidate = Path(str(importlib.resources.files("sase").joinpath("macros")))
    if candidate.is_dir():
        return candidate

    log.warning(
        "Internal macros directory not found via importlib.resources('sase/macros')",
    )
    return candidate


def get_sase_package_default_macros_dir() -> Path:
    """Get the path to the internal sase default markdown macros directory.

    Default file-backed macros live at ``src/sase/default_macros/`` inside
    the package, so ``importlib.resources`` resolves them for both wheel and
    editable installs.
    """
    candidate = Path(str(importlib.resources.files("sase").joinpath("default_macros")))
    if candidate.is_dir():
        return candidate

    log.warning(
        "Default macros directory not found via "
        "importlib.resources('sase/default_macros')",
    )
    return candidate


def get_macro_search_paths(
    project: str | None = None,
    *,
    project_root: Path | None = None,
) -> list[Path]:
    """Get the ordered list of directories to search for macro files.

    The Rust content-layout contract owns the first-wins order: canonical
    project, legacy project, canonical home, legacy home, project-specific
    home, and package filesystem sources. Config and plugin-only entries are
    handled by their dedicated loaders.

    Returns:
        List of directory paths to search, in priority order.
    """
    return [
        source.path
        for source in resolve_macro_file_sources(
            project_root=project_root,
            project=project,
        )
        if source.path is not None
    ]


def load_macros_from_files(project: str | None = None) -> dict[str, Macro]:
    """Load macros from file system locations.

    Scans each search directory for ``.md`` files. Earlier directories in the
    search path take precedence over later ones.

    When *project* is given, macros from project directories (canonical
    ``sase/macros/`` and legacy fallbacks) are namespaced with
    ``{project}/``.

    Returns:
        Dictionary mapping macro name to Macro object.
        Earlier priority sources override later ones.
    """
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
        from sase.legacy_xprompt_syntax import legacy_xprompt_syntax_enabled

        namespaced_dirs = set()
        if legacy_xprompt_syntax_enabled():
            cwd = Path.cwd()
            namespaced_dirs = {
                cwd / "sase" / "xprompts",
                cwd / ".xprompts",
                cwd / "xprompts",
            }
    rank_by_path = {
        search_dir: source_rank(RANK_FILESYSTEM_BASE, index, len(search_paths))
        for index, search_dir in enumerate(search_paths)
    }
    macros: dict[str, Macro] = {}

    # Process directories in reverse priority order (lowest first),
    # so higher-priority directories overwrite.
    for search_dir in reversed(search_paths):
        if not search_dir.is_dir():
            continue

        is_local = search_dir in namespaced_dirs
        for macro_def in _load_ordinary_macros_from_dir(search_dir):
            if project and is_local:
                macro_def = namespace_macro(project, macro_def)
            macro_def.discovery_rank = rank_by_path[search_dir]
            if macro_def.name in macros:
                del macros[macro_def.name]
            macros[macro_def.name] = macro_def

    return macros


def load_macros_from_config(project: str | None = None) -> dict[str, Macro]:
    """Load macros from config sources with proper source attribution.

    Loads macros from each config source separately (built-in defaults,
    plugin default configs, user sase.yml, overlay files) so that each
    macro gets the correct source attribution instead of all being
    tagged as ``"config"``.

    When *project* is given, macros from the local ``sase/sase.yml``
    (``local_config`` source) are namespaced with ``{project}/``.

    Priority order (within config sources, later overrides earlier):
    1. Built-in ``default_config.yml``
    2. Plugin ``default_config.yml`` files
    3. User ``sase.yml``
    4. Overlay ``sase_*.yml`` files
    5. Local ``sase/sase.yml`` (root ``sase.yml`` is a legacy fallback)

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    all_macros: dict[str, Macro] = {}

    sources = load_macros_by_source()
    for index, (source_label, macros_data) in enumerate(sources):
        parsed = parse_macro_entries(macros_data, source_label)
        if project and source_label == "local_config":
            parsed = {
                f"{project}/{name}": namespace_macro(project, xp)
                for name, xp in parsed.items()
            }
        merge_by_discovery_order(
            all_macros,
            parsed,
            fallback_rank=source_rank(RANK_CONFIG_BASE, index, len(sources)),
        )

    return all_macros


def load_macros_from_internal() -> dict[str, Macro]:
    """Load macros from the internal sase package macros directory.

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    internal_dir = get_sase_package_macros_dir()

    if not internal_dir.is_dir():
        return {}

    macros: dict[str, Macro] = {}
    for macro_def in _load_ordinary_macros_from_dir(internal_dir):
        macro_def.discovery_rank = RANK_PACKAGE_MACROS
        if macro_def.name not in macros:
            macros[macro_def.name] = macro_def

    return macros


def load_macros_from_default_files() -> dict[str, Macro]:
    """Load macros from the internal sase package default_macros directory.

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    default_dir = get_sase_package_default_macros_dir()

    if not default_dir.is_dir():
        return {}

    return assign_discovery_rank(
        {
            macro_def.name: macro_def
            for macro_def in _load_ordinary_macros_from_dir(default_dir)
        },
        RANK_PACKAGE_DEFAULT_MACROS,
    )


def load_plugin_markdown_macros(
    module: Any, resource_dir: str
) -> Iterator[tuple[str, Macro]]:
    """Yield ``(source, macro)`` for one plugin resource directory.

    Skill placement is *not* applied here: ``macros/`` and ``skills/`` are
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
            Macro(
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
                local_macros=_parse_markdown_local_macros(front_matter, source),
            ),
        )


def load_macros_from_plugins() -> dict[str, Macro]:
    """Load macros from plugin packages via ``sase_macros`` entry points.

    Each entry point should reference a module whose package contains an
    ``macros/`` resource directory with ``.md`` files; a packaged
    ``xprompts/`` directory is accepted only while the
    ``legacy_xprompt_syntax`` flag allows it. Plugin skills live in
    a sibling ``skills/`` resource directory instead, so a ``skill:``
    declaration here is rejected with that migration destination.

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    if macro_plugins_disabled():
        return {}

    macros: dict[str, Macro] = {}
    for module in discover_macro_plugin_modules():
        resource_dir = macro_plugin_definition_dirname(module)
        if resource_dir is None:
            log.debug(
                "Skipping plugin %s without a macro resource directory",
                getattr(module, "__name__", module),
            )
            continue
        for source, macro_def in load_plugin_markdown_macros(module, resource_dir):
            if reject_reserved_memory_namespace(macro_def.name, source=source):
                continue
            if reject_misplaced_skill(
                macro_def,
                source=source,
                migrate_to=plugin_skill_destination(),
            ):
                continue
            macro_def.discovery_rank = RANK_PLUGIN
            macros[macro_def.name] = macro_def

    return macros


def load_macros_from_project(project: str) -> dict[str, Macro]:
    """Load macros from a project-specific directory.

    Loads macros from canonical ``~/sase/macros/{project}/`` and the
    legacy config-directory fallback, then namespaces them with the project
    name (e.g., bar.md → foo/bar for project 'foo').

    Args:
        project: The project name to load macros for.

    Returns:
        Dictionary mapping namespaced macro name to Macro object.
        Returns empty dict if directory doesn't exist.
    """
    macros: dict[str, Macro] = {}
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
        for macro_def in _load_ordinary_macros_from_dir(project_dir):
            ns = namespace_macro(project, macro_def)
            ns.discovery_rank = rank_by_path[project_dir]
            if ns.name in macros:
                del macros[ns.name]
            macros[ns.name] = ns

    return macros


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


def load_project_local_macros(workspace_dir: Path, project: str) -> dict[str, Macro]:
    """Load macros from a project's ``sase.yml`` file.

    Reads ``<workspace_dir>/sase.yml`` directly, bypassing the
    ``_include_local_config`` flag.  Returns macros namespaced with
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

    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

    macros_data: dict[str, Any] = normalize_frontmatter_macros(
        data, source=f"project_local_config:{project}"
    )
    if not macros_data:
        return {}

    source_label = f"project_local_config:{project}"
    parsed = parse_macro_entries(macros_data, source_label)
    namespaced = {
        f"{project}/{name}": namespace_macro(project, xp) for name, xp in parsed.items()
    }
    return assign_discovery_rank(namespaced, RANK_PROJECT_CONFIG)


def load_project_file_macros(
    workspace_dir: Path,
    project: str,
) -> dict[str, Macro]:
    """Load namespaced Markdown macros from one known project workspace."""
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
    macros: dict[str, Macro] = {}
    for project_dir in reversed(project_dirs):
        if not project_dir.is_dir():
            continue
        for macro_def in _load_ordinary_macros_from_dir(project_dir):
            namespaced = namespace_macro(project, macro_def)
            namespaced.discovery_rank = rank_by_path[project_dir]
            if namespaced.name in macros:
                del macros[namespaced.name]
            macros[namespaced.name] = namespaced
    return macros
