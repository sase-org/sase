"""Synchronous upload and mutation-registered post-commit uploads."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Public helpers from sibling modules resolve through the ``upload`` facade
# at call time, so monkeypatching ``sase.bead.attachments.upload.<name>``
# keeps working after the split.


def upload_wires_now(
    wires: list[dict[str, Any]],
    stores: dict[str, Any],
    tiers: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Upload *wires* through their tier stores, returning digest → seconds.

    *stores* maps tier names to stores; wires route via the core placement
    policy (a single store also works when every wire lands on its tier).
    Each object draws a TTY progress bar above 8 MiB.
    """
    from sase.bead.attachments import upload
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.progress import transfer_progress
    from sase.bead.attachments.store import LocalAttachmentStore
    from sase.bead.config import get_attachment_git_max_bytes

    if tiers is None:
        tiers = upload.placement_tiers(
            stores, git_max_bytes=get_attachment_git_max_bytes()
        )
    grouped = upload.split_wires_by_tier(wires, tiers)
    local = LocalAttachmentStore()
    elapsed: dict[str, float] = {}
    for tier_name, tier_wires in grouped.items():
        store = stores.get(tier_name)
        if store is None:
            raise BlobStoreError(f"no reachable {tier_name} store for upload")
        for wire in tier_wires:
            digest = str(wire.get("sha256") or wire.get("digest") or "")
            size = int(wire.get("size_bytes") or 0)
            name = str(wire.get("name") or digest[:12])
            src = local.object_path(digest)
            started = time.monotonic()
            try:
                with transfer_progress(
                    f"{name} → {store.describe()}", size
                ) as progress:
                    try:
                        mime = wire.get("mime_type")
                        mime_arg = str(mime) if isinstance(mime, str) and mime else None
                        if tier_name == "public":
                            store.put(
                                digest, src, size, progress=progress, mime_type=mime_arg
                            )
                        else:
                            store.put(digest, src, size, progress=progress)
                    except TypeError:
                        store.put(digest, src, size, progress=progress)
            except BlobStoreError:
                raise
            except Exception as exc:
                raise BlobStoreError(str(exc)) from exc
            elapsed[digest] = time.monotonic() - started
    return elapsed


def queue_pending_upload(
    mutation: Any,
    wires: list[dict[str, Any]],
    *,
    store_name: str,
    store_repo: str,
    store_label: str,
    project_key: str,
    echo_rows: list[str] | None = None,
    background: bool = False,
) -> None:
    """Register *wires* for post-commit upload on *mutation*.

    *store_name* is the tier (``git`` or ``large``) so the post-commit
    runner rebuilds the right store. *background* marks entries the
    detached worker drains instead of the inline post-commit upload.
    """
    pending = getattr(mutation, "pending_attachment_uploads", None)
    if pending is None:
        pending = []
        mutation.pending_attachment_uploads = pending
    for wire in wires:
        digest = str(wire.get("sha256") or wire.get("digest") or "")
        if not digest:
            continue
        mime_value = wire.get("mime_type")
        mime_str = (
            str(mime_value) if isinstance(mime_value, str) and mime_value else None
        )
        item: dict[str, object] = {
            "digest": digest,
            "size_bytes": int(wire.get("size_bytes") or 0),
            "store_name": store_name,
            "store_repo": store_repo,
            "store_label": store_label,
            "project_key": project_key,
            "background": background,
        }
        if mime_str:
            item["mime_type"] = mime_str
        pending.append(item)
    if echo_rows is not None:
        mutation.pending_attachment_echo_rows = echo_rows
        mutation.pending_attachment_wires = list(wires)


def _store_for_pending_item(item: dict[str, Any]) -> Any | None:
    """Rebuild the tier store for one queued upload item, if reachable."""
    from sase.bead.attachments import upload

    store_name = str(item.get("store_name") or "git")
    if store_name == "large":
        try:
            return upload.discover_large_store(None)
        except Exception:
            return None
    if store_name == "public":
        repo = str(item.get("store_repo") or "")
        if not repo:
            try:
                return upload.discover_public_store(None)
            except Exception:
                return None
        label = str(item.get("store_label") or "")
        project_key = str(item.get("project_key") or "")
        try:
            from sase.bead.attachments.git_store import GitAttachmentStore

            return GitAttachmentStore(
                repo,
                label or f"{project_key}--attachments (public)",
                name="public",
                layout="public",
            )
        except Exception:
            return None
    repo = str(item.get("store_repo") or "")
    label = str(item.get("store_label") or "")
    project_key = str(item.get("project_key") or "")
    if not repo:
        return None
    try:
        from sase.bead.attachments.git_store import GitAttachmentStore

        return GitAttachmentStore(repo, label or f"{project_key} (private)")
    except Exception:
        return None


