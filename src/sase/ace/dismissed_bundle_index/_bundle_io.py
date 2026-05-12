"""Filesystem and coercion helpers for dismissed bundle archives."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

from sase.core.paths import parse_filename_timestamp

from ._models import INDEX_FILENAME

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


def index_path_for_root(root: Path) -> Path:
    """Return the SQLite index path for *root*."""

    return root / INDEX_FILENAME


@contextmanager
def archive_maintenance_lock(root: Path) -> Iterator[None]:
    """Serialize long-running archive maintenance against other maintainers."""

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".archive.lock"
    with open(lock_path, "a+b") as lock_file:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows fallback
            yield
            return
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def iter_bundle_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    results: list[Path] = []
    for entry in root.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(path for path in entry.glob("*.json") if path.is_file())
            results.extend(
                path for path in entry.glob("*/bundle.json") if path.is_file()
            )
    for path in root.glob("*.json"):
        if path.is_file():
            results.append(path)
    return results


def read_bundle(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundle JSON must be an object")
    return data


def archive_payload_hash(bundle: dict[str, Any]) -> str:
    """Return a stable hash for a bundle payload excluding its hash field."""

    payload = dict(bundle)
    payload.pop("archive_payload_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def agent_id_for_bundle(bundle: dict[str, Any]) -> str:
    raw_suffix = required_str(bundle, "raw_suffix")
    agent_type = string_or_default(bundle.get("agent_type"), "run")
    project_file = optional_str(bundle.get("project_file")) or ""
    step_index = optional_int(bundle.get("step_index"))
    step_index_text = "" if step_index is None else str(step_index)
    payload = "\0".join((project_file, raw_suffix, agent_type, step_index_text))
    return sha256(payload.encode("utf-8")).hexdigest()


def shard_for_raw_suffix(raw_suffix: str) -> str:
    ts = parse_filename_timestamp(raw_suffix)
    if ts is not None:
        return ts.strftime("%Y%m")
    if len(raw_suffix) >= 6 and raw_suffix[:6].isdigit():
        return raw_suffix[:6]
    return "000101"


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
        relative = path.relative_to(root)
    except ValueError:
        return path.name
    if path.name == "bundle.json" and len(relative.parts) >= 3:
        return "/".join(relative.parts[-2:])
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


def positive_int_or_default(value: object, default: int) -> int:
    parsed = optional_int(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def nonnegative_int_or_default(value: object, default: int) -> int:
    parsed = optional_int(value)
    if parsed is None or parsed < 0:
        return default
    return parsed
