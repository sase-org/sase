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


def discover_large_store(bead_context: Any | None = None) -> Any | None:
    """Return a ``RcloneAttachmentStore`` when ``large_store`` is configured.

    Returns None when the config has no remote. Never raises for a missing
    tier; a missing ``rclone`` binary only fails at use time with a clear
    error (and a doctor finding).
    """
    del bead_context  # The large tier is config-addressed, not clone-addressed.
    try:
        from sase.bead.config import get_attachment_large_store
    except Exception:
        return None
    try:
        configured = get_attachment_large_store()
    except Exception:
        return None
    if not configured:
        return None
    try:
        from sase.bead.attachments.rclone_store import RcloneAttachmentStore

        raw_max = configured["max_bytes"]
        max_bytes = (
            raw_max
            if isinstance(raw_max, int) and not isinstance(raw_max, bool)
            else 2147483648
        )
        return RcloneAttachmentStore(
            str(configured["remote"]),
            str(configured["remote"]),
            max_bytes=max_bytes,
        )
    except Exception:
        return None


def discover_stores(bead_context: Any | None = None) -> dict[str, Any]:
    """Return every reachable shared store by tier name, git first."""
    stores: dict[str, Any] = {}
    try:
        git_store = discover_shared_store(bead_context)
    except Exception:
        git_store = None
    if git_store is not None:
        stores["git"] = git_store
    try:
        large_store = discover_large_store(bead_context)
    except Exception:
        large_store = None
    if large_store is not None:
        stores["large"] = large_store
    return stores


def placement_tiers(
    stores: dict[str, Any], *, git_max_bytes: int
) -> list[dict[str, Any]]:
    """Build the ordered core-policy tier list for the reachable *stores*."""
    tiers: list[dict[str, Any]] = []
    if stores.get("git") is not None:
        tiers.append({"name": "git", "max_bytes": git_max_bytes})
    large_store = stores.get("large")
    if large_store is not None:
        try:
            large_max = int(getattr(large_store, "max_bytes", 2147483648))
        except (TypeError, ValueError):
            large_max = 2147483648
        tiers.append({"name": "large", "max_bytes": large_max})
    return tiers


