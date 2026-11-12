"""Filesystem-backed macro loaders (search paths, package, home, project)."""

import importlib.resources
import logging
from pathlib import Path

from sase.content_layout import resolve_macro_file_sources

from ._loader_sources_common import (
    load_ordinary_macros_from_dir,
    namespace_macro,
)
from .discovery_order import (
    RANK_FILESYSTEM_BASE,
    RANK_PACKAGE_DEFAULT_MACROS,
    RANK_PACKAGE_MACROS,
    assign_discovery_rank,
    source_rank,
)
from .models import Macro

log = logging.getLogger(__name__)


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
        # Retired directories are always accepted as aliases.
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
        for macro_def in load_ordinary_macros_from_dir(search_dir):
            if project and is_local:
                macro_def = namespace_macro(project, macro_def)
            macro_def.discovery_rank = rank_by_path[search_dir]
            if macro_def.name in macros:
                del macros[macro_def.name]
            macros[macro_def.name] = macro_def

    return macros


def load_macros_from_internal() -> dict[str, Macro]:
    """Load macros from the internal sase package macros directory.

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    internal_dir = get_sase_package_macros_dir()

    if not internal_dir.is_dir():
        return {}

    macros: dict[str, Macro] = {}
    for macro_def in load_ordinary_macros_from_dir(internal_dir):
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
            for macro_def in load_ordinary_macros_from_dir(default_dir)
        },
        RANK_PACKAGE_DEFAULT_MACROS,
    )
