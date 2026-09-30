"""Project-key and shared-store discovery for attachment uploads."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# Public helpers from sibling modules resolve through the ``upload`` facade
# at call time, so monkeypatching ``sase.bead.attachments.upload.<name>``
# keeps working after the split.


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
    from sase.bead.attachments import upload

    project_key = upload.resolve_project_key(bead_context)
    if not project_key:
        return None
    clone = upload.hidden_clone_path(project_key)
    if clone is None or not clone.is_dir():
        return None
    if not (clone / "HEAD").is_file() or not (clone / "objects").is_dir():
        return None
    if not upload.clone_has_remote(clone):
        return None
    try:
        from sase.bead.attachments.git_store import GitAttachmentStore
    except Exception:
        return None
    label = upload.describe_label(clone, project_key)
    try:
        return GitAttachmentStore(clone, label)
    except Exception:
        return None


def discover_shared_store_with_meta(
    bead_context: Any | None = None,
) -> tuple[Any | None, str | None, str | None]:
    """Return ``(store, repo_path, project_key)``; Nones when no store."""
    from sase.bead.attachments import upload

    project_key = upload.resolve_project_key(bead_context)
    if not project_key:
        return (None, None, None)
    clone = upload.hidden_clone_path(project_key)
    if clone is None or not clone.is_dir():
        return (None, None, project_key)
    if not (clone / "HEAD").is_file() or not (clone / "objects").is_dir():
        return (None, None, project_key)
    if not upload.clone_has_remote(clone):
        return (None, None, project_key)
    try:
        from sase.bead.attachments.git_store import GitAttachmentStore
    except Exception:
        return (None, None, project_key)
    label = upload.describe_label(clone, project_key)
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
    from sase.bead.attachments import upload

    stores: dict[str, Any] = {}
    try:
        git_store = upload.discover_shared_store(bead_context)
    except Exception:
        git_store = None
    if git_store is not None:
        stores["git"] = git_store
    try:
        large_store = upload.discover_large_store(bead_context)
    except Exception:
        large_store = None
    if large_store is not None:
        stores["large"] = large_store
    return stores


__all__ = [
    "clone_has_remote",
    "describe_label",
    "discover_large_store",
    "discover_shared_store",
    "discover_shared_store_with_meta",
    "discover_stores",
    "hidden_clone_path",
    "resolve_project_key",
]
