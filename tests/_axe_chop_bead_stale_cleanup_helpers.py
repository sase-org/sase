"""Shared helpers for bead_stale_cleanup chop script tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_stale_cleanup as stale_cleanup
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import (
    FlagRecord,
    Issue,
    IssueType,
    PhaseSize,
    SnoozeRecord,
    Status,
    TaskPlusOneEvidence,
)
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger

NOW = datetime(2026, 8, 17, 11, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
STALE_CREATED_AT = "2026-08-01T09:14:02-04:00"


def make_runtime(tmp_path: Path, *, dry_run: bool = False) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_stale_cleanup",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="housekeeping",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            dry_run=dry_run,
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def make_task(
    bead_id: str = "sase-task.1",
    *,
    created_at: str = STALE_CREATED_AT,
    plus_ones: int = 0,
    title: str = "Follow up on cache invalidation",
    status: Status = Status.READY,
    size: PhaseSize | None = PhaseSize.SMALL,
) -> Issue:
    issue = Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=IssueType.TASK,
        description="Make cache invalidation deterministic.",
        created_at=created_at,
        created_by="claude_coder",
        size=size,
    )
    issue.plus_one_evidence = [
        TaskPlusOneEvidence(
            timestamp="2026-08-02T00:00:00-04:00",
            reporter=f"reporter-{index}",
            note="corroborated",
        )
        for index in range(plus_ones)
    ]
    return issue


def make_snoozed_task(bead_id: str = "sase-task.snoozed") -> Issue:
    issue = make_task(bead_id)
    issue.status = Status.SNOOZED
    issue.snooze = SnoozeRecord(
        until="2099-01-01T00:00:00-04:00",
        snoozed_at="2026-08-01T00:00:00-04:00",
        snoozed_by="bryan",
        reason="waiting",
    )
    return issue


def make_due_flag(bead_id: str = "sase-flag.1") -> Issue:
    return Issue(
        id=bead_id,
        title="Remove the prettier_enabled flag",
        status=Status.OPEN,
        issue_type=IssueType.FLAG,
        created_at=STALE_CREATED_AT,
        created_by="claude_coder",
        flag=FlagRecord(
            key="prettier_enabled",
            remove_by_date="2026-01-01",
            remove_by_release="0.1.0",
        ),
    )


def patch_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    issues_by_project: dict[str, list[Issue]] | list[Issue],
    *,
    min_plus_ones: int = 1,
    stale_after_days: int = 7,
    stale_cleanup_min_beads: int = 2,
    now: datetime = NOW,
    gate_state: str = "pending",
) -> None:
    if isinstance(issues_by_project, list):
        issues_by_project = {"sase": issues_by_project}
    stores = [(name, tmp_path / name) for name in issues_by_project]
    by_path = {tmp_path / name: issues for name, issues in issues_by_project.items()}
    monkeypatch.setattr(
        stale_cleanup,
        "_enabled_project_stores",
        lambda _log: stores,
    )

    def ready(path: Path) -> list[Issue]:
        if path not in by_path:
            raise OSError(f"no fixture for {path}")
        return list(by_path[path])

    monkeypatch.setattr(stale_cleanup, "_ready_task_beads", ready)
    monkeypatch.setattr(stale_cleanup, "_aware_now", lambda: now)
    monkeypatch.setattr(
        stale_cleanup, "get_task_triage_min_plus_ones", lambda: min_plus_ones
    )
    monkeypatch.setattr(
        stale_cleanup, "get_task_triage_stale_after_days", lambda: stale_after_days
    )
    monkeypatch.setattr(
        stale_cleanup,
        "get_task_triage_stale_cleanup_min_beads",
        lambda: stale_cleanup_min_beads,
    )
    monkeypatch.setattr(stale_cleanup, "_gate_state", lambda _request_id: gate_state)


def capture_created(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        stale_cleanup,
        "create_bead_stale_cleanup_gate",
        lambda **kwargs: created.append(kwargs),
    )
    return created


def capture_canceled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        stale_cleanup,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
    )
    return canceled


def expected_counters(
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    stale: int = 0,
    offered: int = 0,
    omitted: int = 0,
    projects: int = 1,
) -> dict[str, int]:
    return {
        "gated": gated,
        "canceled": canceled,
        "skipped": skipped,
        "stale": stale,
        "offered": offered,
        "omitted": omitted,
        "projects": projects,
    }
