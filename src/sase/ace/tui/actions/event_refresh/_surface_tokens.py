"""Stat-only change tokens for ACE auto-refresh surfaces.

Each token is built from path metadata (existence, mtime, size) without
opening file contents. Directory probes stay shallow: project and
lumberjack membership plus a bounded set of files. The bead-store part is
the exact stat-only store fingerprint over every stream file's metadata.
Callers treat an indeterminate token as dirty and fail open.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.ace.patch.project_spec_path import (
    active_project_spec_filename,
    archive_project_spec_filename,
    legacy_active_project_spec_filename,
    legacy_archive_project_spec_filename,
)

_ACE_REFRESH_PULSE_NAME = ".ace_refresh_pulse"
_AXE_ROOT_PID_FILES = (
    "pid",
    "orchestrator.pid",
)
_AXE_ROOT_IGNORED_FILES = frozenset({"status.json", "metrics.json"})
_AXE_LUMBERJACK_FILES = (
    "status.json",
    "metrics.json",
    "chop_timestamps.json",
    "pid",
)
_BEAD_FINGERPRINT_PART_PREFIX = "bead-store-fingerprint:"
_AXE_DETAIL_KINDS = frozenset({"status", "metrics", "log"})
_AXE_ALWAYS_KINDS = frozenset({"membership", "pid", "service", "content"})


@dataclass(frozen=True)
class _PathMeta:
    """One path's metadata-only fingerprint."""

    path: str
    exists: bool
    mtime_ns: int | None = None
    size: int | None = None
    kind: str = "content"


@dataclass(frozen=True)
class SurfaceToken:
    """Immutable metadata token for one ACE refresh surface.

    ``part_kinds`` is parallel to ``parts`` and does not participate in
    equality: a heartbeat rewrite of an unconsumed file still changes
    ``parts``, while consumers filter by kind before deciding to reload.
    """

    surface: str
    parts: tuple[tuple[str, bool, int | None, int | None], ...]
    indeterminate: bool = False
    part_kinds: tuple[str, ...] = ()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SurfaceToken):
            return NotImplemented
        return (
            self.surface == other.surface
            and self.parts == other.parts
            and self.indeterminate == other.indeterminate
        )

    def __hash__(self) -> int:
        return hash((self.surface, self.parts, self.indeterminate))


@dataclass(frozen=True)
class SurfaceTokenSnapshot:
    """One probe of every ACE refresh surface."""

    agents: SurfaceToken
    axe: SurfaceToken
    notifications: SurfaceToken
    patches: SurfaceToken
    procs: SurfaceToken
    tool_runs: SurfaceToken | None = None
    runner_capacity: SurfaceToken | None = None

    def token_for(self, surface: str) -> SurfaceToken:
        """Return the token for *surface*."""
        try:
            token = getattr(self, surface)
        except AttributeError as exc:
            raise KeyError(surface) from exc
        if not isinstance(token, SurfaceToken):
            raise KeyError(surface)
        return token


@dataclass(frozen=True)
class SurfaceTokenRoots:
    """Filesystem roots a token probe may inspect."""

    projects_root: Path
    axe_root: Path
    notifications_path: Path
    procs_path: Path
    beads_dir: Path | None = None
    agent_index_path: Path | None = None
    runner_limit_override_path: Path | None = None
    agent_hold_store_path: Path | None = None
    runner_slot_token_path: Path | None = None
    service_dir: Path | None = None
    service_state_path: Path | None = None
    service_status_path: Path | None = None
    tool_run_store_path: Path | None = None
    tool_run_wal_path: Path | None = None


def live_surface_token_roots(*, beads_dir: Path | None = None) -> SurfaceTokenRoots:
    """Return the process's live ACE/proc token roots."""
    from sase.config.runner_limit_override import runner_limit_override_path
    from sase.core.agent_hold_facade import agent_hold_store_path
    from sase.axe.state import axe_state_dir
    from sase.core.agent_scan_facade import default_agent_artifact_index_path
    from sase.core.paths import sase_home, sase_projects_dir
    from sase.notifications.store import notifications_file_path
    from sase.procs.paths import proc_store_path
    from sase.service.paths import (
        service_dir,
        service_state_path,
        service_status_path,
    )

    try:
        from sase.core.tool_run import tool_run_store_path

        _tool_run_store = tool_run_store_path()
        _tool_run_wal = _tool_run_store.parent / f"{_tool_run_store.name}-wal"
    except Exception:
        _tool_run_store = None
        _tool_run_wal = None

    return SurfaceTokenRoots(
        projects_root=sase_projects_dir(),
        agent_index_path=default_agent_artifact_index_path(),
        runner_limit_override_path=runner_limit_override_path(),
        agent_hold_store_path=agent_hold_store_path(),
        runner_slot_token_path=sase_home() / "runner_slots.token",
        axe_root=axe_state_dir(),
        notifications_path=notifications_file_path(),
        procs_path=proc_store_path(),
        beads_dir=beads_dir,
        service_dir=service_dir(),
        service_state_path=service_state_path(),
        service_status_path=service_status_path(),
        tool_run_store_path=_tool_run_store,
        tool_run_wal_path=_tool_run_wal,
    )


