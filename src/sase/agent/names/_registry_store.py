"""Persistence and staleness primitives for the agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.agent.names._registry_entries import entry_owner_missing
from sase.agent.names._registry_scan import source_signature_paths
from sase.core.paths import sase_home

SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1
INDEX_FILENAME = "agent_name_registry.json"

_SOURCE_SIGNATURE_SESSION: ContextVar[list[dict[str, int | str]] | None] = ContextVar(
    "agent_name_registry_source_signature_session", default=None
)


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
    schema_version = data.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, _LEGACY_SCHEMA_VERSION}:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    if schema_version == _LEGACY_SCHEMA_VERSION:
        upgraded = dict(data)
        upgraded["schema_version"] = SCHEMA_VERSION
        upgraded["_needs_rebuild"] = True
        upgraded["entries"] = {
            name: _upgrade_v1_entry(name, entry)
            for name, entry in entries.items()
            if isinstance(name, str) and isinstance(entry, dict)
        }
        return upgraded
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
    if data.get("_needs_rebuild") is True:
        return True
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


def _source_signature() -> dict[str, int | str]:
    """Fingerprint registry sources without observing live run output mtimes."""

    session_cache = _SOURCE_SIGNATURE_SESSION.get()
    if session_cache:
        return session_cache[0]

    digest = hashlib.sha256()
    paths = sorted(
        set(_registry_source_signature_paths()),
        key=lambda path: str(path),
    )
    for path in paths:
        digest.update(os.fsencode(path))
        digest.update(b"\0")
        # Every file source_signature_paths() returns is a dismissed-bundle
        # record or dismissed_agents.json, and both always carry a ``.json``
        # suffix; everything else is an artifact directory, whose path name
        # (already hashed above) is its whole signature contribution. Reading
        # the suffix instead of calling ``is_file()`` skips a stat syscall per
        # artifact directory, which is most of the paths here.
        if path.suffix != ".json":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
        digest.update(b"\0")
    signature: dict[str, int | str] = {
        "count": len(paths),
        "path_digest": digest.hexdigest(),
    }
    if session_cache is not None:
        session_cache.append(signature)
    return signature


@contextmanager
def source_signature_load_session() -> Iterator[None]:
    """Memoize one source signature for a bounded registry load session."""

    if _SOURCE_SIGNATURE_SESSION.get() is not None:
        yield
        return
    token = _SOURCE_SIGNATURE_SESSION.set([])
    try:
        yield
    finally:
        _SOURCE_SIGNATURE_SESSION.reset(token)


def _registry_source_signature_paths() -> list[Path]:
    """Return paths included in the registry source signature."""
    return source_signature_paths()


def file_signature(path: Path) -> tuple[int, int]:
    """Return a lightweight signature for one registry file."""
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _upgrade_v1_entry(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Retain v1 reservations while making their provenance non-ambiguous."""
    upgraded = dict(entry)
    source_machine = upgraded.get("imported_from_machine")
    if isinstance(source_machine, str) and source_machine:
        upgraded.update(
            {
                "origin": "import_v1",
                "canonical_global_name": None,
                "source_owner": None,
                "legacy_source_machine": source_machine,
            }
        )
    else:
        upgraded.update(
            {
                "origin": "local",
                "canonical_global_name": None,
                "source_owner": None,
                "legacy_source_machine": None,
                "imported_digest": None,
            }
        )
    upgraded["name"] = name
    return upgraded
