"""Filesystem and coercion helpers for dismissed bundle archives."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sase.core.paths import parse_filename_timestamp

from ._models import INDEX_FILENAME

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


def index_path_for_root(root: Path) -> Path:
    """Return the SQLite index path for *root*."""

    return root / INDEX_FILENAME


def iter_bundle_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    results: list[Path] = []
    for entry in root.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(path for path in entry.glob("*.json") if path.is_file())
    for path in root.glob("*.json"):
        if path.is_file():
            results.append(path)
    return results


def read_bundle(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundle JSON must be an object")
    return data


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def path_shard(root: Path, path: Path) -> str:
    try:
        parent = path.parent.relative_to(root)
    except ValueError:
        parent = path.parent
    if parent.parts and _SHARD_DIR_RE.match(parent.parts[0]):
        return parent.parts[0]
    ts = parse_filename_timestamp(path.name)
    if ts is not None:
        return ts.strftime("%Y%m")
    return ""


def display_filename(root: Path, path: Path) -> str:
    try:
        path.relative_to(root)
    except ValueError:
        return path.name
    return path.name


def required_str(bundle: dict[str, Any], key: str) -> str:
    value = bundle.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"bundle missing {key}")
    return value


def string_or_default(value: object, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None