def probe_tool_runs_token(
    store_path: Path | None = None,
    wal_path: Path | None = None,
) -> SurfaceToken:
    """Stat-only token for the ToolRun ledger (never opens SQLite).

    Stats ``runs.sqlite`` and ``runs.sqlite-wal``. Rides the existing 10 s
    auto-refresh; a quiet tick opens no ToolRun file.
    """

    if store_path is None or wal_path is None:
        try:
            from sase.core.tool_run import tool_run_store_path

            resolved_store = tool_run_store_path()
            resolved_wal = resolved_store.parent / f"{resolved_store.name}-wal"
        except Exception:
            return SurfaceToken(surface="tool_runs", parts=(), indeterminate=True)
        store_path = store_path if store_path is not None else resolved_store
        wal_path = wal_path if wal_path is not None else resolved_wal
    parts: list[_PathMeta] = []
    ok = True
    ok = _extend_stat(parts, store_path, ok=ok)
    ok = _extend_stat(parts, wal_path, ok=ok)
    return _token("tool_runs", parts, ok=ok)


def probe_surface_tokens(
    roots: SurfaceTokenRoots | None = None,
) -> SurfaceTokenSnapshot:
    """Collect one token per surface without opening file contents."""
    resolved = live_surface_token_roots() if roots is None else roots
    return SurfaceTokenSnapshot(
        agents=_probe_agents_token(
            resolved.projects_root,
            agent_index_path=resolved.agent_index_path,
        ),
        axe=_probe_axe_token(
            resolved.axe_root,
            service_paths=(
                resolved.service_dir,
                resolved.service_state_path,
                resolved.service_status_path,
                # Background commands are oneshot rows in the proc store.
                resolved.procs_path,
            ),
        ),
        notifications=_probe_notifications_token(resolved.notifications_path),
        patches=_probe_patches_token(
            resolved.projects_root,
            beads_dir=resolved.beads_dir,
        ),
        procs=probe_procs_token(resolved.procs_path),
        tool_runs=probe_tool_runs_token(
            resolved.tool_run_store_path,
            resolved.tool_run_wal_path,
        ),
        runner_capacity=probe_runner_capacity_token(
            resolved.runner_slot_token_path,
            resolved.runner_limit_override_path,
            resolved.agent_hold_store_path,
        ),
    )


def probe_runner_capacity_token(
    runner_slot_token_path: Path | None = None,
    runner_limit_override_path: Path | None = None,
    agent_hold_store_path: Path | None = None,
) -> SurfaceToken:
    """Stat-only token for capacity reports, separate from the Agents roster."""
    parts: list[_PathMeta] = []
    ok = True
    if runner_slot_token_path is not None:
        ok = _extend_stat(parts, runner_slot_token_path, ok=ok)
    if runner_limit_override_path is not None:
        ok = _extend_stat(parts, runner_limit_override_path, ok=ok)
    if agent_hold_store_path is not None:
        ok = _extend_stat(parts, agent_hold_store_path, ok=ok)
    return _token("runner_capacity", parts, ok=ok)


def _probe_agents_token(
    projects_root: Path,
    *,
    agent_index_path: Path | None = None,
) -> SurfaceToken:
    """Token project membership, artifacts roots, and refresh pulses."""
    collected, children, ok = _open_membership(projects_root)
    if agent_index_path is not None:
        ok = _extend_stat(collected, agent_index_path, ok=ok, kind="index")
    if children is None:
        return _token("agents", collected, ok=False)
    for entry in children:
        is_dir = _dir_entry_is_dir(entry)
        if is_dir is None:
            ok = False
            continue
        if not is_dir:
            continue
        artifacts = Path(entry.path) / "artifacts"
        ok = _extend_stat(collected, artifacts, ok=ok, kind="artifacts")
        ok = _extend_stat(
            collected,
            artifacts / _ACE_REFRESH_PULSE_NAME,
            ok=ok,
            kind="pulse",
        )
    return _token("agents", collected, ok=ok)


