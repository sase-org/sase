"""Runtime and source identities used to invalidate grammar caches."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

import sase
from sase.completion.runtime_cache_models import CACHE_FORMAT_REVISION
from sase.completion.runtime_cache_support import digest_json

_DISTRIBUTIONS = ("sase", "sase-core-rs")


def runtime_identity() -> dict[str, Any]:
    """Return installation identity used to partition grammar caches."""
    package_file = Path(sase.__file__).resolve(strict=False)
    package_root = package_file.parent
    return {
        "cache_format_revision": CACHE_FORMAT_REVISION,
        "distributions": _distribution_records(),
        "package_file": _path_record(package_file),
        "package_root": _path_record(package_root),
        "plugin_commands": _plugin_commands_record(),
        "python_executable": _path_record(Path(sys.executable)),
        "python_version": sys.version.split()[0],
        "sase_version": sase.__version__,
    }


def runtime_identity_key(identity: Mapping[str, Any] | None = None) -> str:
    return digest_json(identity if identity is not None else runtime_identity())[:24]


def source_fingerprint() -> str:
    """Return a conservative source-change fingerprint for CLI grammar inputs."""
    package_root = Path(sase.__file__).resolve(strict=False).parent
    roots = (
        package_root / "__init__.py",
        package_root / "completion",
        package_root / "main",
    )
    files: list[dict[str, object]] = []
    for root in roots:
        if root.is_file():
            files.append(_source_file_record(root, package_root=package_root))
        elif not root.is_dir():
            files.append({"missing": _rel(root, package_root)})
        else:
            files.extend(
                _source_file_record(path, package_root=package_root)
                for path in sorted(root.rglob("*.py"))
                if "__pycache__" not in path.parts
            )
    files.extend(_editable_plugin_source_records())
    return digest_json(
        {
            "cache_format_revision": CACHE_FORMAT_REVISION,
            "environment": {"SASE_HOME": os.environ.get("SASE_HOME")},
            "files": files,
        }
    )


def _plugin_commands_record() -> dict[str, Any]:
    """Return the plugin command set for cache identity.

    Uses the disable-ignoring metadata scan (no plugin is ever imported)
    and records the disable-switch state alongside, so toggling a switch
    invalidates the grammar caches. Records are already sorted by the scan.
    """
    from sase.plugin_commands.scan import disabling_env_var, scan_plugin_commands

    records = scan_plugin_commands(honor_disable=False)
    return {
        "commands": tuple(
            {
                "distribution": record.distribution,
                "location": record.location,
                "name": record.name,
                "value": record.value,
                "version": record.version,
            }
            for record in records
        ),
        "disabled_by": disabling_env_var(),
    }


def _editable_plugin_source_records() -> list[dict[str, object]]:
    """Stat ``*.py`` files under each editable command provider's package.

    Resolved from ``direct_url.json`` and the entry-point module root
    without importing the plugin, so an editable source edit changes the
    fingerprint. Non-editable installs are covered by their version and
    location in :func:`runtime_identity` instead.
    """
    from sase.plugin_commands.scan import scan_plugin_commands

    records: list[dict[str, object]] = []
    for record in scan_plugin_commands(honor_disable=False):
        if not record.editable:
            continue
        package_dir = _plugin_package_dir(record.location, record.value)
        if package_dir is None:
            records.append(
                {"distribution": record.distribution, "missing": record.location}
            )
            continue
        try:
            sources = sorted(
                path
                for path in package_dir.rglob("*.py")
                if "__pycache__" not in path.parts
            )
        except OSError:
            records.append(
                {"distribution": record.distribution, "missing": str(package_dir)}
            )
            continue
        if not sources:
            records.append(
                {"distribution": record.distribution, "missing": str(package_dir)}
            )
            continue
        for path in sources:
            entry = _source_file_record(path, package_root=package_dir)
            entry["distribution"] = record.distribution
            records.append(entry)
    return records


def _plugin_package_dir(location: str, value: str) -> Path | None:
    """Resolve an editable provider's top-level package directory.

    *location* is the editable source root and *value* the entry-point
    value; the top-level package is its first module component, under either
    a flat or a ``src`` layout.
    """
    top = (
        value.split("[", 1)[0].strip().split(":", 1)[0].strip().split(".", 1)[0].strip()
    )
    if not top or not location:
        return None
    root = Path(location)
    for candidate in (root / top, root / "src" / top):
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _distribution_records() -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for name in _DISTRIBUTIONS:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            records.append({"name": name, "missing": True})
        else:
            records.append(
                {
                    "location": str(
                        Path(str(dist.locate_file(""))).resolve(strict=False)
                    ),
                    "metadata_name": dist.metadata.get("Name", name),
                    "name": name,
                    "version": dist.version,
                }
            )
    return tuple(records)


def _source_file_record(path: Path, *, package_root: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"missing": _rel(path, package_root)}
    return {
        "mtime_ns": stat.st_mtime_ns,
        "path": _rel(path, package_root),
        "size": stat.st_size,
    }


def _path_record(path: Path) -> dict[str, object]:
    expanded = path.expanduser().resolve(strict=False)
    record: dict[str, object] = {"path": str(expanded)}
    try:
        stat = expanded.stat()
    except OSError:
        record["missing"] = True
    else:
        record.update(
            {
                "device": stat.st_dev,
                "inode": stat.st_ino,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
            }
        )
    return record


def _rel(path: Path, package_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(package_root).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))
