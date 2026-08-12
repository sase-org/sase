"""Synchronize remote pull requests into local Patch records.

The VCS provider seam accepts a fetch ``limit`` and does not expose a page
cursor. Incremental passes therefore bound the number of fetched PR records;
full repair passes use ``limit=0`` for an unbounded provider request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import time
from typing import Protocol

from sase.ace.patch.importer import (
    apply_external_pr_plan,
    project_patch_files,
    read_project_patch_index,
)
from sase.core.external_pr_facade import plan_external_pr_import
from sase.core.external_pr_wire import (
    ACTION_SKIP,
    EXTERNAL_PR_WIRE_SCHEMA_VERSION,
    ExternalPrImportRequestWire,
    RemotePullRequestWire,
)
from sase.external_mirror.config import mirrored_pr_authors
from sase.external_mirror.report import MirrorReport
from sase.external_mirror.state import (
    MirrorCursor,
    next_backoff_entry,
    pr_mirror_state_dir,
    read_backoff_state,
    read_mirror_cursor,
    write_backoff_state,
    write_mirror_cursor,
)
from sase.vcs_provider import (
    PullRequestListState,
    PullRequestWire,
    supports_pull_requests,
)

KIND = "external_pr"
OVERLAP_WINDOW = timedelta(minutes=10)
DAILY_REPAIR_SCAN = timedelta(hours=24)


class _PullRequestLister(Protocol):
    def list_pull_requests(
        self,
        cwd: str,
        state: PullRequestListState = "open",
        limit: int = 100,
    ) -> list[PullRequestWire]: ...


def sync_external_pull_requests(
    *,
    project_key: str,
    workspace_dir: str,
    provider: _PullRequestLister,
    now: datetime,
    state_dir: Path | None = None,
    dry_run: bool = False,
    full: bool = False,
    fetch_limit: int = 200,
    create_budget: int = 25,
    deadline: float | None = None,
) -> MirrorReport:
    """Mirror remote PRs into local Patches with bounded mutation work.

    ``state_dir`` defaults to the lane-independent ``external_mirror`` state
    root (see ``pr_mirror_state_dir``); tests pass an explicit directory for
    isolation.
    """
    report = MirrorReport()
    if not supports_pull_requests(workspace_dir):
        report.noop_reason = "pull_requests_unsupported"
        return report

    state_dir = state_dir if state_dir is not None else pr_mirror_state_dir()
    now = _utc(now)
    cursor = read_mirror_cursor(state_dir, KIND, project_key)
    full = full or _needs_daily_repair_scan(cursor, now)
    limit = 0 if full else fetch_limit

    try:
        remotes = provider.list_pull_requests(workspace_dir, state="all", limit=limit)
    except Exception as exc:  # noqa: BLE001 - provider failures are persisted.
        report.errors += 1
        report.error_details.append(str(exc))
        backoff = read_backoff_state(state_dir, KIND)
        backoff[project_key] = next_backoff_entry(
            backoff.get(project_key),
            now=now,
            last_error=str(exc),
        )
        write_backoff_state(state_dir, KIND, backoff)
        return report

    report.fetched = len(remotes)
    remotes = _authored_remotes(remotes, mirrored_pr_authors())
    report.unmirrored = report.fetched - len(remotes)
    active_file, archive_file = project_patch_files(project_key)
    index = read_project_patch_index(active_file, archive_file)
    clean_pass = True
    mutations = 0
    latest_seen: tuple[datetime, str] | None = None

    for remote in _sorted_remotes(remotes):
        report.seen += 1
        provider_id = remote.provider_id or str(remote.number)
        updated_at = _parse_remote_datetime(remote.updated_at)
        if not _candidate_in_window(updated_at, cursor, full):
            continue
        if updated_at is not None:
            latest_seen = _max_checkpoint(latest_seen, updated_at, provider_id)

        local_patches = tuple(index.by_name.values())
        try:
            plan = plan_external_pr_import(
                ExternalPrImportRequestWire(
                    schema_version=EXTERNAL_PR_WIRE_SCHEMA_VERSION,
                    remote=_remote_to_wire(remote),
                    local_patches=local_patches,
                )
            )
        except Exception as exc:  # noqa: BLE001 - malformed records defer cursor.
            clean_pass = False
            report.errors += 1
            report.error_details.append(f"{provider_id}: {exc}")
            continue

        if plan.canonical_pr_url is None:
            clean_pass = False
            report.errors += 1
            report.error_details.append(f"{provider_id}: invalid_pull_request_url")
            continue

        would_mutate = plan.action != ACTION_SKIP
        if would_mutate and (mutations >= create_budget or _deadline_passed(deadline)):
            clean_pass = False
            report.budget_exhausted += 1
            continue

        if dry_run:
            _count_dry_run(report, plan.action)
            if would_mutate:
                mutations += 1
            continue

        outcome = apply_external_pr_plan(project_key, plan)
        if outcome.action_taken == "created":
            report.created += 1
            mutations += 1
        elif outcome.action_taken == "repaired":
            report.repaired += 1
            mutations += 1
        elif outcome.action_taken == "skipped":
            report.skipped += 1
        else:
            clean_pass = False
            report.conflicts += 1
        index = read_project_patch_index(active_file, archive_file)

    if dry_run:
        return report

    if clean_pass and not report.budget_exhausted and not report.errors:
        cursor = _advanced_cursor(cursor, latest_seen, full, now)
        write_mirror_cursor(state_dir, KIND, project_key, cursor)
        report.checkpoint_advanced = 1
        backoff = read_backoff_state(state_dir, KIND)
        if project_key in backoff:
            del backoff[project_key]
            write_backoff_state(state_dir, KIND, backoff)

    return report


def _remote_to_wire(remote: PullRequestWire) -> RemotePullRequestWire:
    return RemotePullRequestWire(
        number=remote.number,
        url=remote.url,
        provider_id=remote.provider_id,
        title=remote.title,
        body=remote.body,
        state=remote.state,
        is_draft=remote.is_draft,
        author=remote.author,
        head_ref=remote.head_ref,
        base_ref=remote.base_ref,
        created_at=remote.created_at,
        updated_at=remote.updated_at,
        closed_at=remote.closed_at,
        merged_at=remote.merged_at,
    )


def _authored_remotes(
    remotes: list[PullRequestWire],
    authors: frozenset[str],
) -> list[PullRequestWire]:
    """Narrow *remotes* to ``external_mirror.pr_authors`` when it is set.

    An empty set is the default and adopts every remote PR. Dropped records
    never reach the checkpoint, so clearing the knob later re-examines them.
    """
    if not authors:
        return remotes
    return [remote for remote in remotes if remote.author.casefold() in authors]


def _sorted_remotes(remotes: list[PullRequestWire]) -> list[PullRequestWire]:
    return sorted(
        remotes,
        key=lambda remote: (
            _parse_remote_datetime(remote.updated_at)
            or datetime.min.replace(tzinfo=UTC),
            remote.provider_id or str(remote.number),
        ),
    )


def _candidate_in_window(
    updated_at: datetime | None,
    cursor: MirrorCursor,
    full: bool,
) -> bool:
    if full or not cursor.backfill_complete or cursor.last_updated_at is None:
        return True
    if updated_at is None:
        return True
    return updated_at >= cursor.last_updated_at - OVERLAP_WINDOW


def _advanced_cursor(
    cursor: MirrorCursor,
    latest_seen: tuple[datetime, str] | None,
    full: bool,
    now: datetime,
) -> MirrorCursor:
    last_updated_at = cursor.last_updated_at
    last_provider_id = cursor.last_provider_id
    if latest_seen is not None:
        last_updated_at, last_provider_id = latest_seen
    return MirrorCursor(
        last_updated_at=last_updated_at,
        last_provider_id=last_provider_id,
        backfill_complete=cursor.backfill_complete or full,
        last_full_scan_at=now if full else cursor.last_full_scan_at,
    )


def _needs_daily_repair_scan(cursor: MirrorCursor, now: datetime) -> bool:
    if cursor.last_full_scan_at is None:
        return True
    return now - cursor.last_full_scan_at >= DAILY_REPAIR_SCAN


def _count_dry_run(report: MirrorReport, action: str) -> None:
    if action == "adopt":
        report.created += 1
    elif action == "repair_origin":
        report.repaired += 1
    else:
        report.skipped += 1


def _deadline_passed(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _max_checkpoint(
    current: tuple[datetime, str] | None,
    updated_at: datetime,
    provider_id: str,
) -> tuple[datetime, str]:
    candidate = (updated_at, provider_id)
    if current is None or candidate > current:
        return candidate
    return current


def _parse_remote_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["sync_external_pull_requests"]
