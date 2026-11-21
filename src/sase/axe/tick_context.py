"""Per-tick job context for one routine.

Each routine tick hands its jobs a shared ``context.json``. Parsing every
ProjectSpec and serializing ``all_changespecs.json`` /
``filtered_changespecs.json`` used to happen on every tick of every routine,
although only a few jobs read those files. :class:`TickContextWriter` now
serializes Patches only when an enabled job in the routine reads them, parses
only when a ProjectSpec file's identity changed, and skips rewriting any tick
file whose content would be unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from sase.ace.patch import Patch

from .chop_script_context import (
    ChopScriptContext,
    serialize_patches,
    write_chop_context,
)
from .config import ChopConfig

#: Builtin jobs whose handlers read the tick's serialized Patch files through
#: ``BuiltinChopRuntime.all_patches`` / ``filtered_patches``.
PATCH_READING_BUILTIN_JOBS: frozenset[str] = frozenset(
    {
        "comment_zombie_checks",
        "hook_checks",
        "mentor_checks",
        "orphan_cleanup",
        "pending_checks_poll",
        "suffix_transforms",
        "workflow_checks",
    }
)

#: Script prefixes of SASE job executables (core and plugin). Those scripts
#: read Patches only through the job runtime, which parses on demand when a
#: tick did not serialize them.
SASE_JOB_SCRIPT_PREFIXES: tuple[str, ...] = ("sase_job_", "sase_chop_")

# Legacy compatibility: persisted job policies may still use the old name.
_PATCH_GUARD_PROVIDERS = frozenset({"patch", "changespec"})  # legacy provider name

FileIdentity = tuple[int, int, int]
PatchFingerprint = tuple[tuple[str, str | None, FileIdentity], ...]


def _job_reads_tick_patches(chop: ChopConfig) -> bool:
    """Return whether *chop* needs the tick's serialized Patch files.

    True for a job with a Patch ``inhibit_if`` guard, for the builtin
    Patch-lifecycle jobs, and for any script outside the SASE job namespace,
    because the documented context contract lets external scripts read the
    files directly.
    """
    if any(
        guard.get("provider") in _PATCH_GUARD_PROVIDERS for guard in chop.inhibit_if
    ):
        return True
    script = chop.script_name
    for prefix in SASE_JOB_SCRIPT_PREFIXES:
        if script.startswith(prefix):
            return script.removeprefix(prefix) in PATCH_READING_BUILTIN_JOBS
    return True


def routine_reads_tick_patches(chops: Iterable[ChopConfig]) -> bool:
    """Return whether any enabled job in a routine needs serialized Patches."""
    return any(chop.enabled and _job_reads_tick_patches(chop) for chop in chops)


def _file_identity(path: str | os.PathLike[str]) -> FileIdentity | None:
    """Return ``(mtime_ns, size, inode)`` for *path*, or None when unreadable."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ino)


def _patch_files_fingerprint() -> PatchFingerprint | None:
    """Identify every ProjectSpec file ``find_all_patches`` would parse.

    Returns None when discovery or a stat fails, which forces a fresh parse.
    """
    from sase.ace.patch import iter_patch_project_file_records

    try:
        records = iter_patch_project_file_records()
    except Exception:  # noqa: BLE001 - fall back to parsing on this tick.
        return None
    parts: list[tuple[str, str | None, FileIdentity]] = []
    for record in records:
        identity = _file_identity(record.path)
        if identity is None:
            return None
        parts.append((os.fspath(record.path), record.project_display_name, identity))
    return tuple(parts)


class TickContextWriter:
    """Write one routine's tick files, skipping work whose inputs are unchanged.

    ``load_all_patches`` parses and candidate-filters every Patch; it runs only
    when the ProjectSpec fingerprint changed. ``filter_patches`` applies the
    edit-lock and query filters and runs on every Patch-serializing tick,
    because edit locks are not part of the fingerprint.
    """

    def __init__(
        self,
        tick_dir: Path,
        *,
        load_all_patches: Callable[[], list[Patch]],
        filter_patches: Callable[[list[Patch]], list[Patch]],
        fingerprint_fn: Callable[[], PatchFingerprint | None] | None = None,
    ) -> None:
        self.tick_dir = tick_dir
        self.all_patches_file = str(tick_dir / "all_changespecs.json")
        self.filtered_patches_file = str(tick_dir / "filtered_changespecs.json")
        self.context_file = str(tick_dir / "context.json")
        self._load_all_patches = load_all_patches
        self._filter_patches = filter_patches
        self._fingerprint_fn = fingerprint_fn
        self._fingerprint: PatchFingerprint | None = None
        self._all_patches: list[Patch] = []
        # path -> (content key, on-disk identity right after our write)
        self._written: dict[str, tuple[object, FileIdentity]] = {}

    def write(
        self,
        build_context: Callable[[str, str], ChopScriptContext],
        *,
        include_patches: bool,
    ) -> str:
        """Refresh the tick files and return the context path.

        ``build_context`` receives the Patch file paths, which are empty
        strings when *include_patches* is false.
        """
        all_file = filtered_file = ""
        if include_patches:
            all_file, filtered_file = self.all_patches_file, self.filtered_patches_file
            all_patches, fingerprint = self._current_patches()
            filtered = self._filter_patches(all_patches)
            positions = _positions(all_patches, filtered)
            filtered_key = (
                None
                if fingerprint is None or positions is None
                else (fingerprint, positions)
            )
            self._write_if_changed(
                all_file, fingerprint, lambda: serialize_patches(all_patches, all_file)
            )
            self._write_if_changed(
                filtered_file,
                filtered_key,
                lambda: serialize_patches(filtered, filtered_file),
            )
        ctx = build_context(all_file, filtered_file)
        self._write_if_changed(
            self.context_file,
            asdict(ctx),
            lambda: write_chop_context(ctx, self.context_file),
        )
        return self.context_file

    def _current_patches(self) -> tuple[list[Patch], PatchFingerprint | None]:
        fingerprint_fn = self._fingerprint_fn or _patch_files_fingerprint
        fingerprint = fingerprint_fn()
        if fingerprint is not None and fingerprint == self._fingerprint:
            return self._all_patches, fingerprint
        patches = self._load_all_patches()
        self._fingerprint = fingerprint
        self._all_patches = patches
        return patches, fingerprint

    def _write_if_changed(
        self,
        path: str,
        key: object,
        write_fn: Callable[[], None],
    ) -> None:
        prior = self._written.get(path)
        if (
            key is not None
            and prior is not None
            and prior[0] == key
            and _file_identity(path) == prior[1]
        ):
            return
        write_fn()
        identity = _file_identity(path)
        if key is None or identity is None:
            self._written.pop(path, None)
        else:
            self._written[path] = (key, identity)


def _positions(
    all_patches: list[Patch], filtered: list[Patch]
) -> tuple[int, ...] | None:
    """Return *filtered*'s positions in *all_patches*, or None if not a subset."""
    index = {id(patch): position for position, patch in enumerate(all_patches)}
    positions: list[int] = []
    for patch in filtered:
        position = index.get(id(patch))
        if position is None:
            return None
        positions.append(position)
    return tuple(positions)
