"""Shared helpers for bead_task_triage chop script tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import Issue, IssueType, PhaseSize, SnoozeRecord, Status
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.core.time import get_timezone


def make_runtime(tmp_path: Path, *, dry_run: bool = False) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="bead_task_triage",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
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
    created_by: str = "claude_coder",
) -> Issue:
    return Issue(
        id=bead_id,
        title="Follow up on cache invalidation",
        status=Status.READY,
        issue_type=IssueType.TASK,
        description="Make cache invalidation deterministic.",
        notes="Discovered while landing sase-bg.",
        created_at="2026-01-01T00:00:00Z",
        created_by=created_by,
        size=PhaseSize.SMALL,
    )


def make_snoozed_task(
    bead_id: str = "sase-task.1",
    *,
    until: str | None = None,
    reason: str = "Waiting on the upstream fix.",
) -> Issue:
    issue = make_task(bead_id)
    issue.status = Status.SNOOZED
    issue.snooze = SnoozeRecord(
        until=until or future_instant(days=3),
        snoozed_at="2026-08-01T00:00:00+00:00",
        snoozed_by="bryan",
        reason=reason,
    )
    return issue


def future_instant(*, days: int) -> str:
    return (datetime.now(get_timezone()) + timedelta(days=days)).isoformat()


def patch_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ready: list[Issue],
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: [("sase", tmp_path / "beads")],
    )
    monkeypatch.setattr(task_triage, "_gateable_tasks", lambda _path: list(ready))
    patch_active_launches(monkeypatch)


def patch_active_launches(
    monkeypatch: pytest.MonkeyPatch,
    bead_ids: set[str] | frozenset[str] = frozenset(),
) -> None:
    monkeypatch.setattr(
        task_triage,
        "active_task_launch_bead_ids",
        lambda: frozenset(bead_ids),
    )


def patch_snooze_gate(
    monkeypatch: pytest.MonkeyPatch, created: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        task_triage,
        "create_bead_snooze_gate",
        lambda **kwargs: created.append(kwargs),
    )