def _probe_axe_token(
    axe_root: Path,
    *,
    service_paths: tuple[Path | None, ...] = (),
) -> SurfaceToken:
    """Token axe/lumberjack membership plus bounded status files.

    Service host files (``status.json`` / ``state.json``) and the proc store
    (which holds the oneshot rows behind ``!`` commands) are stat-only; an
    absent service directory is a stable, determinate token. Root
    ``status.json`` / ``metrics.json`` are omitted: the collector reads
    service host state and per-lumberjack files, not those unused
    scheduler leftovers.
    """
    collected, _axe_children, ok = _open_membership(axe_root)
    collected = [
        part
        for part in collected
        if Path(part.path).name not in _AXE_ROOT_IGNORED_FILES
    ]
    if _axe_children is None:
        return _token("axe", collected, ok=False)
    for name in _AXE_ROOT_PID_FILES:
        ok = _extend_stat(collected, axe_root / name, ok=ok, kind="pid")
    ok = _extend_stat(
        collected,
        axe_root / "logs" / "output.log",
        ok=ok,
        kind="log",
    )
    for service_path in service_paths:
        if service_path is not None:
            ok = _extend_stat(collected, service_path, ok=ok, kind="service")
    lumberjacks_root = axe_root / "lumberjacks"
    lumberjack_parts, lumberjacks, lumberjacks_ok = _open_membership(lumberjacks_root)
    collected.extend(lumberjack_parts)
    ok = ok and lumberjacks_ok
    if lumberjacks is None:
        return _token("axe", collected, ok=False)
    for entry in lumberjacks:
        is_dir = _dir_entry_is_dir(entry)
        if is_dir is None:
            ok = False
            continue
        if not is_dir:
            continue
        lumberjack_dir = Path(entry.path)
        for name in _AXE_LUMBERJACK_FILES:
            ok = _extend_stat(
                collected,
                lumberjack_dir / name,
                ok=ok,
                kind=_axe_lumberjack_file_kind(name),
            )
        ok = _extend_stat(
            collected,
            lumberjack_dir / "logs" / "output.log",
            ok=ok,
            kind="log",
        )
    return _token("axe", collected, ok=ok)


def _axe_lumberjack_file_kind(name: str) -> str:
    if name == "pid":
        return "pid"
    if name == "status.json":
        return "status"
    return "metrics"


def _probe_notifications_token(notifications_path: Path) -> SurfaceToken:
    """Token the canonical notifications JSONL file."""
    parts: list[_PathMeta] = []
    ok = _extend_stat(parts, notifications_path, ok=True)
    return _token("notifications", parts, ok=ok)


def _probe_patches_token(
    projects_root: Path,
    *,
    beads_dir: Path | None = None,
) -> SurfaceToken:
    """Token project specs/archives plus compact bead-store metadata."""
    collected, children, ok = _open_membership(projects_root)
    if children is None:
        return _token("patches", collected, ok=False)
    for entry in children:
        is_dir = _dir_entry_is_dir(entry)
        if is_dir is None:
            ok = False
            continue
        if not is_dir:
            continue
        project_dir = Path(entry.path)
        for filename in _project_spec_filenames(entry.name):
            ok = _extend_stat(collected, project_dir / filename, ok=ok)
    if beads_dir is not None:
        ok = _extend_stat(collected, beads_dir, ok=ok)
        ok = _extend_bead_fingerprint(collected, beads_dir, ok=ok)
    return _token("patches", collected, ok=ok)


def _extend_bead_fingerprint(
    collected: list[_PathMeta], beads_dir: Path, *, ok: bool
) -> bool:
    """Append the exact store fingerprint part without opening the store.

    The fingerprint (sase-1h8.5) stays valid once ``projection-off`` stops
    rewriting ``issues.jsonl``. Cores that predate the binding keep the old
    projection-file stats until the pin bump removes this fallback. A store
    that cannot be fingerprinted marks the token indeterminate so callers
    fail open and treat the surface as dirty.
    """
    try:
        from sase.core.bead_read_facade import store_fingerprint

        fingerprint = store_fingerprint(beads_dir)
    except Exception:
        fingerprint = None
    if fingerprint is not None:
        collected.append(
            _PathMeta(
                path=f"{_BEAD_FINGERPRINT_PART_PREFIX}{fingerprint.token}",
                exists=True,
            )
        )
        return ok
    projection_ok = True
    for relative in (Path("issues.jsonl"), Path("events") / "manifest.json"):
        meta, meta_ok = _stat_path(beads_dir / relative)
        collected.append(meta)
        projection_ok = projection_ok and meta_ok
    return ok and projection_ok


