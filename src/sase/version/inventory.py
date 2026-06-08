"""Runtime package version inventory collection.

This module is intentionally CLI-free. It collects immutable records for the
packages that make up the running SASE runtime so later command/rendering layers
can format the same data for humans or JSON.
"""

from __future__ import annotations

import importlib as importlib
import subprocess as subprocess
import sys as sys

from sase.version._collector import (
    collect_package_record,
    collect_package_record_from_distribution,
    collect_plugin_package_records,
    collect_runtime_version_inventory,
)
from sase.version._display import derive_display_version
from sase.version._git import (
    cached_git_probe,
    git_probe_cache_key,
    probe_git,
    probe_git_metadata,
    run_git,
)
from sase.version._models import (
    CONSOLE_SCRIPT_ENTRY_POINT_GROUP,
    CORE_DISTRIBUTION_NAME,
    HOST_DISTRIBUTION_NAME,
    SASE_CHOP_SCRIPT_PREFIX,
    DirectUrlInfo,
    GitProbe,
    GitProbeResult,
    GitVersionMetadata,
    ImportResolution,
    InstallType,
    PackageRole,
    RuntimeVersionInventory,
    SourceKind,
    VersionPackageRecord,
)
from sase.version._plugins import (
    PluginCandidate,
    console_script_signal,
    distribution_entry_points,
    distribution_top_level_modules,
    entry_point_group,
    entry_point_import_module,
    entry_point_name,
    entry_point_signal,
    entry_point_value,
    is_runtime_distribution,
    is_sase_plugin_console_script,
    is_sase_plugin_distribution_name,
    module_from_distribution_name,
    module_from_entry_point_value,
    plugin_candidates_from_distributions,
    preferred_plugin_import_module,
    top_level_import_module,
)
from sase.version._sources import (
    ancestors,
    code_directory,
    direct_url_info,
    distribution_location,
    distribution_name,
    distribution_version,
    find_ancestor_with_file,
    find_cargo_version_root,
    find_distribution,
    install_type,
    path_from_url,
    python_source_version,
    read_toml,
    resolve_import,
    rust_source_version,
    source_root,
    source_version,
)
from sase.version._utils import (
    DISTRIBUTION_NORMALIZE_RE,
    IMPORT_MODULE_RE,
    VERSION_TAG_RE,
    append_warning,
    metadata_value,
    normalize_distribution_name,
    path_str,
    safe_str,
    version_from_tag,
)

_DirectUrlInfo = DirectUrlInfo
_ImportResolution = ImportResolution
_PluginCandidate = PluginCandidate
_VERSION_TAG_RE = VERSION_TAG_RE
_DISTRIBUTION_NORMALIZE_RE = DISTRIBUTION_NORMALIZE_RE
_IMPORT_MODULE_RE = IMPORT_MODULE_RE

_collect_package_record_from_distribution = collect_package_record_from_distribution
_collect_plugin_package_records = collect_plugin_package_records
_cached_git_probe = cached_git_probe
_git_probe_cache_key = git_probe_cache_key
_probe_git = probe_git
_run_git = run_git

_plugin_candidates_from_distributions = plugin_candidates_from_distributions
_distribution_entry_points = distribution_entry_points
_preferred_plugin_import_module = preferred_plugin_import_module
_distribution_top_level_modules = distribution_top_level_modules
_entry_point_group = entry_point_group
_entry_point_name = entry_point_name
_entry_point_value = entry_point_value
_entry_point_import_module = entry_point_import_module
_module_from_entry_point_value = module_from_entry_point_value
_top_level_import_module = top_level_import_module
_module_from_distribution_name = module_from_distribution_name
_entry_point_signal = entry_point_signal
_console_script_signal = console_script_signal
_is_sase_plugin_console_script = is_sase_plugin_console_script
_is_runtime_distribution = is_runtime_distribution
_is_sase_plugin_distribution_name = is_sase_plugin_distribution_name

_find_distribution = find_distribution
_distribution_name = distribution_name
_distribution_version = distribution_version
_distribution_location = distribution_location
_install_type = install_type
_direct_url_info = direct_url_info
_path_from_url = path_from_url
_resolve_import = resolve_import
_source_root = source_root
_source_version = source_version
_python_source_version = python_source_version
_rust_source_version = rust_source_version
_find_cargo_version_root = find_cargo_version_root
_find_ancestor_with_file = find_ancestor_with_file
_ancestors = ancestors
_read_toml = read_toml
_code_directory = code_directory

_version_from_tag = version_from_tag
_normalize_distribution_name = normalize_distribution_name
_metadata_value = metadata_value
_safe_str = safe_str
_append_warning = append_warning
_path_str = path_str

__all__ = [
    "CORE_DISTRIBUTION_NAME",
    "CONSOLE_SCRIPT_ENTRY_POINT_GROUP",
    "GitProbe",
    "GitProbeResult",
    "GitVersionMetadata",
    "HOST_DISTRIBUTION_NAME",
    "InstallType",
    "PackageRole",
    "RuntimeVersionInventory",
    "SASE_CHOP_SCRIPT_PREFIX",
    "SourceKind",
    "VersionPackageRecord",
    "collect_package_record",
    "collect_runtime_version_inventory",
    "derive_display_version",
    "probe_git_metadata",
]
