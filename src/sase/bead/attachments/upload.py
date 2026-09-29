"""Placement, pre-publication upload, and outbox drain for attachments.

Placement uses the core ``attachment_placement`` policy with the single git
tier; Python owns I/O. Uploads run after the bead commit and before bead
publication (``bead_store_mutation``), with a durable outbox that
``attachment push`` and bead sync drain.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class AttachmentTooLargeError(ValueError):
    """An attachment exceeds the git tier and ``-L`` was not accepted."""


class AttachmentStoreMissingError(ValueError):
    """``require_upload`` needs a shared store but none exists."""


def resolve_project_key(bead_context: Any | None = None) -> str | None:
    """Return the project key for outbox/store paths, if determinable."""
    key = getattr(bead_context, "project_key", None)
    if isinstance(key, str) and key:
        return key
    marker_key = _project_key_from_checkout_marker()
    if marker_key:
        return marker_key
    try:
        from sase.bead.project_name import infer_project_name_from_cwd
    except Exception:
        return None
    try:
        return infer_project_name_from_cwd()
    except Exception:
        return None


def _project_key_from_checkout_marker() -> str | None:
    """Return the managed-checkout marker key for the cwd, if present."""
    try:
        from sase.workspace_provider.marker import read_marker
    except Exception:
        return None
    try:
        current = Path.cwd().resolve()
    except OSError:
        return None
    for candidate in (current, *current.parents):
        try:
            marker = read_marker(str(candidate))
        except Exception:
            continue
        if marker is not None and marker.project_key:
            return marker.project_key
    return None


def hidden_clone_path(project_key: str) -> Path | None:
    try:
        from sase._linked_repo_paths import hidden_sidecar_clone_dir
        from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    except Exception:
        return None
    try:
        return Path(
            hidden_sidecar_clone_dir(project_key, ATTACHMENTS_PRIVATE_SIDECAR_ROLE)
        )
    except (ValueError, OSError):
        return None


def clone_has_remote(clone: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=clone,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool((result.stdout or "").strip())


def describe_label(clone: Path, project_key: str) -> str:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=clone,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        remote = (result.stdout or "").strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        remote = ""
    if remote:
        try:
            from sase._git_remote import parse_hosted_git_remote
        except Exception:
            parse_hosted_git_remote = None  # type: ignore[assignment]
        if parse_hosted_git_remote is not None:
            try:
                parsed = parse_hosted_git_remote(remote)
            except Exception:
                parsed = None
            if parsed is not None and "/" in parsed.repo:
                return f"{parsed.repo} (private)"
    return f"{project_key}--attachments-private (private)"


def discover_shared_store(bead_context: Any | None = None) -> Any | None:
    """Return a ``GitAttachmentStore`` when the hidden clone has a remote.

    Returns None when there is no clone, it is not a bare repo, or it has no
    remote. Never raises for a missing store.
    """
    project_key = resolve_project_key(bead_context)
    if not project_key:
        return None
    clone = hidden_clone_path(project_key)
    if clone is None or not clone.is_dir():
        return None
    if not (clone / "HEAD").is_file() or not (clone / "objects").is_dir():
        return None
    if not clone_has_remote(clone):
        return None
    try:
        from sase.bead.attachments.git_store import GitAttachmentStore
    except Exception:
        return None
    label = describe_label(clone, project_key)
    try:
        return GitAttachmentStore(clone, label)
    except Exception:
        return None


def discover_shared_store_with_meta(
    bead_context: Any | None = None,
) -> tuple[Any | None, str | None, str | None]:
    """Return ``(store, repo_path, project_key)``; Nones when no store."""
    project_key = resolve_project_key(bead_context)
    if not project_key:
        return (None, None, None)
    clone = hidden_clone_path(project_key)
    if clone is None or not clone.is_dir():
        return (None, None, project_key)
    if not (clone / "HEAD").is_file() or not (clone / "objects").is_dir():
        return (None, None, project_key)
    if not clone_has_remote(clone):
        return (None, None, project_key)
    try:
        from sase.bead.attachments.git_store import GitAttachmentStore
    except Exception:
        return (None, None, project_key)
    label = describe_label(clone, project_key)
    try:
        return (GitAttachmentStore(clone, label), str(clone), project_key)
    except Exception:
        return (None, None, project_key)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    return f"{size_bytes / (1024 * 1024):g} MiB"


def decide_placement(
    wires: list[dict[str, Any]],
    *,
    local_only: bool,
    store_exists: bool,
    git_max_bytes: int,
    require_upload: bool,
) -> str:
    """Return ``local_only`` | ``no_store`` | ``git`` for *wires*.

    Raises :class:`AttachmentTooLargeError` when a size is rejected and
    ``-L`` was not passed/accepted, and :class:`AttachmentStoreMissingError`
    when ``require_upload`` needs a store that does not exist. On a TTY, an
    oversize prompts y/N to continue local-only.
    """
    if not wires:
        return "git" if store_exists else "no_store"
    if local_only:
        return "local_only"
    if not store_exists:
        if require_upload:
            raise AttachmentStoreMissingError(
                "require_upload is set but no attachments-private shared "
                "store exists on this machine; attachment bytes cannot upload."
            )
        return "no_store"
    from sase.core.rust import require_rust_binding

    placement = require_rust_binding("attachment_placement")
    tiers = [{"name": "git", "max_bytes": git_max_bytes}]
    oversize: dict[str, Any] | None = None
    for wire in wires:
        size = int(wire.get("size_bytes") or 0)
        try:
            placement(size, tiers, False)
        except Exception:
            oversize = wire
            break
    if oversize is None:
        return "git"
    size = int(oversize.get("size_bytes") or 0)
    name = str(oversize.get("name") or "attachment")
    hint = (
        f"attachment {name} is {_format_size(size)} "
        f"(git tier accepts up to {_format_size(git_max_bytes)}); "
        "pass -L/--local-only to keep it on this machine."
    )
    if sys.stdin.isatty():
        try:
            answer = (
                input(f"{hint}\nKeep {name} local-only instead? [y/N] ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer in {"y", "yes"}:
            return "local_only"
        raise AttachmentTooLargeError(hint)
    raise AttachmentTooLargeError(hint)


def prepare_placement(
    wires: list[dict[str, Any]],
    *,
    local_only: bool,
    bead_context: Any | None = None,
) -> tuple[str, Any | None, str | None]:
    """Decide placement, exiting non-zero before any bead write on refusal.

    Returns ``(placement, store, project_key)``. Prints ``Error:`` and exits
    1 when an oversize or missing-store refusal must leave the store
    unchanged.
    """
    from sase.bead.config import (
        get_attachment_git_max_bytes,
        get_attachment_require_upload,
    )

    git_max = get_attachment_git_max_bytes()
    require_upload = get_attachment_require_upload()
    store, _repo, project_key = discover_shared_store_with_meta(bead_context)
    try:
        placement = decide_placement(
            wires,
            local_only=local_only,
            store_exists=store is not None,
            git_max_bytes=git_max,
            require_upload=require_upload,
        )
    except (AttachmentTooLargeError, AttachmentStoreMissingError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return (placement, store, project_key)


def rewrite_echo_for_local(echo_rows: list[str]) -> None:
    """Mark write-echo rows as staying on this machine (local-only/no-store)."""
    for index, row in enumerate(list(echo_rows)):
        if row.startswith("hint: "):
            continue
        if "stayed local on this machine" in row:
            continue
        echo_rows[index] = f"{row} · stayed local on this machine"


def rewrite_echo_for_upload(
    echo_rows: list[str],
    wires: list[dict[str, Any]],
    *,
    label: str,
    elapsed: dict[str, float] | None = None,
    pending: set[str] | None = None,
) -> None:
    """Annotate write-echo rows with the private destination and timing."""
    pending = pending or set()
    elapsed = elapsed or {}
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
        digest = str(matched.get("digest") or matched.get("sha256") or "")
        if digest in pending:
            echo_rows[index] = f"{row} → {label} (private) · pending upload"
        else:
            seconds = elapsed.get(digest)
            if seconds is None:
                echo_rows[index] = f"{row} → {label} (private)"
            else:
                echo_rows[index] = f"{row} → {label} (private) · {seconds:.1f}s"


def upload_wires_now(
    wires: list[dict[str, Any]],
    store: Any,
) -> dict[str, float]:
    """Upload *wires* through *store*, returning digest → elapsed seconds."""
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.store import LocalAttachmentStore

    local = LocalAttachmentStore()
    elapsed: dict[str, float] = {}
    for wire in wires:
        digest = str(wire.get("sha256") or wire.get("digest") or "")
        size = int(wire.get("size_bytes") or 0)
        src = local.object_path(digest)
        started = time.monotonic()
        try:
            store.put(digest, src, size)
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
    store_repo: str,
    store_label: str,
    project_key: str,
    echo_rows: list[str] | None = None,
) -> None:
    """Register *wires* for post-commit upload on *mutation*."""
    pending = getattr(mutation, "pending_attachment_uploads", None)
    if pending is None:
        pending = []
        mutation.pending_attachment_uploads = pending
    for wire in wires:
        digest = str(wire.get("sha256") or wire.get("digest") or "")
        if not digest:
            continue
        pending.append(
            {
                "digest": digest,
                "size_bytes": int(wire.get("size_bytes") or 0),
                "store_repo": store_repo,
                "store_label": store_label,
                "project_key": project_key,
            }
        )
    if echo_rows is not None:
        mutation.pending_attachment_echo_rows = echo_rows
        mutation.pending_attachment_wires = list(wires)


def run_pending_uploads(mutation: Any) -> None:
    """Upload mutation-registered digests; failures queue to the outbox."""
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
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox
    from sase.bead.attachments.store import LocalAttachmentStore
    from sase.config import get_machine_name

    try:
        origin = get_machine_name() or None
    except Exception:
        origin = None
    local = LocalAttachmentStore()
    elapsed: dict[str, float] = {}
    failed: dict[str, str] = {}
    label = str(pending[0].get("store_label") or "")
    for item in pending:
        digest = str(item.get("digest") or "")
        size = int(item.get("size_bytes") or 0)
        repo = str(item.get("store_repo") or "")
        project_key = str(item.get("project_key") or "")
        if not digest or not repo or not project_key:
            continue
        src = local.object_path(digest)
        if not src.is_file():
            continue
        try:
            from sase.bead.attachments.git_store import GitAttachmentStore

            store = GitAttachmentStore(repo, label or f"{project_key} (private)")
        except Exception as exc:
            log.warning("attachment upload skipped: %s", exc)
            failed[digest] = project_key
            _enqueue_failed(project_key, digest, size, origin)
            continue
        started = time.monotonic()
        try:
            store.put(digest, src, size)
        except Exception as exc:
            log.warning("attachment upload of %s… failed: %s", digest[:12], exc)
            failed[digest] = project_key
            _enqueue_failed(project_key, digest, size, origin)
            continue
        elapsed[digest] = time.monotonic() - started
    if echo_rows is not None and wires:
        rewrite_echo_for_upload(
            echo_rows,
            wires,
            label=label,
            elapsed=elapsed,
            pending=set(failed),
        )
    _ = BlobStoreError
    _ = enqueue_outbox


def _enqueue_failed(
    project_key: str, digest: str, size_bytes: int, origin: str | None
) -> None:
    from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox

    try:
        enqueue_outbox(
            project_key,
            [OutboxEntry(digest=digest, size_bytes=size_bytes, origin=origin)],
        )
    except (OSError, ValueError) as exc:
        log.warning("attachment outbox enqueue failed: %s", exc)


def pre_write_upload(
    wires: list[dict[str, Any]],
    echo_rows: list[str],
    *,
    local_only: bool,
    bead_context: Any | None = None,
    attachments_on: bool = True,
) -> tuple[str, Any | None, str | None, bool]:
    """Decide placement and run the pre-write half of the upload protocol.

    Returns ``(placement, store, project_key, require_upload)``. Local-only
    and no-store rows are rewritten in place; ``require_upload`` successes
    are uploaded now and rewritten with the destination. Exits non-zero
    before any bead write on oversize or missing-store refusal.
    """
    from sase.bead.config import get_attachment_require_upload

    if not attachments_on or not wires:
        return ("skip", None, None, False)
    drain_before_upload(bead_context)
    placement, store, project_key = prepare_placement(
        wires,
        local_only=local_only,
        bead_context=bead_context,
    )
    require_upload = get_attachment_require_upload()
    if placement in ("local_only", "no_store"):
        rewrite_echo_for_local(echo_rows)
        return (placement, store, project_key, require_upload)
    if require_upload:
        assert store is not None
        try:
            elapsed = upload_wires_now(wires, store)
        except Exception as exc:
            print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
        rewrite_echo_for_upload(
            echo_rows, wires, label=store.describe(), elapsed=elapsed
        )
        return ("uploaded", store, project_key, require_upload)
    return ("git", store, project_key, require_upload)


def post_write_queue(
    mutation: Any,
    wires: list[dict[str, Any]],
    echo_rows: list[str],
    *,
    placement: str,
    store: Any | None,
    project_key: str | None,
    require_upload: bool,
    attachments_on: bool = True,
) -> None:
    """Register a post-commit upload when placement chose the shared store."""
    if not attachments_on or not wires:
        return
    if placement != "git" or require_upload or store is None:
        return
    if project_key is None:
        project_key = resolve_project_key(None)
        if project_key is None:
            return
    repo = str(getattr(store, "_repo", "") or "")
    if not repo:
        return
    queue_pending_upload(
        mutation,
        wires,
        store_repo=repo,
        store_label=store.describe(),
        project_key=project_key,
        echo_rows=echo_rows,
    )


def drain_before_upload(
    bead_context: Any | None = None,
    *,
    store: Any | None = None,
    time_bound_seconds: float = 5.0,
) -> None:
    """Opportunistically drain the outbox before a new upload; never raises."""
    try:
        project_key = resolve_project_key(bead_context)
        if not project_key:
            return
        active = store if store is not None else discover_shared_store(bead_context)
        if active is None:
            return
        from sase.bead.attachments.outbox import drain_outbox

        drain_outbox(project_key, active, time_bound_seconds=time_bound_seconds)
    except Exception as exc:
        log.warning("attachment outbox opportunistic drain skipped: %s", exc)


def promote_local_only(
    project_key: str,
    store: Any,
    *,
    time_bound_seconds: float = 10.0,
) -> int:
    """Upload local-only objects referenced by current notes, if placeable.

    Returns the count promoted. Objects still rejected by placement stay
    local-only. Never raises.
    """
    deadline = time.monotonic() + max(0.0, time_bound_seconds)
    try:
        from sase.bead.cli_common import get_read_view
        from sase.bead.config import get_attachment_git_max_bytes
        from sase.bead.attachments.outbox import read_outbox
        from sase.bead.attachments.store import LocalAttachmentStore
        from sase.bead.model import Status
        from sase.core.rust import require_rust_binding
    except Exception as exc:
        log.warning("attachment promote skipped: %s", exc)
        return 0
    try:
        git_max = get_attachment_git_max_bytes()
        placement = require_rust_binding("attachment_placement")
        tiers = [{"name": "git", "max_bytes": git_max}]
        try:
            queued = {entry.digest for entry in read_outbox(project_key)}
        except (OSError, ValueError):
            queued = set()
        local = LocalAttachmentStore()
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
        promoted = 0
        for issue in issues:
            if time.monotonic() >= deadline:
                break
            for note in getattr(issue, "notes", ()):
                for attachment in getattr(note, "attachments", ()):
                    if time.monotonic() >= deadline:
                        break
                    digest = str(getattr(attachment, "sha256", "") or "")
                    size = int(getattr(attachment, "size_bytes", 0) or 0)
                    if not digest or digest in queued:
                        continue
                    if not local.has(digest):
                        continue
                    try:
                        if store.has(digest):
                            continue
                    except Exception:
                        continue
                    try:
                        placement(size, tiers, False)
                    except Exception:
                        continue
                    try:
                        store.put(digest, local.object_path(digest), size)
                    except Exception as exc:
                        log.warning(
                            "attachment promote of %s… failed: %s",
                            digest[:12],
                            exc,
                        )
                        continue
                    promoted += 1
        return promoted
    except Exception as exc:
        log.warning("attachment promote skipped: %s", exc)
        return 0


__all__ = [
    "AttachmentStoreMissingError",
    "AttachmentTooLargeError",
    "clone_has_remote",
    "decide_placement",
    "describe_label",
    "discover_shared_store",
    "discover_shared_store_with_meta",
    "drain_before_upload",
    "hidden_clone_path",
    "post_write_queue",
    "pre_write_upload",
    "prepare_placement",
    "promote_local_only",
    "queue_pending_upload",
    "resolve_project_key",
    "rewrite_echo_for_local",
    "rewrite_echo_for_upload",
    "run_pending_uploads",
    "upload_wires_now",
]
