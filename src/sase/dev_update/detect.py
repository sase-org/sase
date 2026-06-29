"""Detect latest dev versions for editable installs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.dev_update.models import DevLatest, DevLatestState
from sase.version._display import derive_display_version
from sase.version._git import (
    GitUpstreamStatus,
    classify_git_upstream,
    fetch_git_upstream,
    probe_git_metadata_at_ref,
)
from sase.version._models import GitProbeResult, VersionPackageRecord


def detect_dev_latest(record: VersionPackageRecord, *, offline: bool) -> DevLatest:
    """Return latest-dev information for one editable package record."""
    unavailable = _record_unavailable_reason(record)
    if unavailable is not None:
        return _latest(record, "unavailable", unavailable)

    source_root = Path(record.source_root or "")
    try:
        status = classify_git_upstream(source_root)
    except FileNotFoundError:
        return _latest(record, "unavailable", "git is not available on PATH")
    except OSError as exc:
        return _latest(record, "unavailable", f"git could not be executed: {exc}")
    except subprocess.TimeoutExpired:
        return _latest(record, "unavailable", f"git probe timed out for {source_root}")
    except subprocess.CalledProcessError as exc:
        return _latest(
            record,
            "unavailable",
            f"git upstream state unavailable: {exc.stderr.strip() or exc}",
        )

    if status.detached:
        return _from_status(record, status, "detached", "checkout is detached")
    if not status.has_upstream:
        return _from_status(record, status, "no_upstream", "checkout has no upstream")

    fetch_error: str | None = None
    if not offline:
        try:
            fetch_git_upstream(status)
            status = classify_git_upstream(source_root)
        except (
            FileNotFoundError,
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            fetch_error = _format_fetch_error(exc)

    latest_version = _latest_version_from_status(record, status)

    if offline:
        return _from_status(
            record,
            status,
            "offline",
            "offline; using cached upstream ref",
            latest_version=latest_version,
        )
    if fetch_error is not None:
        return _from_status(
            record,
            status,
            "fetch_failed",
            f"fetch failed; using cached upstream ref: {fetch_error}",
            latest_version=latest_version,
            fetch_error=fetch_error,
        )
    if status.dirty:
        return _from_status(
            record,
            status,
            "dirty",
            "checkout has local changes",
            latest_version=latest_version,
        )
    if status.diverged:
        return _from_status(
            record,
            status,
            "diverged",
            "checkout has diverged from upstream",
            latest_version=latest_version,
        )
    if git_status_has_update(status):
        return _from_status(
            record,
            status,
            "update_available",
            f"behind upstream by {status.behind} commit(s)",
            latest_version=latest_version,
            update_available=True,
        )

    reason = "already current"
    if status.ahead and status.ahead > 0:
        reason = "checkout is ahead of upstream"
    return _from_status(
        record,
        status,
        "current",
        reason,
        latest_version=latest_version,
    )


def git_status_has_update(status: GitUpstreamStatus) -> bool:
    """Return whether a local git status means an editable install is outdated."""
    return not status.dirty and status.strictly_behind


def _record_unavailable_reason(record: VersionPackageRecord) -> str | None:
    if record.install_type != "editable":
        return "package is not an editable install"
    if not record.source_root:
        return "editable install has no source root"
    return None


def _latest(
    record: VersionPackageRecord,
    state: DevLatestState,
    reason: str,
    *,
    latest_version: str | None = None,
    update_available: bool = False,
    git_root: str | None = None,
    upstream: str | None = None,
    ahead: int | None = None,
    behind: int | None = None,
    fetch_error: str | None = None,
) -> DevLatest:
    return DevLatest(
        record=record,
        state=state,
        reason=reason,
        current_version=record.display_version,
        latest_version=latest_version,
        update_available=update_available,
        git_root=git_root,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        fetch_error=fetch_error,
    )


def _from_status(
    record: VersionPackageRecord,
    status: GitUpstreamStatus,
    state: DevLatestState,
    reason: str,
    *,
    latest_version: str | None = None,
    update_available: bool = False,
    fetch_error: str | None = None,
) -> DevLatest:
    return _latest(
        record,
        state,
        reason,
        latest_version=latest_version,
        update_available=update_available,
        git_root=status.root,
        upstream=status.upstream,
        ahead=status.ahead,
        behind=status.behind,
        fetch_error=fetch_error,
    )


def _latest_version_from_status(
    record: VersionPackageRecord, status: GitUpstreamStatus
) -> str | None:
    if status.upstream is None:
        return None
    result = probe_git_metadata_at_ref(Path(status.root), status.upstream)
    return _version_from_probe(record, result)


def _version_from_probe(
    record: VersionPackageRecord, result: GitProbeResult
) -> str | None:
    if result.metadata is None:
        return None
    base_version = record.source_version or record.distribution_version
    return derive_display_version(base_version, result.metadata)


def _format_fetch_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.stderr.strip() or str(exc)
    if isinstance(exc, subprocess.TimeoutExpired):
        return "git fetch timed out"
    return str(exc)
