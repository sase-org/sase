"""Boot-imported runner lifecycle breadcrumbs and boot code identity.

``mark_lifecycle_phase`` records the latest boundary the runner crossed so a
later failure can say whether it died before its model turn. The in-memory
current phase is what failure-facts capture reads; the disk write is a
best-effort breadcrumb for out-of-process readers.

``boot_code_identity`` snapshots the code this process image imported. Only
module-scope imports here are stdlib: every ``sase.*`` import below is
function-local so importing this module at runner boot adds no deferred
import surface of its own.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any

SCHEMA_VERSION = 1

#: Lifecycle boundaries, in run order. ``handoff`` is set while plan,
#: question, monitor, gate, or pipe markers are processed.
LIFECYCLE_PHASES = (
    "booting",
    "waiting",
    "preparing",
    "provider_running",
    "provider_done",
    "finalizing",
    "handoff",
)

_LIFECYCLE_PHASE_SET = frozenset(LIFECYCLE_PHASES)

#: At most this many ``{phase, at}`` entries are kept on disk.
MAX_HISTORY_ENTRIES = 16

_lock = threading.Lock()
_current_phase: str | None = None

_boot_cache: tuple[dict[str, Any], str, float] | None = None


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def current_lifecycle_phase() -> str | None:
    """Return the in-memory current lifecycle phase, if any was marked."""
    with _lock:
        return _current_phase


def mark_lifecycle_phase(
    artifacts_dir: str | None,
    phase: str,
) -> str | None:
    """Mark *phase* as the latest boundary crossed. Never raises.

    Always updates the in-memory current phase. Best-effort writes
    ``lifecycle_phase``, ``lifecycle_phase_at``, and the bounded
    ``lifecycle_phases`` history into ``agent_meta.json`` when that file
    already exists; a missing file means bootstrap has not run yet, so
    nothing is created.
    """
    global _current_phase  # noqa: PLW0603
    if phase not in _LIFECYCLE_PHASE_SET:
        return current_lifecycle_phase()
    with _lock:
        _current_phase = phase
    if not artifacts_dir:
        return phase
    try:
        _write_lifecycle_breadcrumb(artifacts_dir, phase)
    except Exception:
        pass
    return phase


def _write_lifecycle_breadcrumb(artifacts_dir: str, phase: str) -> None:
    import json
    import os

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as stream:
            disk_meta = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(disk_meta, dict):
        return
    now = _utc_now_iso()
    history = disk_meta.get("lifecycle_phases")
    if not isinstance(history, list):
        history = []
    entries = [entry for entry in history if isinstance(entry, dict)]
    entries.append({"phase": phase, "at": now})
    disk_meta["lifecycle_phase"] = phase
    disk_meta["lifecycle_phase_at"] = now
    disk_meta["lifecycle_phases"] = entries[-MAX_HISTORY_ENTRIES:]

    from sase.axe.agent_meta import overlay_live_auto_keys, write_agent_meta_atomic

    overlay_live_auto_keys(artifacts_dir, disk_meta, disk_meta=disk_meta)
    write_agent_meta_atomic(
        artifacts_dir,
        disk_meta,
        index_updater=_marker_mutation_index_updater(),
    )


def _marker_mutation_index_updater():  # type: ignore[no-untyped-def]
    """Return the marker-mutation index updater without a top-level import."""
    from sase.core.agent_artifact_index_lifecycle import (
        update_agent_artifact_index_for_marker_mutation,
    )

    return update_agent_artifact_index_for_marker_mutation


def boot_code_identity(
    *,
    startup_commit: str | None = None,
) -> tuple[dict[str, Any], str, float]:
    """Snapshot this process image's code identity. Never raises.

    Returns ``(code_identity, booted_at, elapsed_ms)``. The identity covers
    the ``sase`` host, ``sase-core-rs``, and each installed ``sase-*``
    plugin as ``{name, role, version, commit, source_root, install_type}``.
    ``commit`` is probed from git for editable roots only; installed wheels
    carry a version but no commit. The result is memoized: the first call
    pays the inventory scan and later calls return the same snapshot.
    """
    global _boot_cache  # noqa: PLW0603
    with _lock:
        cached = _boot_cache
    if cached is not None:
        return cached
    started = datetime.datetime.now(datetime.UTC)
    try:
        identity = _capture_boot_code_identity(startup_commit=startup_commit)
    except Exception:
        identity = {"schema_version": SCHEMA_VERSION, "roots": []}
    try:
        booted_at = started.isoformat()
    except Exception:
        booted_at = ""
    try:
        elapsed_ms = (
            datetime.datetime.now(datetime.UTC) - started
        ).total_seconds() * 1000.0
    except Exception:
        elapsed_ms = -1.0
    snapshot = (identity, booted_at, elapsed_ms)
    with _lock:
        if _boot_cache is None:
            _boot_cache = snapshot
        else:
            snapshot = _boot_cache
    return snapshot


def _capture_boot_code_identity(
    *,
    startup_commit: str | None,
) -> dict[str, Any]:
    """Build the boot code identity without importing plugin code."""
    import importlib.metadata

    try:
        from sase.version import _models as _version_models
        from sase.version import _sources as _version_sources
    except Exception:
        return {"schema_version": SCHEMA_VERSION, "roots": []}
    if not all(
        hasattr(_version_sources, name)
        for name in (
            "direct_url_info",
            "distribution_location",
            "distribution_version",
            "find_distribution",
            "install_type",
            "resolve_import",
            "source_root",
        )
    ):
        return {"schema_version": SCHEMA_VERSION, "roots": []}
    CORE_DISTRIBUTION_NAME = getattr(
        _version_models, "CORE_DISTRIBUTION_NAME", "sase-core-rs"
    )

    captured_at = _utc_now_iso()
    warnings: list[str] = []
    roots: list[dict[str, Any]] = []

    # One pass over installed distributions: re-resolving each sase
    # distribution by name would re-scan sys.path per record.
    try:
        distributions = list(importlib.metadata.distributions())
    except Exception:
        distributions = []
    host_dist = None
    core_dist = None
    plugin_dists: list[Any] = []
    for dist in distributions:
        try:
            name = dist.metadata["Name"]
        except Exception:
            continue
        if not isinstance(name, str) or not name:
            continue
        lowered = name.lower().replace("_", "-")
        if lowered == "sase":
            host_dist = dist
        elif lowered == str(CORE_DISTRIBUTION_NAME).lower():
            core_dist = dist
        elif lowered.startswith("sase-"):
            plugin_dists.append(dist)
    if host_dist is not None:
        host = _package_root_from_dist(
            host_dist,
            "sase",
            role="host",
            import_module="sase",
            source_kind="python",
            startup_commit=startup_commit,
            warnings=warnings,
        )
        if host is not None:
            roots.append(host)
    if core_dist is not None:
        core = _package_root_from_dist(
            core_dist,
            str(CORE_DISTRIBUTION_NAME),
            role="core",
            import_module="sase_core_rs",
            source_kind="rust",
            startup_commit=None,
            warnings=warnings,
        )
        if core is not None:
            roots.append(core)
    plugin_dists.sort(
        key=lambda dist: _dist_name(dist).lower(),
    )
    for dist in plugin_dists:
        record = _package_root_from_dist(
            dist,
            _dist_name(dist),
            role="plugin",
            import_module=None,
            source_kind="python",
            startup_commit=None,
            warnings=warnings,
        )
        if record is not None:
            roots.append(record)

    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": captured_at,
        "roots": roots,
    }


def _dist_name(dist: Any) -> str:
    """Return a distribution's metadata name, or an empty string."""
    try:
        name = dist.metadata["Name"]
    except Exception:
        return ""
    return name if isinstance(name, str) and name else ""


