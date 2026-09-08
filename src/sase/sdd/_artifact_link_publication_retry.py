"""Durable retry state for unpublished artifact-link sidecar commits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import errno
import fcntl
import json
import os
import subprocess
import tempfile
import time

from sase.core.artifact_link_publication_retry import (
    artifact_link_publication_due,
    artifact_link_publication_mark_attempt,
    artifact_link_publication_record_key,
    artifact_link_publication_register_pending,
    artifact_link_publication_state_wire_schema_version,
)
from sase.core.paths import sase_projects_dir
from sase.sdd._artifact_link_authorize import (
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_machine_store import MachineArtifactLinkRoot

_STATE_FILENAME = "artifact_link_publications.json"
_LOCK_FILENAME = "artifact_link_publications.lock"
_STATE_LOCK_TIMEOUT_SECONDS = 2.0
_LOCAL_GIT_TIMEOUT_SECONDS = 10.0


class _ArtifactLinkPublicationStateBusy(RuntimeError):
    """Raised when retry state is locked by another process."""


@dataclass(frozen=True)
class _ArtifactLinkPublicationRegistration:
    """Result of persisting one failed inline publication attempt."""

    recorded: bool
    diagnostic: str | None = None
    record: dict[str, Any] | None = None


@dataclass(frozen=True)
class ArtifactLinkPublicationRetryDetail:
    """Operator-facing detail for one publication retry root."""

    project_key: str
    role: str
    repo_root: Path
    status: str
    age_seconds: float = 0.0
    last_error: str | None = None
    next_due_at: float | None = None
    log_path: Path | None = None
    diagnostic: str | None = None


@dataclass(frozen=True)
class _ArtifactLinkPublicationRetryReport:
    """Summary of one publication retry sweep."""

    attempted: int = 0
    published: int = 0
    deferred: int = 0
    failed: int = 0
    aged: int = 0
    discovered: int = 0
    cleared: int = 0
    diagnostics: tuple[str, ...] = ()
    details: tuple[ArtifactLinkPublicationRetryDetail, ...] = ()


@dataclass
class _MutableReport:
    attempted: int = 0
    published: int = 0
    deferred: int = 0
    failed: int = 0
    aged: int = 0
    discovered: int = 0
    cleared: int = 0
    diagnostics: list[str] = field(default_factory=list)
    details: list[ArtifactLinkPublicationRetryDetail] = field(default_factory=list)

    def freeze(self) -> _ArtifactLinkPublicationRetryReport:
        return _ArtifactLinkPublicationRetryReport(
            attempted=self.attempted,
            published=self.published,
            deferred=self.deferred,
            failed=self.failed,
            aged=self.aged,
            discovered=self.discovered,
            cleared=self.cleared,
            diagnostics=tuple(self.diagnostics),
            details=tuple(self.details),
        )


def _artifact_link_publication_state_path(project_key: str) -> Path:
    """Return the host-owned publication retry state file for *project_key*."""

    key = project_key.strip()
    if not key or "/" in key or key in {".", ".."}:
        raise ValueError(
            f"invalid project key for artifact-link publication state: {project_key!r}"
        )
    return sase_projects_dir() / key / _STATE_FILENAME


def register_artifact_link_publication_failure(
    *,
    project_key: str,
    role: str,
    repo_root: str | Path,
    remote_url: str,
    error: str,
    log_path: str | Path | None = None,
    attempt_status: str = "failed",
    now: float | None = None,
) -> _ArtifactLinkPublicationRegistration:
    """Persist retry state after an inline artifact-link publication failed."""

    observed_at = _wall_now(now)
    root = MachineArtifactLinkRoot(
        project_key=project_key,
        role=role,
        repo_root=Path(repo_root).expanduser().resolve(strict=False),
        remote_url=remote_url,
    )
    try:
        record, diagnostic, _discovered = _register_pending(root, observed_at)
        if record is None:
            return _ArtifactLinkPublicationRegistration(False, diagnostic=diagnostic)
        record = _mark_attempt(
            root.project_key,
            record,
            {
                "status": attempt_status,
                "error": error,
                "log_path": str(log_path) if log_path is not None else None,
            },
            observed_at,
        )
    except Exception as exc:  # noqa: BLE001 - publication failure reporting must survive.
        return _ArtifactLinkPublicationRegistration(
            False,
            diagnostic=f"could not persist artifact-link publication retry state: {exc}",
        )
    return _ArtifactLinkPublicationRegistration(True, record=record)


def sweep_artifact_link_publication_retries(
    roots: tuple[MachineArtifactLinkRoot, ...],
    *,
    now: float | None = None,
    deadline: float | None = None,
    worker_lock_wait: float = 0.0,
) -> _ArtifactLinkPublicationRetryReport:
    """Retry due unpublished artifact-link commits for eligible hidden roots."""

    report = _MutableReport()
    observed_at = _wall_now(now)
    for root in roots:
        if _deadline_expired(deadline):
            report.deferred += 1
            _add_detail(
                report,
                root,
                "deferred",
                diagnostic="publication retry deferred past chop budget",
            )
            break
        try:
            _sweep_root(
                root,
                now=observed_at,
                deadline=deadline,
                worker_lock_wait=worker_lock_wait,
                report=report,
            )
        except Exception as exc:  # noqa: BLE001 - one broken role cannot block peers.
            report.failed += 1
            diagnostic = (
                f"{root.project_key}/{root.role}: publication retry failed: {exc}"
            )
            report.diagnostics.append(diagnostic)
            _add_detail(report, root, "failed", diagnostic=diagnostic)
    return report.freeze()


def _sweep_root(
    root: MachineArtifactLinkRoot,
    *,
    now: float,
    deadline: float | None,
    worker_lock_wait: float,
    report: _MutableReport,
) -> None:
    probe = probe_machine_writable_sidecar_root(root.repo_root)
    if not probe.writable:
        report.deferred += 1
        refusal = sidecar_root_not_machine_writable_message(
            root.role,
            root.repo_root,
            diagnostic=probe.diagnostic or "not machine-writable",
        )
        report.diagnostics.append(f"{root.project_key}/{root.role}: {refusal}")
        _add_detail(report, root, "deferred", diagnostic=refusal)
        return

    observation, observation_diagnostic = _publication_observation(root, now)
    if observation is None:
        report.failed += 1
        detail = observation_diagnostic or "could not inspect publication state"
        report.diagnostics.append(f"{root.project_key}/{root.role}: {detail}")
        _add_detail(report, root, "failed", diagnostic=detail)
        return

    key = str(observation["key"])
    if _head_is_published(root.repo_root):
        if _clear_record(root.project_key, key):
            report.cleared += 1
        _add_detail(report, root, "published")
        return

    record, registration_diagnostic, discovered = _register_pending(
        root, now, observation=observation
    )
    if record is None:
        report.failed += 1
        detail = (
            registration_diagnostic or "could not record unpublished artifact-link head"
        )
        report.diagnostics.append(f"{root.project_key}/{root.role}: {detail}")
        _add_detail(report, root, "failed", diagnostic=detail)
        return
    if discovered:
        report.discovered += 1

    due = artifact_link_publication_due(record, now=now)
    if bool(due.get("aged")):
        report.aged += 1
        warning = str(due.get("warning") or "artifact-link publication is aging")
        report.diagnostics.append(f"{root.project_key}/{root.role}: {warning}")
    if not bool(due.get("due")):
        _add_detail(
            report,
            root,
            "pending",
            age_seconds=float(due.get("age_seconds") or 0.0),
            last_error=_string_or_none(record.get("last_error")),
            next_due_at=float(
                due.get("next_due_at") or record.get("next_due_at") or 0.0
            ),
            log_path=_path_or_none(record.get("last_log_path")),
        )
        return

    if _deadline_expired(deadline):
        report.deferred += 1
        _add_detail(
            report,
            root,
            "deferred",
            age_seconds=float(due.get("age_seconds") or 0.0),
            diagnostic="publication retry deferred past chop budget",
            next_due_at=float(due.get("next_due_at") or 0.0),
        )
        return

    report.attempted += 1
    outcome = _run_publication_worker(
        root.repo_root,
        worker_lock_wait=worker_lock_wait,
        deadline=deadline,
    )
    log_path = getattr(outcome, "log_path", None)
    if _head_is_published(root.repo_root):
        _clear_record(root.project_key, key)
        report.published += 1
        _add_detail(
            report,
            root,
            "published",
            age_seconds=float(due.get("age_seconds") or 0.0),
            log_path=_path_or_none(log_path),
        )
        return

    if getattr(outcome, "skipped_locked", False):
        report.deferred += 1
        error = "managed sync worker already holds the publication lock"
        marked = _mark_attempt(
            root.project_key,
            record,
            {
                "status": "deferred",
                "error": error,
                "log_path": _string_or_none(log_path),
            },
            now,
        )
        _add_detail(
            report,
            root,
            "deferred",
            age_seconds=float(due.get("age_seconds") or 0.0),
            last_error=error,
            next_due_at=float(marked.get("next_due_at") or 0.0),
            log_path=_path_or_none(log_path),
        )
        return

    report.failed += 1
    attempt_error = getattr(outcome, "error", None)
    if not attempt_error and getattr(outcome, "skipped_no_remote", False):
        attempt_error = "sidecar repository has no push remote"
    if not attempt_error:
        attempt_error = "publication worker completed without publishing HEAD"
    marked = _mark_attempt(
        root.project_key,
        record,
        {
            "status": "failed",
            "error": str(attempt_error),
            "log_path": _string_or_none(log_path),
        },
        now,
    )
    report.diagnostics.append(f"{root.project_key}/{root.role}: {attempt_error}")
    _add_detail(
        report,
        root,
        "failed",
        age_seconds=float(due.get("age_seconds") or 0.0),
        last_error=str(attempt_error),
        next_due_at=float(marked.get("next_due_at") or 0.0),
        log_path=_path_or_none(log_path),
    )


def _publication_observation(
    root: MachineArtifactLinkRoot, now: float
) -> tuple[dict[str, Any] | None, str | None]:
    repo_root = root.repo_root.expanduser().resolve(strict=False)
    if not (repo_root / ".git").is_dir():
        return None, f"{repo_root} is not a git worktree"
    upstream = _tracking_upstream(repo_root)
    if upstream is None:
        return None, "sidecar repository has no tracking upstream"
    head_revision = _git_text(repo_root, ["rev-parse", "HEAD"])
    if head_revision is None:
        return None, "could not read sidecar HEAD"
    return (
        {
            "version": artifact_link_publication_state_wire_schema_version(),
            "project_key": root.project_key,
            "role": root.role,
            "repo_root": str(repo_root),
            "remote_url": root.remote_url,
            "upstream": upstream,
            "head_revision": head_revision,
            "oldest_unpublished_at": _oldest_unpublished_commit_time(
                repo_root, upstream
            )
            or now,
            "key": artifact_link_publication_record_key(
                project_key=root.project_key,
                role=root.role,
                repo_root=str(repo_root),
                remote_url=root.remote_url,
                upstream=upstream,
            ),
        },
        None,
    )


def _register_pending(
    root: MachineArtifactLinkRoot,
    now: float,
    *,
    observation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    if observation is None:
        observation, diagnostic = _publication_observation(root, now)
        if observation is None:
            return None, diagnostic, False
    key = str(observation["key"])
    payload = {item: value for item, value in observation.items() if item != "key"}
    path = _artifact_link_publication_state_path(root.project_key)
    with _state_lock(path):
        records = _read_records_unlocked(path)
        current = records.get(key)
        try:
            record = artifact_link_publication_register_pending(
                current if isinstance(current, dict) else None,
                payload,
                now=now,
            )
        except Exception:
            record = artifact_link_publication_register_pending(
                None,
                payload,
                now=now,
            )
        discovered = key not in records
        records[key] = record
        _write_records_unlocked(path, records)
    return record, None, discovered


def _mark_attempt(
    project_key: str,
    record: dict[str, Any],
    attempt: dict[str, Any],
    now: float,
) -> dict[str, Any]:
    key = str(record["key"])
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path):
        records = _read_records_unlocked(path)
        current = records.get(key)
        base = current if isinstance(current, dict) else record
        marked = artifact_link_publication_mark_attempt(base, attempt, now=now)
        records[key] = marked
        _write_records_unlocked(path, records)
    return marked


def _clear_record(project_key: str, key: str) -> bool:
    path = _artifact_link_publication_state_path(project_key)
    with _state_lock(path):
        records = _read_records_unlocked(path)
        if key not in records:
            return False
        del records[key]
        _write_records_unlocked(path, records)
    return True


def _read_records_unlocked(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != artifact_link_publication_state_wire_schema_version()
    ):
        return {}
    records = payload.get("records")
    if not isinstance(records, dict):
        return {}
    return {
        str(key): value
        for key, value in records.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _write_records_unlocked(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": artifact_link_publication_state_wire_schema_version(),
        "records": records,
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(_LOCK_FILENAME)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        _flock_with_timeout(lock_file.fileno(), _STATE_LOCK_TIMEOUT_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _flock_with_timeout(fd: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            if time.monotonic() >= deadline:
                raise _ArtifactLinkPublicationStateBusy(
                    "artifact-link publication retry state is locked"
                ) from exc
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def _run_publication_worker(
    repo_root: Path, *, worker_lock_wait: float, deadline: float | None
) -> Any:
    from sase.bead.sync import push_bead_work_launch

    wait = max(0.0, worker_lock_wait)
    remaining = _deadline_remaining(deadline)
    if remaining is not None:
        wait = min(wait, remaining)
    return push_bead_work_launch(
        repo_root,
        worker_lock_wait=wait,
        deadline=deadline,
    )


def _head_is_published(repo_root: Path) -> bool:
    from sase.bead._sync_publication import head_is_published

    try:
        return head_is_published(repo_root)
    except Exception:  # noqa: BLE001 - callers need a falsey probe.
        return False


def _tracking_upstream(repo_root: Path) -> str | None:
    return _git_text(
        repo_root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
    )


def _oldest_unpublished_commit_time(repo_root: Path, upstream: str) -> float | None:
    output = _git_text(
        repo_root, ["log", "--format=%ct", "--reverse", f"{upstream}..HEAD"]
    )
    if not output:
        return None
    first = output.splitlines()[0].strip()
    try:
        return float(int(first))
    except ValueError:
        return None


def _git_text(repo_root: Path, args: list[str]) -> str | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _deadline_remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def _wall_now(value: float | None) -> float:
    return float(time.time() if value is None else value)


def _add_detail(
    report: _MutableReport,
    root: MachineArtifactLinkRoot,
    status: str,
    *,
    age_seconds: float = 0.0,
    last_error: str | None = None,
    next_due_at: float | None = None,
    log_path: Path | None = None,
    diagnostic: str | None = None,
) -> None:
    report.details.append(
        ArtifactLinkPublicationRetryDetail(
            project_key=root.project_key,
            role=root.role,
            repo_root=root.repo_root,
            status=status,
            age_seconds=age_seconds,
            last_error=last_error,
            next_due_at=next_due_at,
            log_path=log_path,
            diagnostic=diagnostic,
        )
    )


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_or_none(value: object) -> Path | None:
    text = _string_or_none(value)
    return Path(text) if text else None


__all__ = [
    "ArtifactLinkPublicationRetryDetail",
    "register_artifact_link_publication_failure",
    "sweep_artifact_link_publication_retries",
]