def split_wires_by_tier(
    wires: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Route each wire to its core-policy tier name; raise on oversize.

    Raises :class:`AttachmentTooLargeError` naming the first wire no
    configured tier accepts.
    """
    from sase.core.rust import require_rust_binding

    placement = require_rust_binding("attachment_placement")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for wire in wires:
        size = int(wire.get("size_bytes") or 0)
        try:
            decision = placement(size, tiers, False)
            tier_name = str(decision.get("store"))
        except Exception:
            tier_name = ""
        if not tier_name:
            name = str(wire.get("name") or "attachment")
            raise AttachmentTooLargeError((name, size))
        grouped.setdefault(tier_name, []).append(wire)
    return grouped


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:g} KiB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):g} MiB"
    return f"{size_bytes / (1024 * 1024 * 1024):g} GiB"


def decide_placement(
    wires: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
    *,
    local_only: bool,
    require_upload: bool,
) -> str:
    """Return ``local_only`` | ``no_store`` | a tier name | ``mixed``.

    *tiers* is the ordered reachable-tier list from :func:`placement_tiers`
    (empty when no shared store exists). Raises
    :class:`AttachmentTooLargeError` when a size is rejected and ``-L`` was
    not passed/accepted, and :class:`AttachmentStoreMissingError` when
    ``require_upload`` needs a store that does not exist. On a TTY, an
    oversize prompts y/N to continue local-only.
    """
    if not wires:
        if not tiers:
            return "no_store"
        return str(tiers[0]["name"])
    if local_only:
        return "local_only"
    if not tiers:
        if require_upload:
            raise AttachmentStoreMissingError(
                "require_upload is set but no attachments-private shared "
                "store exists on this machine; attachment bytes cannot upload."
            )
        return "no_store"
    try:
        grouped = split_wires_by_tier(wires, tiers)
    except AttachmentTooLargeError as exc:
        oversize: dict[str, Any] | None = None
        if exc.args and isinstance(exc.args[0], tuple):
            oversize_name, oversize_size = exc.args[0]
            oversize = {"name": oversize_name, "size_bytes": oversize_size}
        if oversize is None:
            oversize = wires[0]
        size = int(oversize.get("size_bytes") or 0)
        name = str(oversize.get("name") or "attachment")
        caps = "; ".join(
            f"{spec['name']} tier accepts up to {_format_size(int(spec['max_bytes']))}"
            for spec in tiers
        )
        hint = (
            f"attachment {name} is {_format_size(size)} ({caps}); "
            "pass -L/--local-only to keep it on this machine."
        )
        if sys.stdin.isatty():
            try:
                answer = (
                    input(f"{hint}\nKeep {name} local-only instead? [y/N] ")
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer in {"y", "yes"}:
                return "local_only"
            raise AttachmentTooLargeError(hint) from exc
        raise AttachmentTooLargeError(hint) from exc
    names = sorted(grouped)
    if len(names) == 1:
        return names[0]
    return "mixed"


def prepare_placement(
    wires: list[dict[str, Any]],
    *,
    local_only: bool,
    bead_context: Any | None = None,
) -> tuple[str, dict[str, Any], str | None]:
    """Decide placement, exiting non-zero before any bead write on refusal.

    Returns ``(placement, stores, project_key)`` where *stores* maps every
    reachable tier name to its store. Prints ``Error:`` and exits 1 when an
    oversize or missing-store refusal must leave the store unchanged.
    """
    from sase.bead.config import (
        get_attachment_git_max_bytes,
        get_attachment_require_upload,
    )

    git_max = get_attachment_git_max_bytes()
    require_upload = get_attachment_require_upload()
    stores = discover_stores(bead_context)
    tiers = placement_tiers(stores, git_max_bytes=git_max)
    try:
        project_key = resolve_project_key(bead_context)
        placement = decide_placement(
            wires,
            tiers,
            local_only=local_only,
            require_upload=require_upload,
        )
    except (AttachmentTooLargeError, AttachmentStoreMissingError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    return (placement, stores, project_key)


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
    stores: dict[str, Any],
    tiers: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Upload *wires* through their tier stores, returning digest → seconds.

    *stores* maps tier names to stores; wires route via the core placement
    policy (a single store also works when every wire lands on its tier).
    Each object draws a TTY progress bar above 8 MiB.
    """
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.progress import transfer_progress
    from sase.bead.attachments.store import LocalAttachmentStore
    from sase.bead.config import get_attachment_git_max_bytes

    if tiers is None:
        tiers = placement_tiers(stores, git_max_bytes=get_attachment_git_max_bytes())
    grouped = split_wires_by_tier(wires, tiers)
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
        pending.append(
            {
                "digest": digest,
                "size_bytes": int(wire.get("size_bytes") or 0),
                "store_name": store_name,
                "store_repo": store_repo,
                "store_label": store_label,
                "project_key": project_key,
                "background": background,
            }
        )
    if echo_rows is not None:
        mutation.pending_attachment_echo_rows = echo_rows
        mutation.pending_attachment_wires = list(wires)


def _store_for_pending_item(item: dict[str, Any]) -> Any | None:
    """Rebuild the tier store for one queued upload item, if reachable."""
    store_name = str(item.get("store_name") or "git")
    if store_name == "large":
        try:
            return discover_large_store(None)
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
        if item.get("background"):
            _enqueue_failed(project_key, digest, size, origin, store_name=store_name)
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
            _enqueue_failed(project_key, digest, size, origin, store_name=store_name)
            continue
        started = time.monotonic()
        try:
            wire = by_digest.get(digest)
            name = str((wire or {}).get("name") or digest[:12])
            with transfer_progress(f"{name} → {store.describe()}", size) as progress:
                store.put(digest, src, size, progress=progress)
        except Exception as exc:
            log.warning("attachment upload of %s… failed: %s", digest[:12], exc)
            failed[digest] = project_key
            _enqueue_failed(project_key, digest, size, origin, store_name=store_name)
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
        rewrite_echo_for_upload(
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
                )
            ],
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
) -> tuple[str, dict[str, Any], str | None, bool]:
    """Decide placement and run the pre-write half of the upload protocol.

    Returns ``(placement, stores, project_key, require_upload)`` where
    *stores* maps every reachable tier name to its store. Local-only and
    no-store rows are rewritten in place; ``require_upload`` successes
    upload now (synchronously, even above the background threshold) and
    are rewritten with the destination. Exits non-zero before any bead
    write on oversize or missing-store refusal.
    """
    from sase.bead.config import get_attachment_require_upload

    if not attachments_on or not wires:
        return ("skip", {}, None, False)
    drain_before_upload(bead_context)
    placement, stores, project_key = prepare_placement(
        wires,
        local_only=local_only,
        bead_context=bead_context,
    )
    require_upload = get_attachment_require_upload()
    if placement in ("local_only", "no_store"):
        rewrite_echo_for_local(echo_rows)
        return (placement, stores, project_key, require_upload)
    if require_upload:
        assert stores
        try:
            elapsed = upload_wires_now(wires, stores)
        except Exception as exc:
            print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
        first_store = next(iter(stores.values()))
        rewrite_echo_for_upload(
            echo_rows, wires, label=first_store.describe(), elapsed=elapsed
        )
        return ("uploaded", stores, project_key, require_upload)
    return (placement, stores, project_key, require_upload)


