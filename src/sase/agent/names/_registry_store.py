"""Persistence and staleness primitives for the agent-name registry."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import os
import time
from pathlib import Path
import tempfile
from typing import Any

from sase.agent.names._registry_entries import (
    entry_owner_missing,
    normalize_agent_session_kind,
)
from sase.agent.names._registry_scan import source_signature_paths
from sase.core.paths import sase_home

SCHEMA_VERSION = 3
_LEGACY_SCHEMA_VERSIONS = frozenset({1, 2})
INDEX_FILENAME = "agent_name_registry.json"

# Bumped whenever a scan-logic change would derive different entries from the
# same on-disk artifacts, so every existing registry rebuilds exactly once
# after upgrade. This is independent of SCHEMA_VERSION, which tracks the
# on-disk envelope's own compatibility, not the scanner's behavior.
SCAN_VERSION = 2

_SOURCE_SIGNATURE_SESSION: ContextVar[list[dict[str, int | str]] | None] = ContextVar(
    "agent_name_registry_source_signature_session", default=None
)


def registry_path() -> Path:
    """Return the durable agent-name registry path."""
    return sase_home() / INDEX_FILENAME


def read_registry(path: Path) -> dict[str, Any] | None:
    """Read and minimally validate a registry file."""
    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()
    try:
        if timer is None:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        else:
            with timer.stage("registry_file_read"):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    schema_version = data.get("schema_version")
    if schema_version not in {SCHEMA_VERSION, *_LEGACY_SCHEMA_VERSIONS}:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    if schema_version in _LEGACY_SCHEMA_VERSIONS:
        upgraded = dict(data)
        upgraded["schema_version"] = SCHEMA_VERSION
        upgraded["_needs_rebuild"] = True
        if schema_version == 1:
            upgraded["entries"] = {
                name: _upgrade_v1_entry(name, entry)
                for name, entry in entries.items()
                if isinstance(name, str) and isinstance(entry, dict)
            }
        else:
            upgraded["entries"] = {
                name: _upgrade_v2_entry(entry)
                for name, entry in entries.items()
                if isinstance(name, str) and isinstance(entry, dict)
            }
        return upgraded
    return data


@dataclass(frozen=True)
class _RegistryTmpSweepResult:
    """Outcome of sweeping stale agent-name registry temp files."""

    scanned: int = 0
    selected: int = 0
    removed: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()
    reclaimable_bytes: int = 0
    reclaimed_bytes: int = 0
    capped: bool = False
    paths: tuple[str, ...] = ()


def _default_registry_tmp_max_age_seconds() -> float:
    """Return the configured stale age for registry temp files."""
    try:
        from sase.config.core import get_agent_name_registry_tmp_horizon_seconds

        return float(get_agent_name_registry_tmp_horizon_seconds())
    except Exception:  # noqa: BLE001 - a sweep must never break a registry write.
        return 600.0


def _default_registry_tmp_max_removals() -> int:
    """Return the configured per-pass budget for the registry temp sweep."""
    try:
        from sase.config.core import get_agent_name_registry_tmp_max_removals

        return int(get_agent_name_registry_tmp_max_removals())
    except Exception:  # noqa: BLE001 - fall back to the built-in budget.
        return 200


def _registry_tmp_prefix(path: Path) -> str:
    return f".{path.name}."


def sweep_stale_registry_tmp_files(
    path: Path,
    *,
    max_age_seconds: float | None = None,
    now: float | None = None,
    apply: bool = True,
    max_removals: int | None = None,
) -> _RegistryTmpSweepResult:
    """Remove ``.<name>.*.tmp`` siblings of the registry older than the horizon.

    Callers that already hold the registry mutation lock (every
    :func:`write_registry` path) sweep under that lock; the retention-chop
    reaper applies this same age-gated sweep without the lock, relying on the
    horizon to protect in-progress dumps. Only direct children of the registry
    directory are considered, symlinks are never followed, and at most
    *max_removals* files go in one pass.
    """
    horizon = (
        _default_registry_tmp_max_age_seconds()
        if max_age_seconds is None
        else max_age_seconds
    )
    budget = (
        _default_registry_tmp_max_removals() if max_removals is None else max_removals
    )
    moment = time.time() if now is None else now
    prefix = _registry_tmp_prefix(path)
    try:
        entries = list(path.parent.iterdir())
    except OSError as exc:
        return _RegistryTmpSweepResult(errors=(f"registry dir listing failed: {exc}",))
    candidates: list[tuple[float, int, Path]] = []
    skipped = 0
    for entry in entries:
        if not entry.name.startswith(prefix) or not entry.name.endswith(".tmp"):
            continue
        try:
            if entry.is_symlink() or not entry.is_file():
                skipped += 1
                continue
            stat = entry.stat()
        except OSError:
            skipped += 1
            continue
        if moment - stat.st_mtime < horizon:
            skipped += 1
            continue
        candidates.append((stat.st_mtime, stat.st_size, entry))
    candidates.sort(key=lambda item: (item[0], str(item[2])))
    scanned = len(candidates) + skipped
    selected = candidates[: max(0, budget)]
    capped_out = candidates[len(selected) :]
    capped = bool(capped_out)
    skipped += len(capped_out)
    removed = 0
    reclaimed = 0
    reclaimable = sum(size for _, size, _ in selected)
    errors: list[str] = []
    swept: list[str] = []
    if apply:
        for _, size, entry in selected:
            try:
                entry.unlink()
            except FileNotFoundError:
                skipped += 1
            except OSError as exc:
                errors.append(f"{entry.name}: {exc}")
            else:
                removed += 1
                reclaimed += size
                swept.append(str(entry))
    else:
        swept = [str(entry) for _, _, entry in selected]
    return _RegistryTmpSweepResult(
        scanned=scanned,
        selected=len(selected),
        removed=removed,
        skipped=skipped,
        errors=tuple(errors),
        reclaimable_bytes=reclaimable,
        reclaimed_bytes=reclaimed,
        capped=capped,
        paths=tuple(swept),
    )


def write_registry(
    path: Path,
    data: dict[str, Any],
    *,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> None:
    """Atomically write registry data through a unique temporary file."""
    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Every write_registry caller holds the registry mutation lock, so this
        # sweep runs under that lock; the horizon still protects the temp file
        # this very write is about to create. Failures stay silent: a sweep
        # must never break a registry write.
        sweep_stale_registry_tmp_files(path)
    except Exception:  # noqa: BLE001 - sweep failures must not break writes.
        pass
    tmp_path: Path | None = None
    replaced = False
    try:
        if timer is None:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            replace_file(tmp_path, path)
            replaced = True
        else:
            entry_count = len(data.get("entries", {})) if isinstance(data, dict) else 0
            with timer.stage(
                "registry_write", registry_writes=1, entry_count=entry_count
            ):
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
        "scan_version": SCAN_VERSION,
        "source_signature": _source_signature(),
        "entries": dict(sorted(entries.items())),
    }


def registry_file_is_stale(data: dict[str, Any]) -> bool:
    """Return whether registry data no longer matches its artifact sources."""
    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()
    if timer is not None:
        with timer.stage("registry_source_proof"):
            return _registry_file_is_stale(data)
    return _registry_file_is_stale(data)


def _registry_file_is_stale(data: dict[str, Any]) -> bool:
    if data.get("_needs_rebuild") is True:
        return True
    if data.get("scan_version") != SCAN_VERSION:
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

    from sase.agent.launch_timing import active_launch_timing_recorder

    timer = active_launch_timing_recorder()

    digest = hashlib.sha256()
    paths = sorted(set(_registry_source_signature_paths()), key=lambda path: str(path))
    statted_files = 0
    if timer is None:
        _update_source_signature_digest(digest, paths)
    else:
        with timer.stage("registry_source_signature", scanned_source_files=len(paths)):
            statted_files = _update_source_signature_digest(digest, paths)
            timer.mark(
                "registry_source_signature_counts", statted_json_files=statted_files
            )
    signature: dict[str, int | str] = {
        "count": len(paths),
        "path_digest": digest.hexdigest(),
    }
    if session_cache is not None:
        session_cache.append(signature)
    return signature


def _update_source_signature_digest(
    digest: Any,
    paths: list[Path],
) -> int:
    statted_files = 0
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
        statted_files += 1
        digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
        digest.update(b"\0")
    return statted_files


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
    return _upgrade_v2_entry(upgraded)


def _upgrade_v2_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a v2 entry's container kinds to the session spelling."""
    upgraded = dict(entry)
    # legacy agent-family spelling
    for field in ("reservation_kind", "container_kind"):
        if field in upgraded:
            upgraded[field] = normalize_agent_session_kind(upgraded[field])
    return upgraded
