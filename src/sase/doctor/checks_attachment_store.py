"""Shared-store reachability and outbox backlog check for ``sase doctor``."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_CHECK_ID = "project.attachment_store"
_CHECK_ALIAS = "attachments.store"
_TITLE = "Attachment stores"
_GIT_TIMEOUT_SECONDS = 10


def attachment_store_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the default check for the attachment shared stores."""

    return (
        CheckSpec(
            id=_CHECK_ID,
            group="project",
            title=_TITLE,
            runner=lambda: _check_attachment_store(context),
            aliases=(_CHECK_ALIAS,),
        ),
    )


def _skip(summary: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="SKIP",
        title=_TITLE,
        summary=summary,
    )


def _warn(summary: str, *details: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="WARN",
        title=_TITLE,
        summary=summary,
        details=list(details),
    )


def _resolve_project_key(context: DoctorContext) -> str | None:
    from sase.doctor.checks_project import resolve_current_project_record

    try:
        resolution = resolve_current_project_record(context)
    except Exception:
        return None
    name = resolution.project_name or context.project
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        from sase.core.paths import validate_sase_project_name

        validate_sase_project_name(name.strip())
    except Exception:
        return None
    return name.strip()


def _clone_for_key(project_key: str, role: str | None = None) -> object | None:
    from pathlib import Path

    from sase._linked_repo_paths import hidden_sidecar_clone_dir
    from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE

    resolved = role or ATTACHMENTS_PRIVATE_SIDECAR_ROLE
    try:
        from sase.bead.attachments.upload.discovery import role_disabled

        if role_disabled(resolved):
            return None
    except Exception:
        pass
    try:
        clone = Path(hidden_sidecar_clone_dir(project_key, resolved))
    except (ValueError, OSError):
        return None
    if not clone.is_dir():
        return None
    if not (clone / "HEAD").is_file() or not (clone / "objects").is_dir():
        return None
    return clone


def _tip_branch(clone: object) -> str:
    from pathlib import Path

    repo = Path(str(clone))
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return "main"
    branch = (result.stdout or "").strip() if result.returncode == 0 else ""
    return branch or "main"


def _large_store_result(project_key: str) -> DiagnosticCheck | None:
    """Probe the configured rclone large tier.

    Returns None when no large tier is configured, otherwise an OK or
    WARN check for the tier alone.
    """
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
    remote = str(configured.get("remote") or "")
    try:
        from sase.bead.attachments.rclone_store import rclone_binary
    except Exception:
        rclone_binary = None  # type: ignore[assignment]
    binary = rclone_binary() if rclone_binary is not None else None
    if binary is None:
        return _warn(
            f"large attachment store {remote} for {project_key} is unusable",
            "the rclone binary is not installed; install rclone and "
            "configure the large-store remote per docs/beads.md "
            "(Large-object store).",
        )
    try:
        from sase.sdd._git import network_git_timeout

        probe_timeout = network_git_timeout()
    except Exception:
        probe_timeout = 60.0
    try:
        probed = subprocess.run(
            [binary, "lsjson", "--max-depth", "0", remote],
            check=False,
            capture_output=True,
            text=True,
            timeout=probe_timeout,
        )
    except subprocess.TimeoutExpired:
        return _warn(
            f"large attachment store {remote} for {project_key} is unreachable",
            "bounded rclone lsjson timed out; "
            "attachments above the git tier stay local-only.",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _warn(
            f"large attachment store {remote} for {project_key} is unreachable",
            f"bounded rclone lsjson failed: {exc}",
        )
    if probed.returncode != 0:
        detail = ((probed.stderr or probed.stdout) or "unknown rclone error").strip()
        first = detail.splitlines()[0] if detail else "unknown rclone error"
        return _warn(
            f"large attachment store {remote} for {project_key} is unreachable",
            f"bounded rclone lsjson of {remote} failed: {first}",
        )
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="OK",
        title=_TITLE,
        summary=(f"large attachment store {remote} for {project_key} is reachable"),
    )