def run_pending_uploads(mutation: Any) -> None:
    """Upload mutation-registered digests; failures queue to the outbox.

    Items marked ``background`` skip the inline upload: they move to the
    durable outbox and a detached worker drains them, so the command
    returns promptly.
    """
    from sase.bead.attachments import upload

    pending = list(getattr(mutation, "pending_attachment_uploads", None) or [])
    if not pending:
        return
    mutation.pending_attachment_uploads = []
    echo_rows = getattr(mutation, "pending_attachment_echo_rows", None)
    wires = list(getattr(mutation, "pending_attachment_wires", None) or [])
    by_digest: dict[str, dict[str, Any]] = {}
    for wire in wires:
        digest = str(wire.get("sha256") or wire.get("digest") or "")
        if digest:
            by_digest[digest] = wire
    from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox
    from sase.bead.attachments.progress import transfer_progress
    from sase.bead.attachments.store import LocalAttachmentStore
    from sase.config import get_machine_name

    try:
        origin = get_machine_name() or None
    except Exception:
        origin = None
    local = LocalAttachmentStore()
    elapsed: dict[str, float] = {}
    failed: dict[str, str] = {}
    background_digests: set[str] = set()
    background_projects: set[str] = set()
    labels: dict[str, str] = {}
    for item in pending:
        digest = str(item.get("digest") or "")
        size = int(item.get("size_bytes") or 0)
        project_key = str(item.get("project_key") or "")
        store_name = str(item.get("store_name") or "git")
        if not digest or not project_key:
            continue
        labels[digest] = str(item.get("store_label") or "")
        item_mime = item.get("mime_type")
        item_mime_str = (
            str(item_mime) if isinstance(item_mime, str) and item_mime else None
        )
        if item_mime_str is None:
            wire_hint = by_digest.get(digest)
            hint_mime = (wire_hint or {}).get("mime_type") if wire_hint else None
            if isinstance(hint_mime, str) and hint_mime:
                item_mime_str = hint_mime
        if item.get("background"):
            _enqueue_failed(
                project_key,
                digest,
                size,
                origin,
                store_name=store_name,
                mime_type=item_mime_str,
            )
            background_digests.add(digest)
            background_projects.add(project_key)
            continue
        src = local.object_path(digest)
        if not src.is_file():
            continue
        store = _store_for_pending_item(item)
        if store is None:
            log.warning("attachment upload skipped: no reachable store")
            failed[digest] = project_key
            _enqueue_failed(
                project_key,
                digest,
                size,
                origin,
                store_name=store_name,
                mime_type=item_mime_str,
            )
            continue
        started = time.monotonic()
        try:
            wire = by_digest.get(digest)
            name = str((wire or {}).get("name") or digest[:12])
            with transfer_progress(f"{name} → {store.describe()}", size) as progress:
                try:
                    if store_name == "public":
                        store.put(
                            digest,
                            src,
                            size,
                            progress=progress,
                            mime_type=item_mime_str,
                        )
                    else:
                        store.put(digest, src, size, progress=progress)
                except TypeError:
                    store.put(digest, src, size, progress=progress)
        except Exception as exc:
            if getattr(exc, "secret_scan", False):
                try:
                    from sase.bead.attachments.upload.secret_scan import (
                        handle_secret_scan_rejection,
                    )
                except Exception:
                    handle_secret_scan_rejection = None  # type: ignore[assignment]
                if handle_secret_scan_rejection is not None:
                    try:
                        from sase.bead.attachments.outbox import OutboxEntry

                        handle_secret_scan_rejection(
                            project_key,
                            OutboxEntry(
                                digest=digest,
                                size_bytes=size,
                                store=store_name,
                                origin=origin,
                                mime_type=item_mime_str,
                            ),
                            store,
                            str(exc),
                        )
                    except Exception:
                        pass
                else:
                    log.warning("attachment upload of %s… failed: %s", digest[:12], exc)
                    failed[digest] = project_key
                    _enqueue_failed(
                        project_key,
                        digest,
                        size,
                        origin,
                        store_name=store_name,
                        mime_type=item_mime_str,
                    )
                continue
            log.warning("attachment upload of %s… failed: %s", digest[:12], exc)
            failed[digest] = project_key
            _enqueue_failed(
                project_key,
                digest,
                size,
                origin,
                store_name=store_name,
                mime_type=item_mime_str,
            )
            continue
        elapsed[digest] = time.monotonic() - started
    if background_digests:
        from sase.bead.attachments.background import (
            launch_background_drain,
            rewrite_echo_for_background,
        )

        for background_project in sorted(background_projects):
            launch_background_drain(background_project)
        if echo_rows is not None:
            background_wires = [
                wire
                for wire in wires
                if str(wire.get("sha256") or wire.get("digest") or "")
                in background_digests
            ]
            rewrite_echo_for_background(echo_rows, background_wires)
    if echo_rows is not None and wires:
        label = next((value for value in labels.values() if value), "")
        foreground_wires = [
            wire
            for wire in wires
            if str(wire.get("sha256") or wire.get("digest") or "")
            not in background_digests
        ]
        upload.rewrite_echo_for_upload(
            echo_rows,
            foreground_wires,
            label=label,
            elapsed=elapsed,
            pending=set(failed),
        )
    _ = enqueue_outbox
    _ = OutboxEntry


def _enqueue_failed(
    project_key: str,
    digest: str,
    size_bytes: int,
    origin: str | None,
    *,
    store_name: str = "git",
    mime_type: str | None = None,
) -> None:
    from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox

    try:
        enqueue_outbox(
            project_key,
            [
                OutboxEntry(
                    digest=digest,
                    size_bytes=size_bytes,
                    store=store_name,
                    origin=origin,
                    mime_type=mime_type,
                )
            ],
        )
    except (OSError, ValueError) as exc:
        log.warning("attachment outbox enqueue failed: %s", exc)


__all__ = [
    "queue_pending_upload",
    "run_pending_uploads",
    "upload_wires_now",
]
