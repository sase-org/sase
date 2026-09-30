"""Permanent handling for secret-scanning push rejections (GH013)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def handle_secret_scan_rejection(
    project_key: str,
    entry: Any,
    store: Any,
    message: str,
) -> None:
    """Reset the ref, block the outbox row, keep a private copy, narrow notes."""
    del message
    digest = str(getattr(entry, "digest", "") or "")
    store_name = str(getattr(entry, "store", "git") or "git")
    if not digest or not project_key:
        return
    _reset_store_ref(store)
    try:
        from sase.bead.attachments.outbox import mark_outbox_blocked

        mark_outbox_blocked(project_key, digest, store_name)
    except Exception as exc:
        log.warning("secret-scan outbox block skipped: %s", exc)
    if store_name == "public":
        _copy_to_private_store(project_key, entry, store)
        _narrow_note_descriptors(digest)
    print(
        "⛔ blocked by secret scanning — stored privately",
        flush=True,
    )


def _reset_store_ref(store: Any) -> None:
    """Reset a git store's branch ref to the remote tip."""
    try:
        repo = getattr(store, "_repo", None)
        if repo is None:
            return
        from pathlib import Path

        repo_path = Path(repo)
        branch = "main"
        try:
            branch = str(store._branch()) if hasattr(store, "_branch") else "main"
        except Exception:
            branch = "main"
        ref = f"refs/heads/{branch}"
        try:
            fetched = (
                store._fetch_head_tip() if hasattr(store, "_fetch_head_tip") else None
            )
        except Exception:
            fetched = None
        if not fetched:
            try:
                if hasattr(store, "_fetch_now"):
                    store._fetch_now(branch)
                fetched = (
                    store._fetch_head_tip()
                    if hasattr(store, "_fetch_head_tip")
                    else None
                )
            except Exception:
                fetched = None
        if not fetched:
            try:
                fetched = (
                    store._tracking_tip(branch)
                    if hasattr(store, "_tracking_tip")
                    else None
                )
            except Exception:
                fetched = None
        if not fetched:
            try:
                fetched = store._tip(branch) if hasattr(store, "_tip") else None
            except Exception:
                fetched = None
        if not fetched:
            return
        try:
            from sase.bead.attachments.git_store.plumbing import update_ref

            update_ref(repo_path, ref, fetched)
        except Exception as exc:
            log.warning("secret-scan ref reset skipped: %s", exc)
    except Exception as exc:
        log.warning("secret-scan ref reset skipped: %s", exc)


def _copy_to_private_store(project_key: str, entry: Any, store: Any) -> None:
    """Copy rejected public bytes to the private store directly."""
    _ = project_key
    try:
        from sase.bead.attachments.store import LocalAttachmentStore
        from sase.bead.attachments.upload import discover_shared_store

        digest = str(getattr(entry, "digest", "") or "")
        size = int(getattr(entry, "size_bytes", 0) or 0)
        if not digest:
            return
        private = discover_shared_store(None)
        if private is None:
            return
        local = LocalAttachmentStore()
        src = local.object_path(digest)
        if not src.is_file():
            return
        try:
            private.put(digest, src, size)
        except Exception as exc:
            log.warning("secret-scan private copy failed: %s", exc)
    except Exception as exc:
        log.warning("secret-scan private copy skipped: %s", exc)


def _narrow_note_descriptors(digest: str) -> None:
    """Narrow every note descriptor for *digest* to private, leaving +1 alone."""
    try:
        from sase.bead.cli_common import get_project, get_read_view
        from sase.bead.note_codec import attachment_to_dict
        from sase.bead.model import Status
    except Exception as exc:
        log.warning("secret-scan descriptor narrowing skipped: %s", exc)
        return
    try:
        with get_read_view() as view:
            issues = view.list_issues(
                statuses=[
                    Status.OPEN,
                    Status.CLAIMED,
                    Status.READY,
                    Status.SNOOZED,
                    Status.IN_PROGRESS,
                    Status.CLOSED,
                ],
            )
            targets: list[tuple[str, int, str, list[dict[str, Any]]]] = []
            for issue in issues:
                issue_id = str(getattr(issue, "id", "") or "")
                for ordinal, note in enumerate(
                    getattr(issue, "notes", ()) or (), start=1
                ):
                    attachments = list(getattr(note, "attachments", ()) or ())
                    if not any(
                        str(getattr(att, "sha256", "") or "") == digest
                        for att in attachments
                    ):
                        continue
                    manifest: list[dict[str, Any]] = []
                    changed = False
                    for att in attachments:
                        try:
                            wire = dict(attachment_to_dict(att))
                        except Exception:
                            continue
                        if str(wire.get("sha256") or "") == digest:
                            if wire.get("visibility") != "private":
                                wire["visibility"] = "private"
                                changed = True
                        manifest.append(wire)
                    if changed:
                        targets.append(
                            (
                                issue_id,
                                ordinal,
                                str(getattr(note, "text", "") or ""),
                                manifest,
                            )
                        )
    except Exception as exc:
        log.warning("secret-scan descriptor scan skipped: %s", exc)
        return
    for issue_id, ordinal, text, manifest in targets:
        try:
            project = get_project()
            project.edit_note(issue_id, ordinal, text, attachments=manifest)
        except Exception as exc:
            log.warning("secret-scan descriptor narrowing failed: %s", exc)
            continue


__all__ = ["handle_secret_scan_rejection"]
