"""Stat-only change tokens for ACE auto-refresh surfaces.

Each token is built from path metadata (existence, mtime, size) without
opening file contents. Directory probes stay shallow: project and
lumberjack membership plus a bounded set of files. Callers treat an
indeterminate token as dirty and fail open.
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
_AXE_ROOT_FILES = (
    "status.json",
    "metrics.json",
    "pid",
    "desired_state.json",
    "orchestrator.pid",
)
_AXE_LUMBERJACK_FILES = (
    "status.json",
    "metrics.json",
    "chop_timestamps.json",
    "pid",
)
_BEAD_PROJECTION_FILES = (
    Path("issues.jsonl"),
    Path("events") / "manifest.json",
)


@dataclass(frozen=True)
class _PathMeta:
    """One path's metadata-only fingerprint."""

    path: str
    exists: bool
    mtime_ns: int | None = None
    size: int | None = None


@dataclass(frozen=True)
class SurfaceToken:
    """Immutable metadata token for one ACE refresh surface."""

    surface: str
    parts: tuple[tuple[str, bool, int | None, int | None], ...]
    indeterminate: bool = False


@dataclass(frozen=True)
class SurfaceTokenSnapshot:
    """One probe of every ACE refresh surface."""

    agents: SurfaceToken
    axe: SurfaceToken
    notifications: SurfaceToken
    patches: SurfaceToken
    procs: SurfaceToken

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


def live_surface_token_roots(*, beads_dir: Path | None = None) -> SurfaceTokenRoots:
    """Return the process's live ACE/proc token roots."""
    from sase.axe.state import axe_state_dir
    from sase.core.paths import sase_projects_dir
    from sase.notifications.store import notifications_file_path
    from sase.procs.paths import proc_store_path

    return SurfaceTokenRoots(
        projects_root=sase_projects_dir(),
        axe_root=axe_state_dir(),
        notifications_path=notifications_file_path(),
        procs_path=proc_store_path(),
        beads_dir=beads_dir,
    )


def probe_surface_tokens(
    roots: SurfaceTokenRoots | None = None,
) -> SurfaceTokenSnapshot:
    """Collect one token per surface without opening file contents."""
    resolved = live_surface_token_roots() if roots is None else roots
    return SurfaceTokenSnapshot(
        agents=_probe_agents_token(resolved.projects_root),
        axe=_probe_axe_token(resolved.axe_root),
        notifications=_probe_notifications_token(resolved.notifications_path),
        patches=_probe_patches_token(
            resolved.projects_root,
            beads_dir=resolved.beads_dir,
        ),
        procs=probe_procs_token(resolved.procs_path),
    )


def _probe_agents_token(projects_root: Path) -> SurfaceToken:
    """Token project membership, artifacts roots, and refresh pulses."""
    collected, children, ok = _open_membership(projects_root)
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
        ok = _extend_stat(collected, artifacts, ok=ok)
        ok = _extend_stat(
            collected,
            artifacts / _ACE_REFRESH_PULSE_NAME,
            ok=ok,
        )
    return _token("agents", collected, ok=ok)


def _probe_axe_token(axe_root: Path) -> SurfaceToken:
    """Token axe/lumberjack membership plus bounded status files."""
    collected, _axe_children, ok = _open_membership(axe_root)
    if _axe_children is None:
        return _token("axe", collected, ok=False)
    for name in _AXE_ROOT_FILES:
        ok = _extend_stat(collected, axe_root / name, ok=ok)
    ok = _extend_stat(collected, axe_root / "logs" / "output.log", ok=ok)
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
            ok = _extend_stat(collected, lumberjack_dir / name, ok=ok)
        ok = _extend_stat(
            collected,
            lumberjack_dir / "logs" / "output.log",
            ok=ok,
        )
    return _token("axe", collected, ok=ok)


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
        for relative in _BEAD_PROJECTION_FILES:
            ok = _extend_stat(collected, beads_dir / relative, ok=ok)
    return _token("patches", collected, ok=ok)


def probe_procs_token(procs_path: Path) -> SurfaceToken:
    """Token the canonical durable proc store."""
    parts: list[_PathMeta] = []
    ok = _extend_stat(parts, procs_path, ok=True)
    return _token("procs", parts, ok=ok)


def surface_token_drifted(
    current: SurfaceToken,
    last: SurfaceToken | None,
) -> bool:
    """Return True when *current* cannot be treated as unchanged."""
    if current.indeterminate or last is None:
        return True
    return current != last


def _token(surface: str, parts: Iterable[_PathMeta], *, ok: bool) -> SurfaceToken:
    return SurfaceToken(
        surface=surface,
        parts=tuple(
            (part.path, part.exists, part.mtime_ns, part.size) for part in parts
        ),
        indeterminate=not ok,
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


def _extend_stat(parts: list[_PathMeta], path: Path, *, ok: bool) -> bool:
    meta, meta_ok = _stat_path(path)
    parts.append(meta)
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
        parts.append(meta)
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
    "live_surface_token_roots",
    "probe_procs_token",
    "probe_surface_tokens",
    "surface_token_drifted",
]
