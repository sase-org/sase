"""Mtime-based file cache for reducing redundant I/O during TUI refresh cycles.

On each refresh (every ~7 seconds), the Agents tab re-reads many JSON files
(done.json, agent_meta.json, workflow_state.json, prompt_step_*.json, etc.).
Most of these files don't change between refreshes.  This module caches parsed
JSON data keyed by (path, mtime), turning redundant file reads into cheap
os.stat() calls (~1-2 us each vs ~50-100 us for open+read+parse).
"""

import json
import os
from pathlib import Path
from typing import Any

# Cache: path_str -> (mtime, parsed_data)
_json_cache: dict[str, tuple[float, Any]] = {}

# Cache: (dir_str, pattern) -> (dir_mtime, sorted file path strings)
_glob_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


def read_json_cached(path: str | Path) -> Any | None:
    """Read and parse a JSON file, returning cached result if mtime unchanged.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path_str = str(path)
    try:
        mtime = os.path.getmtime(path_str)
    except OSError:
        _json_cache.pop(path_str, None)
        return None

    cached = _json_cache.get(path_str)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(path_str, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        _json_cache.pop(path_str, None)
        return None

    _json_cache[path_str] = (mtime, data)
    return data


def glob_json_cached(directory: str | Path, pattern: str) -> list[Path]:
    """Glob a directory for files, caching results based on directory mtime.

    Directory mtime changes when files are created or deleted within it,
    so a matching mtime guarantees the same set of entries.
    """
    dir_str = str(directory)
    key = (dir_str, pattern)
    try:
        dir_mtime = os.path.getmtime(dir_str)
    except OSError:
        _glob_cache.pop(key, None)
        return []

    cached = _glob_cache.get(key)
    if cached is not None and cached[0] == dir_mtime:
        return [Path(p) for p in cached[1]]

    result = sorted(Path(directory).glob(pattern))
    _glob_cache[key] = (dir_mtime, [str(p) for p in result])
    return result


def file_exists_cached(path: str | Path) -> bool:
    """Check if a file exists, using the JSON cache to avoid redundant stats.

    If the file is already in the JSON cache, it exists.  Otherwise fall
    back to os.path.exists().
    """
    path_str = str(path)
    if path_str in _json_cache:
        return True
    return os.path.exists(path_str)


def invalidate_path(path: str | Path) -> None:
    """Remove a specific path from the JSON cache."""
    _json_cache.pop(str(path), None)


def clear_all() -> None:
    """Clear all caches.  Called when a full re-scan is needed."""
    _json_cache.clear()
    _glob_cache.clear()