def _store_identity(tier_name: str, store: Any) -> tuple[str, str]:
    """Return ``(store_repo, store_label)`` for one tier store."""
    if tier_name == "large":
        remote = str(getattr(store, "_remote", "") or store.describe())
        return (remote, store.describe())
    return (str(getattr(store, "_repo", "") or ""), store.describe())


def post_write_queue(
    mutation: Any,
    wires: list[dict[str, Any]],
    echo_rows: list[str],
    *,
    placement: str,
    stores: dict[str, Any] | Any | None,
    project_key: str | None,
    require_upload: bool,
    attachments_on: bool = True,
) -> None:
    """Register a post-commit upload when placement chose a shared store.

    Wires route per tier; wires at or above the background threshold are
    marked for the detached worker instead of the inline post-commit
    upload. *stores* is the tier-name mapping from :func:`pre_write_upload`
    (a single store still works for one-tier placements).
    """
    if not attachments_on or not wires:
        return
    if placement not in ("git", "large", "mixed") or require_upload:
        return
    if not isinstance(stores, dict):
        stores = {"git": stores} if stores is not None else {}
    if not stores:
        return
    if project_key is None:
        project_key = resolve_project_key(None)
        if project_key is None:
            return
    from sase.bead.attachments.background import should_background
    from sase.bead.config import get_attachment_git_max_bytes

    tiers = placement_tiers(stores, git_max_bytes=get_attachment_git_max_bytes())
    try:
        grouped = split_wires_by_tier(wires, tiers)
    except AttachmentTooLargeError as exc:
        log.warning("attachment post-write queue skipped: %s", exc)
        return
    for tier_name, tier_wires in grouped.items():
        store = stores.get(tier_name)
        if store is None:
            continue
        repo, label = _store_identity(tier_name, store)
        if tier_name == "git" and not repo:
            continue
        foreground = [
            wire
            for wire in tier_wires
            if not should_background(int(wire.get("size_bytes") or 0))
        ]
        background_wires = [
            wire
            for wire in tier_wires
            if should_background(int(wire.get("size_bytes") or 0))
        ]
        if foreground:
            queue_pending_upload(
                mutation,
                foreground,
                store_name=tier_name,
                store_repo=repo,
                store_label=label,
                project_key=project_key,
                echo_rows=echo_rows,
            )
        if background_wires:
            queue_pending_upload(
                mutation,
                background_wires,
                store_name=tier_name,
                store_repo=repo,
                store_label=label,
                project_key=project_key,
                echo_rows=echo_rows,
                background=True,
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
        if store is not None:
            actives = [store]
        else:
            actives = list(discover_stores(bead_context).values())
        if not actives:
            return
        from sase.bead.attachments.outbox import drain_outbox

        for active in actives:
            drain_outbox(project_key, active, time_bound_seconds=time_bound_seconds)
    except Exception as exc:
        log.warning("attachment outbox opportunistic drain skipped: %s", exc)


def promote_local_only(
    project_key: str,
    stores: dict[str, Any] | Any,
    *,
    time_bound_seconds: float = 10.0,
) -> int:
    """Upload local-only objects referenced by current notes, if placeable.

    *stores* maps tier names to stores (a single store still means the git
    tier). Each object routes via the core placement policy, so big
    local-only objects promote to the large tier when it is configured.
    Returns the count promoted. Objects still rejected by placement stay
    local-only. Never raises.
    """
    deadline = time.monotonic() + max(0.0, time_bound_seconds)
    if not isinstance(stores, dict):
        stores = {"git": stores} if stores is not None else {}
    if not stores:
        return 0
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
        tiers = placement_tiers(stores, git_max_bytes=git_max)
        if not tiers:
            return 0
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
                        decision = placement(size, tiers, False)
                        tier_name = str(decision.get("store"))
                    except Exception:
                        continue
                    store = stores.get(tier_name)
                    if store is None:
                        continue
                    try:
                        if store.has(digest):
                            continue
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
    "discover_large_store",
    "discover_shared_store",
    "discover_shared_store_with_meta",
    "discover_stores",
    "drain_before_upload",
    "hidden_clone_path",
    "placement_tiers",
    "post_write_queue",
    "pre_write_upload",
    "prepare_placement",
    "promote_local_only",
    "queue_pending_upload",
    "resolve_project_key",
    "rewrite_echo_for_local",
    "rewrite_echo_for_upload",
    "run_pending_uploads",
    "split_wires_by_tier",
    "upload_wires_now",
]
