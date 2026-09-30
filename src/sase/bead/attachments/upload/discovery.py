"""Project-key and shared-store discovery for attachment uploads."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

# Public helpers from sibling modules resolve through the ``upload`` facade
# at call time, so monkeypatching ``sase.bead.attachments.upload.<name>``
# keeps working after the split.

_PUBLIC_MATERIALIZATION_ATTEMPTED: set[str] = set()
_PUBLIC_MATERIALIZATION_LOCK = threading.Lock()


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


def _default_role() -> str:
    try:
        from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    except Exception:
        return "attachments-private"
    return ATTACHMENTS_PRIVATE_SIDECAR_ROLE


def _public_role() -> str:
    try:
        from sase.sdd._store_types import ATTACHMENTS_SIDECAR_ROLE
    except Exception:
        return "attachments"
    return ATTACHMENTS_SIDECAR_ROLE


def hidden_clone_path(project_key: str, role: str | None = None) -> Path | None:
    """Return the hidden clone path for *project_key* and *role*."""
    try:
        from sase._linked_repo_paths import hidden_sidecar_clone_dir
        from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    except Exception:
        return None
    resolved_role = role or ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    try:
        return Path(hidden_sidecar_clone_dir(project_key, resolved_role))
    except (ValueError, OSError):
        return None


def _sidecar_entry_for_role(role: str) -> dict[str, Any] | None:
    """Return the merged sidecar entry for *role*, if configured."""
    try:
        from pathlib import Path as _Path

        from sase._linked_repo_config import (
            _SIDECAR_ROLE_KEY,
            merged_sidecar_entries_from_config,
            resolution_config,
        )

        workspace = str(_Path.cwd())
        config = resolution_config(workspace, None)
        for entry in merged_sidecar_entries_from_config(
            config, primary_workspace_dir=workspace
        ):
            entry_role = entry.get(_SIDECAR_ROLE_KEY) or entry.get("role")
            if entry_role == role:
                return dict(entry)
            if entry.get("name") == role:
                return dict(entry)
    except Exception:
        return None
    return None


def role_disabled(role: str) -> bool:
    entry = _sidecar_entry_for_role(role)
    return bool(entry is not None and entry.get("disabled") is True)


def _role_disabled(role: str) -> bool:
    return role_disabled(role)


def _configured_remote_for_role(role: str) -> str | None:
    entry = _sidecar_entry_for_role(role)
    if entry is None:
        return None
    try:
        from sase._linked_repo_config import _SIDECAR_REMOTE_URL_KEY
    except Exception:
        _SIDECAR_REMOTE_URL_KEY = "_sase_sidecar_remote_url"  # type: ignore[assignment]
    for key in (_SIDECAR_REMOTE_URL_KEY, "remote_url"):
        try:
            value = entry.get(key)
        except Exception:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
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


def describe_label(clone: Path, project_key: str, audience: str = "private") -> str:
    """Return the human-readable store label for *clone*."""
    word = "public" if audience == "public" else "private"
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
                return f"{parsed.repo} ({word})"
    if word == "public":
        return f"{project_key}--attachments (public)"
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
    if _role_disabled(_default_role()):
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
    if _role_disabled(_default_role()):
        return (None, None, project_key)
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


def _ensure_public_clone(project_key: str) -> None:
    """Create the public bare clone once per process when it is wanted."""
    try:
        from sase.bead.attachments import upload as _upload

        _clone = _upload.hidden_clone_path(project_key, _public_role())
        _key = str(_clone) if _clone is not None else project_key
    except Exception:
        _key = project_key
    with _PUBLIC_MATERIALIZATION_LOCK:
        if _key in _PUBLIC_MATERIALIZATION_ATTEMPTED:
            return
        _PUBLIC_MATERIALIZATION_ATTEMPTED.add(_key)
    try:
        from sase.bead.attachments import upload

        clone = upload.hidden_clone_path(project_key, _public_role())
        if clone is None:
            return
        if clone.is_dir() and (clone / "HEAD").is_file():
            return
        remote = _configured_remote_for_role(_public_role())
        if not remote:
            return
        try:
            from sase.bead.attachments.remote_visibility import (
                resolve_remote_visibility,
            )
        except Exception:
            return
        try:
            visibility = resolve_remote_visibility(remote)
        except Exception:
            return
        if visibility != "public":
            return
        try:
            from sase.sdd._sidecar_bare import ensure_attachments_bare_clone

            ensure_attachments_bare_clone(clone, remote, role=_public_role())
        except Exception:
            return
    except Exception:
        return


def discover_public_store(bead_context: Any | None = None) -> Any | None:
    """Return the public ``GitAttachmentStore``, materializing it when wanted."""
    from sase.bead.attachments import upload

    project_key = upload.resolve_project_key(bead_context)
    if not project_key:
        return None
    if _role_disabled(_public_role()):
        return None
    _ensure_public_clone(project_key)
    clone = upload.hidden_clone_path(project_key, _public_role())
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
    try:
        label = upload.describe_label(clone, project_key, "public")
    except TypeError:
        label = upload.describe_label(clone, project_key)
    try:
        return GitAttachmentStore(clone, label, name="public", layout="public")
    except Exception:
        return None


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
    """Return every reachable shared store by tier name, public first."""
    from sase.bead.attachments import upload

    stores: dict[str, Any] = {}
    try:
        public_store = upload.discover_public_store(bead_context)
    except Exception:
        public_store = None
    if public_store is not None:
        stores["public"] = public_store
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
    "discover_public_store",
    "discover_shared_store",
    "discover_shared_store_with_meta",
    "discover_stores",
    "hidden_clone_path",
    "resolve_project_key",
]