def _check_attachment_store(context: DoctorContext) -> DiagnosticCheck:
    """Warn about an unreachable store or a backed-up upload outbox."""
    git_result = _check_git_store_and_outbox(context)
    project_key = _resolve_project_key(context)
    if project_key is None:
        return git_result
    large = _large_store_result(project_key)
    if large is None:
        return git_result
    if large.status != "WARN":
        if "no attachments-private shared store" in git_result.summary:
            return DiagnosticCheck(
                id=git_result.id,
                group=git_result.group,
                status="OK",
                title=git_result.title,
                summary=(
                    f"project {project_key} has no attachments-private git "
                    "store; the rclone large tier is reachable"
                ),
            )
        return git_result
    if git_result.status != "WARN":
        return large
    merged = (
        list(git_result.details or []) + [large.summary] + list(large.details or [])
    )
    return DiagnosticCheck(
        id=git_result.id,
        group=git_result.group,
        status="WARN",
        title=git_result.title,
        summary=git_result.summary,
        details=merged,
    )


def _private_remote_url(clone: object) -> str | None:
    """Return the configured origin URL for a private clone, if any."""
    from pathlib import Path

    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=Path(str(clone)),
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    url = (result.stdout or "").strip()
    return url or None


def _private_store_anonymously_readable(private_clone: object | None) -> bool:
    """Return whether the private store remote answers an anonymous probe."""
    if private_clone is None:
        return False
    url = _private_remote_url(private_clone)
    if not url:
        return False
    try:
        from sase.bead.attachments.remote_visibility import resolve_remote_visibility

        return resolve_remote_visibility(url) == "public"
    except Exception:
        return False


