"""Shared-store reachability and outbox backlog check for ``sase doctor``."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_CHECK_ID = "project.attachment_store"
_CHECK_ALIAS = "attachments.store"
_TITLE = "Private attachment store"
_GIT_TIMEOUT_SECONDS = 10


def attachment_store_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the default check for the private attachment shared store."""

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


def _clone_for_key(project_key: str) -> object | None:
    from pathlib import Path

    from sase._linked_repo_paths import hidden_sidecar_clone_dir
    from sase.sdd._store_types import ATTACHMENTS_PRIVATE_SIDECAR_ROLE

    try:
        clone = Path(
            hidden_sidecar_clone_dir(project_key, ATTACHMENTS_PRIVATE_SIDECAR_ROLE)
        )
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


def _check_git_store_and_outbox(context: DoctorContext) -> DiagnosticCheck:
    """Warn about an unreachable git store or a backed-up upload outbox."""
    project_key = _resolve_project_key(context)
    if project_key is None:
        return _skip("no current project; attachment store check needs one")
    clone = _clone_for_key(project_key)
    if clone is None:
        return _skip(
            f"project {project_key} has no attachments-private shared store; "
            "attachments stay on this machine"
        )
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
    if queued:
        count = len(queued)
        noun = "upload" if count == 1 else "uploads"
        return _warn(
            f"attachments-private store for {project_key} is reachable; "
            f"{count} queued {noun} waiting "
            "(sase bead attachment push drains them)",
            f"{count} entries in attachment-upload-outbox.json",
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
    )


__all__ = ["attachment_store_check_specs"]