def _package_root_from_dist(
    dist: Any,
    distribution_name: str,
    *,
    role: str,
    import_module: str | None,
    source_kind: str,
    startup_commit: str | None,
    warnings: list,
) -> dict[str, Any] | None:
    """Describe one installed distribution without importing its code."""
    from sase.version._sources import (
        direct_url_info,
        distribution_location,
        distribution_version,
        install_type,
        resolve_import,
        source_root,
    )

    version = distribution_version(dist)
    direct_url = direct_url_info(dist, warnings)
    resolved_install_type = (
        direct_url.install_type if direct_url else install_type(dist)
    )
    import_resolution = resolve_import(import_module)
    root = source_root(
        source_kind=source_kind,  # type: ignore[arg-type]
        direct_url=direct_url,
        install_type=resolved_install_type,
        import_resolution=import_resolution,
        distribution_location=distribution_location(dist),
    )
    from pathlib import Path

    source_root_str = str(root) if root is not None else None
    commit: str | None = None
    if resolved_install_type == "editable" and root is not None:
        if startup_commit is not None and role == "host":
            commit = startup_commit
        else:
            commit = _probe_editable_commit(Path(root))
    return {
        "name": distribution_name,
        "role": role,
        "version": version,
        "commit": commit,
        "source_root": source_root_str,
        "install_type": resolved_install_type,
    }


def _probe_editable_commit(root: object) -> str | None:
    """Return the HEAD commit for an editable root, or None."""
    try:
        from sase.version._git import probe_git_metadata_at_ref

        result = probe_git_metadata_at_ref(root, "HEAD")  # type: ignore[arg-type]
    except Exception:
        return None
    try:
        metadata = result.metadata
    except Exception:
        return None
    if metadata is None:
        return None
    commit = getattr(metadata, "commit", None)
    return commit if isinstance(commit, str) and commit else None
