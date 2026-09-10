"""Durable retry state for unpublished artifact-link sidecar commits.

Git probes and host-owned JSON state live in sibling modules so this file
keeps the sweep orchestration and public registration API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.artifact_link_publication_retry import artifact_link_publication_due
from sase.sdd._artifact_link_authorize import (
    probe_machine_writable_sidecar_root,
    sidecar_root_not_machine_writable_message,
)
from sase.sdd._artifact_link_machine_store import MachineArtifactLinkRoot
from sase.sdd._artifact_link_publication_retry_state import (
    clear_record as _clear_record,
    mark_attempt as _mark_attempt,
    next_retry_role_after as _next_retry_role_after,
    read_publication_state as _read_publication_state,
    register_pending as _register_pending,
    rotate_retry_roots as _rotate_retry_roots,
    write_next_retry_role as _write_next_retry_role,
)
from sase.sdd._artifact_link_publication_retry_support import (
    deadline_expired as _deadline_expired,
    deadline_remaining as _deadline_remaining,
    head_is_published as _head_is_published,
    publication_observation as _publication_observation,
    retry_mutation_blocker as _retry_mutation_blocker,
    wall_now as _wall_now,
)


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


@dataclass(frozen=True)
class _ArtifactLinkPublicationInspection:
    """Read-only health snapshot of unpublished publication records."""

    pending: int = 0
    aged: int = 0
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


def inspect_artifact_link_publications(
    project_key: str,
    *,
    now: float | None = None,
) -> _ArtifactLinkPublicationInspection:
    """Return pending unpublished artifact-link publication records."""

    observed_at = _wall_now(now)
    try:
        records, _next_role = _read_publication_state(project_key)
    except Exception as exc:  # noqa: BLE001 - doctor should report, not crash.
        return _ArtifactLinkPublicationInspection(
            diagnostics=(
                f"{project_key}: could not inspect artifact-link publication "
                f"state: {exc}",
            )
        )
    details: list[ArtifactLinkPublicationRetryDetail] = []
    diagnostics: list[str] = []
    aged = 0
    for record in records.values():
        try:
            due = artifact_link_publication_due(record, now=observed_at)
        except Exception as exc:  # noqa: BLE001 - malformed state is a health issue.
            diagnostics.append(
                f"{project_key}: malformed artifact-link publication record: {exc}"
            )
            continue
        is_aged = bool(due.get("aged"))
        if is_aged:
            aged += 1
        details.append(
            ArtifactLinkPublicationRetryDetail(
                project_key=str(record.get("project_key") or project_key),
                role=str(record.get("role") or ""),
                repo_root=Path(str(record.get("repo_root") or ".")),
                status="aged" if is_aged else "pending",
                age_seconds=float(due.get("age_seconds") or 0.0),
                last_error=_string_or_none(record.get("last_error")),
                next_due_at=float(
                    due.get("next_due_at") or record.get("next_due_at") or 0.0
                ),
                log_path=_path_or_none(record.get("last_log_path")),
            )
        )
    return _ArtifactLinkPublicationInspection(
        pending=len(details),
        aged=aged,
        diagnostics=tuple(diagnostics),
        details=tuple(details),
    )


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
    ordered_roots = _rotate_retry_roots(roots, deadline=deadline)
    last_started: MachineArtifactLinkRoot | None = None
    for root in ordered_roots:
        if _deadline_expired(deadline):
            report.deferred += 1
            _add_detail(
                report,
                root,
                "deferred",
                diagnostic="publication retry deferred past chop budget",
            )
            break
        last_started = root
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
    if last_started is not None:
        next_role = _next_retry_role_after(ordered_roots, last_started)
        try:
            _write_next_retry_role(
                last_started.project_key,
                next_role,
                deadline=deadline,
            )
        except Exception as exc:  # noqa: BLE001 - retry fairness is best effort.
            report.diagnostics.append(
                f"{last_started.project_key}: could not persist publication retry "
                f"role cursor: {exc}"
            )
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

    observation, observation_diagnostic = _publication_observation(
        root, now, deadline=deadline
    )
    if observation is None:
        report.failed += 1
        detail = observation_diagnostic or "could not inspect publication state"
        report.diagnostics.append(f"{root.project_key}/{root.role}: {detail}")
        _add_detail(report, root, "failed", diagnostic=detail)
        return

    key = str(observation["key"])
    if _head_is_published(root.repo_root, deadline=deadline):
        if _clear_record(root.project_key, key, deadline=deadline):
            report.cleared += 1
        _add_detail(report, root, "published")
        return

    blocking_diagnostic = _retry_mutation_blocker(root.repo_root, deadline=deadline)
    if blocking_diagnostic is not None:
        record, registration_diagnostic, discovered = _register_pending(
            root, now, observation=observation, deadline=deadline
        )
        if record is None:
            report.failed += 1
            detail = (
                registration_diagnostic
                or "could not record unpublished artifact-link head"
            )
            report.diagnostics.append(f"{root.project_key}/{root.role}: {detail}")
            _add_detail(report, root, "failed", diagnostic=detail)
            return
        if discovered:
            report.discovered += 1
        marked = _mark_attempt(
            root.project_key,
            record,
            {
                "status": "deferred",
                "error": blocking_diagnostic,
                "log_path": None,
            },
            now,
            deadline=deadline,
        )
        due = artifact_link_publication_due(marked, now=now)
        report.deferred += 1
        report.diagnostics.append(
            f"{root.project_key}/{root.role}: {blocking_diagnostic}"
        )
        _add_detail(
            report,
            root,
            "deferred",
            age_seconds=float(due.get("age_seconds") or 0.0),
            last_error=blocking_diagnostic,
            next_due_at=float(due.get("next_due_at") or 0.0),
            diagnostic=blocking_diagnostic,
        )
        return

    record, registration_diagnostic, discovered = _register_pending(
        root, now, observation=observation, deadline=deadline
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
    if _head_is_published(root.repo_root, deadline=deadline):
        _clear_record(root.project_key, key, deadline=deadline)
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
            deadline=deadline,
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
        deadline=deadline,
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
    "inspect_artifact_link_publications",
    "register_artifact_link_publication_failure",
    "sweep_artifact_link_publication_retries",
]