def probe_procs_token(procs_path: Path) -> SurfaceToken:
    """Token the canonical durable proc store."""
    parts: list[_PathMeta] = []
    ok = _extend_stat(parts, procs_path, ok=True)
    return _token("procs", parts, ok=ok)


def surface_token_drifted(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
) -> bool:
    """Return True when *current* cannot be treated as unchanged."""
    if current is None or last is None:
        return True
    if current.indeterminate or last.indeterminate:
        return True
    return current != last


def surface_token_changed_kinds(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consumed_kinds: frozenset[str] | None = None,
) -> tuple[str, ...]:
    """Return bounded part-kind labels for changed token inputs.

    Missing or indeterminate inputs are reported as ``("unknown",)`` so
    callers can explain fail-open refreshes without logging file paths.
    """
    if current is None or last is None or current.indeterminate or last.indeterminate:
        return ("unknown",)
    current_map = _part_map(current)
    last_map = _part_map(last)
    changed_kinds: set[str] = set()
    for path in current_map.keys() | last_map.keys():
        current_entry = current_map.get(path)
        last_entry = last_map.get(path)
        if current_entry == last_entry:
            continue
        kind = (
            current_entry[3]
            if current_entry is not None
            else last_entry[3]
            if last_entry is not None
            else "content"
        )
        if consumed_kinds is None or kind in consumed_kinds:
            changed_kinds.add(kind)
    return tuple(sorted(changed_kinds))


def _consumed_axe_part_kinds(*, consume_details: bool) -> frozenset[str]:
    """Return axe token kinds the current consumer actually reads."""
    if consume_details:
        return _AXE_ALWAYS_KINDS | _AXE_DETAIL_KINDS
    return _AXE_ALWAYS_KINDS


def axe_token_consumer_drifted(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consume_details: bool,
) -> bool:
    """Return True when consumed axe parts cannot be treated as unchanged.

    Lumberjack ``status.json`` / ``metrics.json`` / ``output.log`` rewrite
    every tick with heartbeat fields the Agents tab does not display.
    Those parts only invalidate the Services dashboard and visible logs.
    """
    if current is None or last is None:
        return True
    if current.indeterminate or last.indeterminate:
        return True
    kinds = _consumed_axe_part_kinds(consume_details=consume_details)
    return _parts_for_kinds(current, kinds) != _parts_for_kinds(last, kinds)


def axe_token_changed_kinds(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    consume_details: bool,
) -> tuple[str, ...]:
    """Return changed, currently consumed AXE token-part labels."""
    return surface_token_changed_kinds(
        current,
        last,
        consumed_kinds=_consumed_axe_part_kinds(consume_details=consume_details),
    )


def agents_token_reload_kind(
    current: SurfaceToken | None,
    last: SurfaceToken | None,
    *,
    watcher_active: bool,
) -> str:
    """Return ``skip`` or ``load`` for an Agents token pair.

    Index-only metadata churn is not a roster change. With a watcher the
    exact artifact-dir path is already queued; without one the poll
    fallback still loads. Pulse, artifacts-dir, and membership parts stay
    load signals.
    """
    if current is None or last is None:
        return "load"
    if current.indeterminate or last.indeterminate:
        return "load"
    changed = _surface_token_changed_entries(current, last)
    if not changed:
        return "skip"
    kinds = {kind for _path, kind in changed}
    if kinds <= {"index"}:
        return "skip" if watcher_active else "load"
    return "load"


def _surface_token_changed_entries(
    current: SurfaceToken,
    last: SurfaceToken,
) -> tuple[tuple[str, str], ...]:
    """Return ``(path, kind)`` for parts whose metadata differs."""
    current_map = _part_map(current)
    last_map = _part_map(last)
    changed: list[tuple[str, str]] = []
    for path in sorted(set(current_map) | set(last_map)):
        current_entry = current_map.get(path)
        last_entry = last_map.get(path)
        if current_entry == last_entry:
            continue
        kind = (
            current_entry[3]
            if current_entry is not None
            else last_entry[3]
            if last_entry is not None
            else "content"
        )
        changed.append((path, kind))
    return tuple(changed)


