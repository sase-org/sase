"""Background uploads for large bead attachments.

Objects at or above ``bead.attachments.background_upload_min_bytes`` are
never uploaded inline: the write command queues them in the durable
outbox and launches a detached drain worker (the same
:func:`detach_scope` pattern as the async bead-push worker), so the
command returns promptly. The echo carries
``⇡ uploading in background (<size>) — sase bead attachment push`` and
``sase bead attachment push`` drains the same queue with live progress.

The outbox is the crash recovery: a worker that dies mid-drain leaves
its entries queued, and the next ``push``, sync drain, or worker launch
picks them up. ``python -m sase.bead.attachments.background <key>`` is
the worker entry point.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WORKER_DESCRIPTION = "SASE attachment background upload"
WORKER_UNIT_PREFIX = "sase-attachment-upload"
WORKER_DRAIN_SECONDS = 1800.0


def should_background(size_bytes: int) -> bool:
    """Return whether *size_bytes* uploads in the background worker."""
    try:
        from sase.bead.config import get_attachment_background_upload_min_bytes

        threshold = get_attachment_background_upload_min_bytes()
    except Exception:
        threshold = 67108864
    try:
        return int(size_bytes) >= int(threshold)
    except (TypeError, ValueError):
        return False


def _format_background_size(size_bytes: int) -> str:
    """Format a byte count the way the background echo does (up to GiB)."""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):g} MiB"
    return f"{size_bytes / (1024 * 1024 * 1024):g} GiB"


def rewrite_echo_for_background(
    echo_rows: list[str],
    wires: list[dict[str, Any]],
) -> None:
    """Mark write-echo rows as background-queued with the push hint."""
    by_name: dict[str, dict[str, Any]] = {}
    for wire in wires:
        name = str(wire.get("name") or "")
        if name:
            by_name[name] = wire
    for index, row in enumerate(list(echo_rows)):
        if row.startswith("hint: "):
            continue
        matched: dict[str, Any] | None = None
        for name, wire in by_name.items():
            if name in row:
                matched = wire
                break
        if matched is None:
            continue
        size = int(matched.get("size_bytes") or 0)
        echo_rows[index] = (
            f"{row} ⇡ uploading in background ({_format_background_size(size)}) "
            "— sase bead attachment push"
        )


def _background_log_path(project_key: str) -> Path:
    """Return the worker log path for *project_key* (appended, never truncated)."""
    from sase.core.paths import sase_projects_dir, validate_sase_project_name

    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / "attachment-background-upload.log"


def launch_background_drain(project_key: str) -> int | None:
    """Start a detached outbox-drain worker; return its pid, if started.

    Never raises: a launch failure only warns and the durable outbox keeps
    the entries for the next push or sync drain.
    """
    try:
        from sase.detach_scope import detach_scope

        log_path = _background_log_path(project_key)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        launch = detach_scope(
            [
                sys.executable,
                "-m",
                "sase.bead.attachments.background",
                project_key,
            ],
            description=WORKER_DESCRIPTION,
            unit_prefix=WORKER_UNIT_PREFIX,
        )
        with open(log_path, "a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                launch.argv,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=launch.start_new_session,
            )
        return process.pid
    except Exception as exc:
        log.warning("attachment background drain launch failed: %s", exc)
        return None


def _discover_stores_for_drain(project_key: str) -> list[Any]:
    """Return every reachable shared store for *project_key*, git first.

    Discovery resolves from the inherited cwd (the worker starts in the
    project that queued the uploads); *project_key* names the outbox.
    """
    stores: list[Any] = []
    try:
        from sase.bead.attachments.upload import (
            discover_large_store,
            discover_shared_store,
        )

        git_store = discover_shared_store(None)
        if git_store is not None:
            stores.append(git_store)
        large_store = discover_large_store(None)
        if large_store is not None:
            stores.append(large_store)
    except Exception as exc:
        log.warning("attachment background store discovery failed: %s", exc)
    return stores


def drain_project_outbox(
    project_key: str,
    *,
    time_bound_seconds: float = WORKER_DRAIN_SECONDS,
    only_digests: set[str] | None = None,
    progress: bool = False,
    stores: list[Any] | None = None,
) -> tuple[int, int]:
    """Drain *project_key*'s outbox through every reachable store.

    Returns ``(drained, remaining)``. With *progress*, each object draws a
    TTY bar (``push``); the worker passes False and stays quiet. *stores*
    overrides discovery (scoped ``push`` already resolved them). Never
    raises: failures stay queued and are only logged.
    """
    from sase.bead.attachments.outbox import drain_outbox, read_outbox

    try:
        queued = len(read_outbox(project_key))
    except (OSError, ValueError):
        queued = 0
    if queued == 0:
        return (0, 0)
    if stores is None:
        stores = _discover_stores_for_drain(project_key)
    if not stores:
        return (0, queued)
    drained_total = 0
    remaining = queued
    for store in stores:
        try:
            if progress:
                drained, remaining = _drain_with_progress(
                    project_key,
                    store,
                    time_bound_seconds=time_bound_seconds,
                    only_digests=only_digests,
                )
            else:
                drained, remaining = drain_outbox(
                    project_key,
                    store,
                    time_bound_seconds=time_bound_seconds,
                    only_digests=only_digests,
                )
        except Exception as exc:
            log.warning("attachment background drain failed: %s", exc)
            continue
        drained_total += drained
        if remaining == 0:
            break
    return (drained_total, remaining)


def _drain_with_progress(
    project_key: str,
    store: Any,
    *,
    time_bound_seconds: float,
    only_digests: set[str] | None,
) -> tuple[int, int]:
    """Drain one store with a live TTY bar per object; never raises."""
    import time as _time

    from sase.bead.attachments.outbox import read_outbox, remove_outbox_digests
    from sase.bead.attachments.progress import transfer_progress
    from sase.bead.attachments.store import LocalAttachmentStore

    deadline = _time.monotonic() + max(0.0, time_bound_seconds)
    try:
        entries = read_outbox(project_key)
    except (OSError, ValueError) as exc:
        log.warning("attachment outbox drain skipped: %s", exc)
        return (0, 0)
    targets = [
        entry
        for entry in entries
        if (only_digests is None or entry.digest in only_digests)
        and getattr(store, "name", "git") == entry.store
    ]
    if not targets:
        return (0, len(entries))
    local = LocalAttachmentStore()
    drained: list[str] = []
    for entry in targets:
        if _time.monotonic() >= deadline:
            break
        src = local.object_path(entry.digest)
        if not src.is_file():
            continue
        label = f"{entry.digest[:12]}… → {store.describe()}"
        try:
            with transfer_progress(label, entry.size_bytes) as bar:
                store.put(entry.digest, src, entry.size_bytes, progress=bar)
        except Exception as exc:
            log.warning(
                "attachment outbox upload of %s… failed: %s",
                entry.digest[:12],
                exc,
            )
            continue
        drained.append(entry.digest)
    if drained:
        try:
            remaining = remove_outbox_digests(project_key, drained)
            return (len(drained), len(remaining))
        except (OSError, ValueError) as exc:
            log.warning("attachment outbox drain cleanup failed: %s", exc)
            return (0, len(entries))
    return (0, len(entries))


def main(argv: list[str]) -> int:
    """Drain one project's outbox; the detached worker entry point."""
    if len(argv) != 1 or not argv[0].strip():
        print(
            "usage: python -m sase.bead.attachments.background <project-key>",
            file=sys.stderr,
        )
        return 2
    project_key = argv[0].strip()
    try:
        drained, remaining = drain_project_outbox(project_key)
    except Exception as exc:
        print(f"attachment background drain failed: {exc}", file=sys.stderr)
        return 1
    print(f"drained {drained} attachment(s); {remaining} queued.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


__all__ = [
    "_background_log_path",
    "_discover_stores_for_drain",
    "drain_project_outbox",
    "_format_background_size",
    "launch_background_drain",
    "main",
    "rewrite_echo_for_background",
    "should_background",
]
