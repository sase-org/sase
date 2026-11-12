"""Per-source macro loaders (filesystem, config, plugins, projects).

This module is the public import path for per-source loading. The
implementations live in the sibling ``loader_sources_*`` modules, with the
helpers shared by more than one of them in
:mod:`._loader_sources_common`.
"""

from ._loader_sources_common import (
    load_macro_from_file,
    namespace_macro,
)
from .loader_sources_config import load_macros_from_config
from .loader_sources_files import (
    get_macro_search_paths,
    get_sase_package_default_macros_dir,
    get_sase_package_macros_dir,
    load_macros_from_default_files,
    load_macros_from_files,
    load_macros_from_internal,
)
from .loader_sources_plugins import (
    load_macros_from_plugins,
    load_plugin_markdown_macros,
)
from .loader_sources_projects import (
    get_known_project_workspaces,
    get_project_lifecycle_record,
    inactive_project_message_for_ref,
    load_macros_from_project,
    load_project_file_macros,
    load_project_local_macros,
    load_project_local_workflows,
)

__all__ = [
    "get_known_project_workspaces",
    "get_macro_search_paths",
    "get_project_lifecycle_record",
    "get_sase_package_default_macros_dir",
    "get_sase_package_macros_dir",
    "inactive_project_message_for_ref",
    "load_macro_from_file",
    "load_macros_from_config",
    "load_macros_from_default_files",
    "load_macros_from_files",
    "load_macros_from_internal",
    "load_macros_from_plugins",
    "load_macros_from_project",
    "load_plugin_markdown_macros",
    "load_project_file_macros",
    "load_project_local_macros",
    "load_project_local_workflows",
    "namespace_macro",
]