def _push_access_error(clone: object, branch: str) -> str | None:
    """Return a no-push-access detail, or None when a dry-run push succeeds.

    Never raises: timeouts and unexpected git failures are treated as
    unknown (no finding) so offline machines do not go red.
    """
    from pathlib import Path

    try:
        from sase.sdd._git import network_git_timeout

        push_timeout = network_git_timeout()
    except Exception:
        push_timeout = 60.0
    try:
        probed = subprocess.run(
            ["git", "push", "--dry-run", "origin", branch],
            cwd=Path(str(clone)),
            check=False,
            capture_output=True,
            text=True,
            timeout=push_timeout,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        return None
    if probed.returncode == 0:
        return None
    detail = ((probed.stderr or probed.stdout) or "unknown git error").strip()
    lowered = detail.lower()
    auth_markers = (
        "authentication failed",
        "permission denied",
        "repository not found",
        "could not read username",
        "401",
        "403",
        "404",
    )
    if any(marker in lowered for marker in auth_markers):
        first = detail.splitlines()[0] if detail else "push denied"
        return first
    return None


def _store_growth_details() -> list[str]:
    """Return logical/physical byte lines per reachable shared store."""
    try:
        from sase.bead.attachment_doctor import _store_growth_lines

        return list(_store_growth_lines())
    except Exception:
        return []


def _check_git_store_and_outbox(context: DoctorContext) -> DiagnosticCheck:
    """Warn about an unreachable store or a backed-up upload outbox."""
    from sase.sdd._store_types import (
        ATTACHMENTS_PRIVATE_SIDECAR_ROLE,
        ATTACHMENTS_SIDECAR_ROLE,
    )

    project_key = _resolve_project_key(context)
    if project_key is None:
        return _skip("no current project; attachment store check needs one")
    public_clone = _clone_for_key(project_key, ATTACHMENTS_SIDECAR_ROLE)
    clone = _clone_for_key(project_key, ATTACHMENTS_PRIVATE_SIDECAR_ROLE)
    if clone is None and public_clone is None:
        try:
            from sase.bead.config import get_attachment_large_store

            if get_attachment_large_store():
                pass
            else:
                return _skip(
                    f"project {project_key} has no attachments-private shared store; "
                    "attachments stay on this machine"
                )
        except Exception:
            return _skip(
                f"project {project_key} has no attachments-private shared store; "
                "attachments stay on this machine"
            )
    if clone is None and public_clone is not None:
        clone = public_clone
    branch = _tip_branch(clone)
    try:
        from pathlib import Path

        tip = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=Path(str(clone)),
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _warn(
            f"attachments-private store for {project_key} is unreachable",
            f"git rev-parse of the store tip failed: {exc}",
        )
    if tip.returncode != 0 or not (tip.stdout or "").strip():
        return _warn(
            f"attachments-private store for {project_key} has no resolvable tip",
            f"git rev-parse refs/heads/{branch} failed; "
            "the clone may be uninitialized or corrupt.",
        )
    try:
        from sase.sdd._git import network_git_timeout

        fetch_timeout = network_git_timeout()
    except Exception:
        fetch_timeout = 60.0
    try:
        from pathlib import Path

        fetched = subprocess.run(
            ["git", "fetch", "--quiet", "origin", branch],
            cwd=Path(str(clone)),
            check=False,
            capture_output=True,
            text=True,
            timeout=fetch_timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _warn(
            f"attachments-private store for {project_key} is unreachable",
            f"bounded git fetch failed: {exc}",
        )
    if fetched.returncode != 0:
        detail = ((fetched.stderr or fetched.stdout) or "unknown git error").strip()
        return _warn(
            f"attachments-private store for {project_key} is unreachable",
            f"bounded git fetch of {branch} failed: {detail}",
        )
    try:
        from sase.bead.attachments.outbox import read_outbox

        queued = read_outbox(project_key)
    except ValueError as exc:
        return _warn(
            f"attachments-private store for {project_key} is reachable; "
            "the upload outbox is unreadable",
            f"attachment-upload-outbox.json is malformed: {exc}",
        )
    except OSError as exc:
        return _warn(
            f"attachments-private store for {project_key} is reachable; "
            "the upload outbox could not be read",
            f"attachment-upload-outbox.json read failed: {exc}",
        )
    private_clone_for_probe = (
        None
        if clone is None or public_clone is not None and clone is public_clone
        else clone
    )
    try:
        from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE as _priv

        _real_private = _clone_for_key(project_key, _priv)
    except Exception:
        _real_private = None
    if _private_store_anonymously_readable(_real_private):
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="ERROR",
            title=_TITLE,
            summary=(
                f"attachments-private store for {project_key} is anonymously "
                "readable; private bytes are exposed"
            ),
            details=[
                "the private attachments remote answers an unauthenticated "
                "read probe; rotate any exposed bytes and restrict the remote "
                "visibility before using it for private attachments.",
            ],
        )
    growth = _store_growth_details()
    push_detail = _push_access_error(clone, branch)
    _ = private_clone_for_probe
    if queued:
        pending = [e for e in queued if getattr(e, "state", "pending") != "blocked"]
        blocked = [e for e in queued if getattr(e, "state", "pending") == "blocked"]
        if blocked and not pending:
            return _warn(
                f"attachments-private store for {project_key} is reachable; "
                f"{len(blocked)} blocked upload(s) held "
                "(secret-scanning rejection; see outbox)",
                *(
                    [f"{len(blocked)} blocked entries in attachment-upload-outbox.json"]
                    + growth
                    + (
                        [f"no push access to the attachment store: {push_detail}"]
                        if push_detail
                        else []
                    )
                ),
            )
        count = len(pending) if pending else len(queued)
        noun = "upload" if count == 1 else "uploads"
        detail = f"{count} entries in attachment-upload-outbox.json"
        if blocked:
            detail += f"; {len(blocked)} blocked"
        return _warn(
            f"attachments-private store for {project_key} is reachable; "
            f"{count} queued {noun} waiting "
            "(sase bead attachment push drains them)",
            *(
                [detail]
                + growth
                + (
                    [f"no push access to the attachment store: {push_detail}"]
                    if push_detail
                    else []
                )
            ),
        )
    if push_detail:
        return _warn(
            f"attachments-private store for {project_key} is reachable; "
            "writers have no push access",
            *([f"no push access to the attachment store: {push_detail}"] + growth),
        )
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="OK",
        title=_TITLE,
        summary=(
            f"attachments-private store for {project_key} is reachable "
            "and the upload outbox is empty"
        ),
        details=growth,
    )


__all__ = ["attachment_store_check_specs"]
