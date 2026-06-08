"""Runtime package version inventory collection."""

from __future__ import annotations

import importlib.metadata
import sys

from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.version._display import derive_display_version
from sase.version._git import cached_git_probe, probe_git, probe_git_metadata
from sase.version._models import (
    CORE_DISTRIBUTION_NAME,
    HOST_DISTRIBUTION_NAME,
    GitProbe,
    PackageRole,
    RuntimeVersionInventory,
    SourceKind,
    VersionPackageRecord,
)
from sase.version._plugins import plugin_candidates_from_distributions
from sase.version._sources import (
    code_directory,
    direct_url_info,
    distribution_location,
    distribution_name as distribution_metadata_name,
    distribution_version,
    find_distribution,
    install_type,
    resolve_import,
    source_root,
    source_version,
)
from sase.version._utils import append_warning, path_str


def collect_runtime_version_inventory(
    *,
    git_probe: GitProbe | None = probe_git_metadata,
    include_plugins: bool = True,
) -> RuntimeVersionInventory:
    """Collect the runtime inventory for the current SASE environment."""
    cached_probe = cached_git_probe(git_probe)
    packages = [
        collect_package_record(
            HOST_DISTRIBUTION_NAME,
            role="host",
            import_module="sase",
            source_kind="python",
            git_probe=cached_probe,
        ),
        collect_package_record(
            CORE_DISTRIBUTION_NAME,
            role="core",
            import_module=RUST_EXTENSION_MODULE_NAME,
            source_kind="rust",
            git_probe=cached_probe,
        ),
    ]
    if include_plugins:
        packages.extend(collect_plugin_package_records(git_probe=cached_probe))

    return RuntimeVersionInventory(
        executable=sys.argv[0],
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
        packages=tuple(packages),
    )


def collect_plugin_package_records(
    *, git_probe: GitProbe | None = probe_git_metadata
) -> tuple[VersionPackageRecord, ...]:
    """Collect installed SASE plugin package records without loading plugins."""
    git_probe = cached_git_probe(git_probe)
    records: list[VersionPackageRecord] = []
    for candidate in plugin_candidates_from_distributions(
        importlib.metadata.distributions()
    ):
        records.append(
            collect_package_record_from_distribution(
                candidate.distribution_name,
                dist=candidate.distribution,
                role="plugin",
                import_module=candidate.import_module,
                source_kind="python",
                git_probe=git_probe,
                plugin_signals=candidate.plugin_signals,
                initial_warnings=(),
            )
        )

    records.sort(key=lambda record: record.name.lower())
    return tuple(records)


def collect_package_record(
    distribution_name: str,
    *,
    role: PackageRole,
    import_module: str | None,
    source_kind: SourceKind,
    git_probe: GitProbe | None = probe_git_metadata,
) -> VersionPackageRecord:
    """Collect one package record without importing provider/plugin code."""
    warnings: list[str] = []
    dist = find_distribution(distribution_name, warnings)
    return collect_package_record_from_distribution(
        distribution_name,
        dist=dist,
        role=role,
        import_module=import_module,
        source_kind=source_kind,
        git_probe=git_probe,
        plugin_signals=(),
        initial_warnings=tuple(warnings),
    )


def collect_package_record_from_distribution(
    distribution_name: str,
    *,
    dist: importlib.metadata.Distribution | None,
    role: PackageRole,
    import_module: str | None,
    source_kind: SourceKind,
    git_probe: GitProbe | None,
    plugin_signals: tuple[str, ...],
    initial_warnings: tuple[str, ...],
) -> VersionPackageRecord:
    warnings: list[str] = list(initial_warnings)
    metadata_name = distribution_metadata_name(dist) or distribution_name
    dist_version = distribution_version(dist)
    dist_location = distribution_location(dist)
    direct_url = direct_url_info(dist, warnings)
    install = direct_url.install_type if direct_url else install_type(dist)

    import_resolution = resolve_import(import_module)
    if import_resolution.warning:
        warnings.append(import_resolution.warning)

    src_root = source_root(
        source_kind=source_kind,
        direct_url=direct_url,
        install_type=install,
        import_resolution=import_resolution,
        distribution_location=dist_location,
    )
    src_version = source_version(source_kind, src_root, install, warnings)
    git_result = probe_git(src_root, git_probe)
    if git_result.warning:
        warnings.append(git_result.warning)

    display_version = derive_display_version(
        src_version or dist_version,
        git_result.metadata,
    )
    code_dir = code_directory(
        source_kind=source_kind,
        install_type=install,
        source_root=src_root,
        import_resolution=import_resolution,
        distribution_location=dist_location,
    )
    if (
        code_dir == dist_location
        and import_resolution.code_directory is None
        and dist_location is not None
    ):
        append_warning(
            warnings,
            f"falling back to distribution location for {metadata_name}; "
            "import module path could not be resolved",
        )

    return VersionPackageRecord(
        name=metadata_name,
        role=role,
        display_version=display_version,
        distribution_version=dist_version,
        source_version=src_version,
        import_module=import_module,
        import_path=path_str(import_resolution.import_path),
        code_directory=path_str(code_dir),
        source_root=path_str(src_root),
        distribution_location=path_str(dist_location),
        install_type=install,
        git=git_result.metadata,
        plugin_signals=plugin_signals,
        warnings=tuple(warnings),
    )
