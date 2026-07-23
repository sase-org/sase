"""Persistence and staleness primitives for the agent-name registry."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.agent.names._registry_entries import entry_owner_missing
from sase.agent.names._registry_scan import source_signature_paths
from sase.core.paths import sase_home

SCHEMA_VERSION = 1
INDEX_FILENAME = "agent_name_registry.json"


def registry_path() -> Path:
    """Return the durable agent-name registry path."""
    return sase_home() / INDEX_FILENAME


def read_registry(path: Path) -> dict[str, Any] | None:
    """Read and minimally validate a registry file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    return data


def write_registry(
    path: Path,
    data: dict[str, Any],
    *,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> None:
    """Atomically write registry data through a unique temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    replaced = False
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        replace_file(tmp_path, path)
        replaced = True
    finally:
        if tmp_path is not None and not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def registry_data(entries: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted registry envelope for *entries*."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source_signature": _source_signature(),
        "entries": dict(sorted(entries.items())),
    }


def registry_file_is_stale(data: dict[str, Any]) -> bool:
    """Return whether registry data no longer matches its artifact sources."""
    if data.get("source_signature") != _source_signature():
        return True
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return True
    for entry in entries.values():
        if not isinstance(entry, dict):
            return True
        if entry_owner_missing(entry):
            return True
    return False


def _source_signature() -> dict[str, int]:
    """Summarize all paths whose changes can affect a registry rebuild."""
    count = 0
    max_mtime_ns = 0
    for path in _registry_source_signature_paths():
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        max_mtime_ns = max(max_mtime_ns, stat.st_mtime_ns)
    return {"count": count, "max_mtime_ns": max_mtime_ns}


def _registry_source_signature_paths() -> list[Path]:
    """Return paths included in the registry source signature."""
    return source_signature_paths()


def file_signature(path: Path) -> tuple[int, int]:
    """Return a lightweight signature for one registry file."""
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)