def _token(surface: str, parts: Iterable[_PathMeta], *, ok: bool) -> SurfaceToken:
    metas = tuple(parts)
    return SurfaceToken(
        surface=surface,
        parts=tuple(
            (part.path, part.exists, part.mtime_ns, part.size) for part in metas
        ),
        indeterminate=not ok,
        part_kinds=tuple(part.kind for part in metas),
    )


def _kind_at(token: SurfaceToken, index: int) -> str:
    if index < len(token.part_kinds) and token.part_kinds[index]:
        return token.part_kinds[index]
    return "content"


def _part_map(
    token: SurfaceToken,
) -> dict[str, tuple[bool, int | None, int | None, str]]:
    mapped: dict[str, tuple[bool, int | None, int | None, str]] = {}
    for index, (path, exists, mtime_ns, size) in enumerate(token.parts):
        mapped[path] = (exists, mtime_ns, size, _kind_at(token, index))
    return mapped


def _parts_for_kinds(
    token: SurfaceToken, kinds: frozenset[str]
) -> tuple[tuple[str, bool, int | None, int | None], ...]:
    return tuple(
        part
        for index, part in enumerate(token.parts)
        if _kind_at(token, index) in kinds
    )


def _with_kind(meta: _PathMeta, kind: str) -> _PathMeta:
    if meta.kind == kind:
        return meta
    return _PathMeta(
        path=meta.path,
        exists=meta.exists,
        mtime_ns=meta.mtime_ns,
        size=meta.size,
        kind=kind,
    )


def _stat_path(path: Path) -> tuple[_PathMeta, bool]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return _PathMeta(path=str(path), exists=False), True
    except OSError:
        return _PathMeta(path=str(path), exists=False), False
    return (
        _PathMeta(
            path=str(path),
            exists=True,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
        ),
        True,
    )


def _stat_dir_entry(entry: os.DirEntry[str]) -> tuple[_PathMeta, bool]:
    try:
        stat = entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return _PathMeta(path=entry.path, exists=False), True
    except OSError:
        return _PathMeta(path=entry.path, exists=False), False
    return (
        _PathMeta(
            path=entry.path,
            exists=True,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
        ),
        True,
    )


def _extend_stat(
    parts: list[_PathMeta],
    path: Path,
    *,
    ok: bool,
    kind: str = "content",
) -> bool:
    meta, meta_ok = _stat_path(path)
    parts.append(_with_kind(meta, kind))
    return ok and meta_ok


def _open_membership(
    path: Path,
) -> tuple[list[_PathMeta], tuple[os.DirEntry[str], ...] | None, bool]:
    """Return membership parts, child entries, and whether the probe is determinate.

    *children* is ``None`` when the directory could not be listed. An absent
    path yields an empty child tuple so later creation remains observable
    through the parent metadata.
    """
    parent, parent_ok = _stat_path(path)
    parent = _with_kind(parent, "membership")
    if not parent_ok:
        return [parent], None, False
    if not parent.exists:
        return [parent], (), True
    children, children_ok = _scandir_sorted(path)
    if not children_ok or children is None:
        return [parent], None, False
    parts = [parent]
    ok = True
    for entry in children:
        meta, meta_ok = _stat_dir_entry(entry)
        parts.append(_with_kind(meta, "membership"))
        if not meta_ok:
            ok = False
    return parts, children, ok


def _scandir_sorted(path: Path) -> tuple[tuple[os.DirEntry[str], ...] | None, bool]:
    try:
        with os.scandir(path) as iterator:
            children = tuple(sorted(iterator, key=lambda entry: entry.name))
    except FileNotFoundError:
        return (), True
    except OSError:
        return None, False
    return children, True


def _dir_entry_is_dir(entry: os.DirEntry[str]) -> bool | None:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return None


def _project_spec_filenames(project_name: str) -> tuple[str, ...]:
    return (
        active_project_spec_filename(project_name),
        archive_project_spec_filename(project_name),
        legacy_active_project_spec_filename(project_name),
        legacy_archive_project_spec_filename(project_name),
    )


__all__ = [
    "SurfaceToken",
    "SurfaceTokenRoots",
    "SurfaceTokenSnapshot",
    "agents_token_reload_kind",
    "axe_token_consumer_drifted",
    "live_surface_token_roots",
    "probe_procs_token",
    "probe_runner_capacity_token",
    "probe_surface_tokens",
    "probe_tool_runs_token",
    "surface_token_drifted",
]
