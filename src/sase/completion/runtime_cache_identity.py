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
    return digest_json(
        {
            "cache_format_revision": CACHE_FORMAT_REVISION,
            "environment": {"SASE_HOME": os.environ.get("SASE_HOME")},
            "files": files,
        }
    )


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
