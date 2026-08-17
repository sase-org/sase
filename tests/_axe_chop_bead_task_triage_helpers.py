"""Shared helpers for bead_task_triage chop script tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.model import (
    FlagRecord,
    Issue,
    IssueType,
    PhaseSize,
    SnoozeRecord,
    Status,
)
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


def make_due_flag(
    bead_id: str = "sase-flag.1",
    *,
    key: str = "prettier_enabled",
    remove_by_date: str = "2026-01-01",
    remove_by_release: str = "0.1.0",
    created_by: str = "claude_coder",
) -> Issue:
    """Return an ``open`` flag bead whose thresholds have both passed."""
    return Issue(
        id=bead_id,
        title=f"Remove the {key} flag",
        status=Status.OPEN,
        issue_type=IssueType.FLAG,
        description="Routes prettier formatting.",
        notes="Discovered while landing sase-bg.",
        created_at="2026-01-01T00:00:00Z",
        created_by=created_by,
        flag=FlagRecord(
            key=key,
            remove_by_date=remove_by_date,
            remove_by_release=remove_by_release,
        ),
    )


def make_live_flag(
    bead_id: str = "sase-flag.1",
    *,
    key: str = "prettier_enabled",
    created_by: str = "claude_coder",
) -> Issue:
    """Return an ``open`` flag bead whose thresholds have not passed."""
    return make_due_flag(
        bead_id,
        key=key,
        remove_by_date="2099-01-01",
        remove_by_release="99.0.0",
        created_by=created_by,
    )


def patch_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ready: list[Issue],
    *,
    min_plus_ones: int = 0,
) -> None:
    monkeypatch.setattr(
        task_triage,
        "_enabled_project_stores",
        lambda _log: [("sase", tmp_path / "beads")],
    )
    monkeypatch.setattr(
        task_triage,
        "_gateable_beads",
        lambda _path, **_kwargs: list(ready),
    )
    monkeypatch.setattr(task_triage, "find_pending_bead_gates", lambda _kinds: [])
    patch_min_plus_ones(monkeypatch, min_plus_ones)
    patch_active_launches(monkeypatch)


def patch_min_plus_ones(monkeypatch: pytest.MonkeyPatch, min_plus_ones: int) -> None:
    monkeypatch.setattr(
        task_triage, "get_task_triage_min_plus_ones", lambda: min_plus_ones
    )


@pytest.fixture(autouse=True)
def _default_task_triage_min_plus_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the ``+1`` bar to 0 so pre-existing fixtures keep gating every ready task.

    Tests that exercise the threshold itself override it via
    :func:`patch_min_plus_ones` or ``patch_project(..., min_plus_ones=...)``.
    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """
    patch_min_plus_ones(monkeypatch, 0)


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
