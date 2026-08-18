"""Shared helpers for epic_resume chop script tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_epic_resume as epic_resume
from sase.axe.chop_script_context import ChopScriptContext
from sase.bead.epic_stall_policy import EpicClanMember, EpicClanSnapshot
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.scripts._bead_gate_projects import ProjectInventory

NOW = datetime(2026, 8, 17, 12, 5, 0, tzinfo=timezone(timedelta(hours=-4)))
FAILED_AT = NOW - timedelta(seconds=180)
SETTLE_SECONDS = 120


def make_runtime(tmp_path: Path, *, dry_run: bool = False) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="epic_resume",
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


def make_member(
    name: str = "sase-p4.1",
    *,
    bead_id: str | None = None,
    artifact_dir: str | None = None,
    timestamp: str = "20260817120000",
    outcome: str | None = None,
    has_done_marker: bool = False,
    is_live: bool = False,
    finished_at: datetime | None = None,
) -> EpicClanMember:
    return EpicClanMember(
        agent_name=name,
        bead_id=bead_id if bead_id is not None else f"{name}-bead",
        artifact_dir=(
            artifact_dir if artifact_dir is not None else f"/artifacts/{name}"
        ),
        timestamp=timestamp,
        outcome=outcome,
        has_done_marker=has_done_marker,
        is_live=is_live,
        finished_at=finished_at,
    )


def make_failed_member(
    name: str = "sase-p4.1", *, finished_at: datetime = FAILED_AT
) -> EpicClanMember:
    return make_member(
        name, outcome="failed", has_done_marker=True, finished_at=finished_at
    )


def make_waiting_member(name: str = "sase-p4.2") -> EpicClanMember:
    return make_member(name)


def make_live_member(name: str = "sase-p4.2") -> EpicClanMember:
    return make_member(name, is_live=True)


def make_snapshot(
    *members: EpicClanMember,
    project: str = "sase",
    epic_id: str = "sase-p4",
    generation: str = "20260817110000",
) -> EpicClanSnapshot:
    return EpicClanSnapshot(
        project=project,
        epic_id=epic_id,
        clan_generation=generation,
        members=members,
    )


class _FakeFlags:
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    def enabled(self, _flag: object) -> bool:
        return self._enabled


def patch_epic_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    snapshots: list[EpicClanSnapshot] | None = None,
    projects: list[str] | None = None,
    epic_open: bool = True,
    epic_title: str = "Raise an EpicResume gate",
    remaining_phase_count: int = 1,
    resolve_info: Callable[[Path, str], epic_resume._EpicInfo] | None = None,
    flag_enabled: bool = True,
    now: datetime = NOW,
    settle_seconds: int = SETTLE_SECONDS,
    gate_state: str | dict[str, str] = "pending",
    in_flight_epics: frozenset[str] = frozenset(),
    skipped_projects: frozenset[str] = frozenset(),
    sweep_allowed: bool = True,
) -> None:
    project_names = projects if projects is not None else ["sase"]
    stores = tuple((name, tmp_path / name) for name in project_names)
    monkeypatch.setattr(
        epic_resume,
        "_enabled_project_stores",
        lambda _log: ProjectInventory(
            stores=stores,
            skipped_projects=frozenset(skipped_projects),
            sweep_allowed=sweep_allowed,
        ),
    )
    monkeypatch.setattr(
        epic_resume, "_scan_epic_snapshots", lambda _root: list(snapshots or [])
    )
    monkeypatch.setattr(epic_resume, "_aware_now", lambda: now)
    monkeypatch.setattr(
        epic_resume, "get_epic_resume_settle_seconds", lambda: settle_seconds
    )
    monkeypatch.setattr(epic_resume, "current_flags", lambda: _FakeFlags(flag_enabled))

    default_resolver = resolve_info or (
        lambda _beads_dir, _epic_id: epic_resume._EpicInfo(
            open=epic_open,
            title=epic_title,
            remaining_phase_count=remaining_phase_count,
        )
    )
    monkeypatch.setattr(epic_resume, "_resolve_epic_info", default_resolver)

    def resolve_gate_state(request_id: str) -> str:
        if isinstance(gate_state, dict):
            return gate_state.get(request_id, "missing")
        return gate_state

    monkeypatch.setattr(epic_resume, "_gate_state", resolve_gate_state)
    monkeypatch.setattr(
        epic_resume,
        "active_epic_resume",
        lambda epic_id: object() if epic_id in in_flight_epics else None,
    )


def capture_created(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        epic_resume,
        "create_epic_resume_gate",
        lambda **kwargs: created.append(kwargs),
    )
    return created


def capture_canceled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    canceled: list[tuple[str, str, str]] = []

    def fake_cancel(project: str, epic_id: str, *, reason: str, source: str) -> bool:
        canceled.append((project, epic_id, reason))
        return True

    monkeypatch.setattr(epic_resume, "cancel_epic_resume", fake_cancel)
    return canceled


def expected_counters(
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    deferred: int = 0,
    stalled: int = 0,
    epics: int = 0,
    projects: int = 1,
) -> dict[str, int]:
    return {
        "gated": gated,
        "canceled": canceled,
        "skipped": skipped,
        "deferred": deferred,
        "stalled": stalled,
        "epics": epics,
        "projects": projects,
    }
