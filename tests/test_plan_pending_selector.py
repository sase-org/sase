"""Selector-matrix, visibility, and miss-diagnosis tests for the resolver phase.

Covers every PLAN form in the epic design table, exact-beats-prefix,
no name-prefix matching, ambiguity reporting, gate-owned visibility, miss
diagnosis, success rendering, and color-contract behavior.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.paths import sharded_path
from sase.core.time import get_timezone
from sase.main.plan_pending import (
    PendingPlanAmbiguity,
    PendingPlanMatch,
    PendingPlanMiss,
    pending_plans,
    resolve_pending_plan_selector,
)
from sase.main.plan_pending_diagnosis import miss_error_code
from sase.main.plan_pending_render import (
    render_ambiguity,
    _render_approve_success,
    render_miss,
)
from sase.notifications.models import Notification
from sase.notifications.pending_actions import mark_already_handled
from sase.notifications.store import append_notification

_LIVE_AGENT_TS = "20260613120000"
_DEAD_AGENT_TS = "19990101000000"
_SEPT_2026 = datetime(2026, 9, 24, 12, 0, 0)


@pytest.fixture(autouse=True)
def _no_live_plan_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to no live planner rows; shell-backed gates stay visible."""
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        lambda notifications: (),
    )
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents",
        lambda: (),
    )


@pytest.fixture(autouse=True)
def _live_gate_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every gate id to a live (non-terminal) gate shell."""
    monkeypatch.setattr(
        "sase.gate_turn.store.find_gate_turn_by_gate_id",
        lambda project, gate_id: _shell_record(terminal=False),
    )


def _archived_plan(name: str, *, ts: datetime | None = None) -> Path:
    path = Path(sharded_path("plans", name, ts=ts or _SEPT_2026))
    path.write_text(
        f"---\ntier: tale\ntitle: {path.stem.replace('_', ' ').title()}\n"
        f"goal: G\n---\n# {path.stem}\n",
        encoding="utf-8",
    )
    return path


def _append_notification(
    notification_id: str,
    plan_file: Path,
    *,
    agent_name: str = "0qw",
    agent_timestamp: str | None = None,
    request_id: str | None = None,
    dismissed: bool = False,
    minutes_ago: int = 4,
    bundle_plan: Path | None = None,
) -> None:
    response_dir = plan_file.parent / f"{notification_id}.resp"
    response_dir.mkdir(parents=True, exist_ok=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    action_data = {
        "agent_name": agent_name,
        "agent_cl_name": "demo-cl",
        "original_plan_file": str(plan_file),
        "response_dir": str(response_dir),
    }
    if agent_timestamp:
        action_data["agent_timestamp"] = agent_timestamp
    if request_id:
        action_data["request_id"] = request_id
    append_notification(
        Notification(
            id=notification_id,
            timestamp=(
                datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)
            ).isoformat(),
            sender="plan",
            files=[str(bundle_plan or plan_file)],
            action="PlanApproval",
            action_data=action_data,
            dismissed=dismissed,
        )
    )


def _shell_record(*, terminal: bool) -> Any:
    return SimpleNamespace(is_terminal=terminal)


def _pending_shell(
    monkeypatch: pytest.MonkeyPatch, gate_id: str, *, terminal: bool
) -> None:
    record = _shell_record(terminal=terminal)

    def _find(project: Any, wanted: str) -> Any:
        return record if wanted == gate_id else None

    monkeypatch.setattr("sase.gate_turn.store.find_gate_turn_by_gate_id", _find)


def _live_agent(name: str = "planner") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-cl",
        project_file="/tmp/demo-project.sase",
        status="PLAN",
        start_time=None,
        raw_suffix=_LIVE_AGENT_TS,
        agent_name=name,
        workspace_dir="/work/demo-project",
    )


# --- selector matrix ---------------------------------------------------------


def _two_pending_plans() -> tuple[Path, Path]:
    first = _archived_plan("updates_tab_cached_open.md")
    second = _archived_plan("bead_relocation_safe_epic_launch.md")
    _append_notification(
        "35553907-aaaa",
        first,
        agent_name="0qw",
        request_id="gate-aaa",
        minutes_ago=4,
    )
    _append_notification(
        "35553908-bbbb",
        second,
        agent_name="0qv",
        request_id="gate-bbb",
        minutes_ago=10,
    )
    return first, second


def test_selector_accepts_every_documented_form() -> None:
    first, _ = _two_pending_plans()
    shard = first.parent.name
    forms = [
        "updates_tab_cached_open",
        "updates_tab_cached_open.md",
        f"{shard}/updates_tab_cached_open.md",
        f"plan:{shard}/updates_tab_cached_open.md",
        str(first),
        "35553907-aaaa",
        "35553907",
    ]
    for form in forms:
        outcome = resolve_pending_plan_selector(form)
        assert isinstance(outcome, PendingPlanMatch), form
        assert outcome.plan.notification.id == "35553907-aaaa", form


def test_selector_accepts_bundle_plan_path(tmp_path: Path) -> None:
    first, _ = _two_pending_plans()
    bundle_plan = tmp_path / "plan.md"
    bundle_plan.write_text("# bundle\n", encoding="utf-8")
    _append_notification(
        "99999999-cccc",
        first,
        agent_name="0qx",
        request_id="gate-ccc",
        bundle_plan=bundle_plan,
    )
    outcome = resolve_pending_plan_selector(str(bundle_plan))
    assert isinstance(outcome, PendingPlanMatch)
    assert outcome.plan.notification.id == "99999999-cccc"
    assert outcome.plan.matched_by == "path"


def test_selector_accepts_agent_spellings() -> None:
    _two_pending_plans()
    for form in ("0qw", "@0qw", "0qw--plan", "0qw--gate"):
        outcome = resolve_pending_plan_selector(form)
        assert isinstance(outcome, PendingPlanMatch), form
        assert outcome.plan.notification.id == "35553907-aaaa", form


def test_selector_is_case_insensitive() -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("UPDATES_TAB_CACHED_OPEN")
    assert isinstance(outcome, PendingPlanMatch)
    assert outcome.plan.notification.id == "35553907-aaaa"
    outcome = resolve_pending_plan_selector("0QW")
    assert isinstance(outcome, PendingPlanMatch)
    assert outcome.plan.notification.id == "35553907-aaaa"


def test_exact_full_id_beats_prefix() -> None:
    plan = _archived_plan("exact_beats_prefix.md")
    _append_notification("abc123", plan, agent_name="0qw", request_id="g1")
    other = _archived_plan("exact_beats_prefix_other.md")
    _append_notification("abc123-extra", other, agent_name="0qv", request_id="g2")
    outcome = resolve_pending_plan_selector("abc123")
    assert isinstance(outcome, PendingPlanMatch)
    assert outcome.plan.notification.id == "abc123"


def test_bare_name_never_prefix_matches() -> None:
    foo = _archived_plan("agent_session_wire_cutover.md")
    foo_finish = _archived_plan("agent_session_wire_cutover_finish.md")
    _append_notification("id-foo", foo, agent_name="0qw", request_id="g1")
    _append_notification("id-foo-finish", foo_finish, agent_name="0qv", request_id="g2")
    outcome = resolve_pending_plan_selector("agent_session_wire_cutover")
    assert isinstance(outcome, PendingPlanMatch)
    assert outcome.plan.notification.id == "id-foo"


def test_agent_ambiguity_reports_matched_by() -> None:
    _two_pending_plans()
    third = _archived_plan("third_plan.md")
    _append_notification("id-third", third, agent_name="0qw", request_id="g3")
    outcome = resolve_pending_plan_selector("0qw")
    assert isinstance(outcome, PendingPlanAmbiguity)
    assert len(outcome.candidates) == 2
    assert all(candidate.matched_by == "agent" for candidate in outcome.candidates)
    stream = io.StringIO()
    render_ambiguity(outcome, pending_plans(), console=Console(file=stream, width=120))
    assert "matched by agent" in stream.getvalue()


def test_id_prefix_ambiguity_reports_matched_by() -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("3555390")
    assert isinstance(outcome, PendingPlanAmbiguity)
    assert all(candidate.matched_by == "ID prefix" for candidate in outcome.candidates)


def test_user_exact_invocations_diagnose_never_gated() -> None:
    plan = _archived_plan("unrelated_red_gate_bead_close.md")
    shard = plan.parent.name
    for form in (
        f"{shard}/unrelated_red_gate_bead_close.md",
        "unrelated_red_gate_bead_close.md",
    ):
        outcome = resolve_pending_plan_selector(form)
        assert isinstance(outcome, PendingPlanMiss), form
        assert outcome.header.startswith("unrelated_red_gate_bead_close"), form
        assert "No approval gate was ever opened" in " ".join(outcome.detail_lines), (
            form
        )
        assert miss_error_code(outcome) == "not_found", form


# --- visibility --------------------------------------------------------------


def test_turn_backed_gate_visible_with_done_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _archived_plan("shell_visible.md")
    _append_notification(
        "id-shell",
        plan,
        agent_name="0qw",
        agent_timestamp=_LIVE_AGENT_TS,
        request_id="gate-live",
    )
    _pending_shell(monkeypatch, "gate-live", terminal=False)
    assert [p.notification.id for p in pending_plans()] == ["id-shell"]


def test_turn_backed_gate_visible_when_dismissed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _archived_plan("shell_dismissed.md")
    _append_notification(
        "id-dismissed", plan, agent_name="0qw", request_id="gate-d", dismissed=True
    )
    _pending_shell(monkeypatch, "gate-d", terminal=False)
    assert [p.notification.id for p in pending_plans()] == ["id-dismissed"]


def test_answered_or_cancelled_shell_is_invisible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _archived_plan("shell_done.md")
    _append_notification("id-done", plan, agent_name="0qw", request_id="gate-done")
    _pending_shell(monkeypatch, "gate-done", terminal=True)
    assert pending_plans() == ()


def _no_gate_turn_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.gate_turn.store.find_gate_turn_by_gate_id",
        lambda project, gate_id: None,
    )


def test_legacy_live_planner_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_gate_turn_record(monkeypatch)
    plan = _archived_plan("legacy_live.md")
    _append_notification(
        "id-legacy",
        plan,
        agent_name="planner",
        agent_timestamp=_LIVE_AGENT_TS,
    )
    monkeypatch.setattr(
        "sase.main.plan_candidates._load_live_plan_agents_for_notifications",
        lambda notifications: (_live_agent(),),
    )
    assert [p.notification.id for p in pending_plans()] == ["id-legacy"]


def test_legacy_orphan_is_invisible(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_gate_turn_record(monkeypatch)
    plan = _archived_plan("legacy_orphan.md")
    _append_notification(
        "id-orphan",
        plan,
        agent_name="planner",
        agent_timestamp=_DEAD_AGENT_TS,
    )
    assert pending_plans() == ()


# --- miss diagnosis ----------------------------------------------------------


def test_miss_approved_as_tale() -> None:
    plan = _archived_plan("was_tale.md")
    _append_notification("id-tale", plan, agent_name="0qw", request_id="g-tale")
    mark_already_handled("id-tale", source="test", action="tale")
    outcome = resolve_pending_plan_selector("was_tale")
    assert isinstance(outcome, PendingPlanMiss)
    assert "was already approved as a tale" in " ".join(outcome.detail_lines)
    assert miss_error_code(outcome) == "conflict_already_handled"


def test_miss_rejected() -> None:
    plan = _archived_plan("was_rejected.md")
    _append_notification("id-rej", plan, agent_name="0qw", request_id="g-rej")
    mark_already_handled("id-rej", source="test", action="reject")
    outcome = resolve_pending_plan_selector("was_rejected")
    assert isinstance(outcome, PendingPlanMiss)
    assert "was already rejected" in " ".join(outcome.detail_lines)
    assert miss_error_code(outcome) == "conflict_already_handled"


def test_miss_stale() -> None:
    plan = _archived_plan("went_stale.md")
    aged = time.time() - 3 * 24 * 60 * 60
    with pytest.MonkeyPatch().context() as patcher:
        patcher.setattr(time, "time", lambda: aged)
        _append_notification("id-stale", plan, agent_name="0qw", request_id="g-stale")
    outcome = resolve_pending_plan_selector("went_stale")
    assert isinstance(outcome, PendingPlanMiss)
    assert "expired" in " ".join(outcome.detail_lines)
    assert miss_error_code(outcome) == "gone_stale"


def test_miss_orphaned_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_gate_turn_record(monkeypatch)
    plan = _archived_plan("orphaned_plan.md")
    _append_notification(
        "id-orphan-gate",
        plan,
        agent_name="0qw",
        agent_timestamp=_DEAD_AGENT_TS,
        request_id="gate-missing",
    )
    outcome = resolve_pending_plan_selector("orphaned_plan")
    assert isinstance(outcome, PendingPlanMiss)
    assert "orphaned" in " ".join(outcome.detail_lines)
    assert miss_error_code(outcome) == "not_found"


def test_miss_unknown_suggests_close_names() -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("updates_tab_cached_opne")
    assert isinstance(outcome, PendingPlanMiss)
    assert outcome.header == "no pending plan matches `updates_tab_cached_opne`"
    assert "updates_tab_cached_open" in outcome.suggestions
    assert miss_error_code(outcome) == "not_found"


def test_omitted_plan_miss_zero_and_multiple() -> None:
    outcome = resolve_pending_plan_selector(None)
    assert isinstance(outcome, PendingPlanMiss)
    assert "no pending plan proposals" in outcome.header
    _two_pending_plans()
    outcome = resolve_pending_plan_selector(None)
    assert isinstance(outcome, PendingPlanMiss)
    assert "multiple pending plan proposals" in outcome.header


# --- rendering ---------------------------------------------------------------


def test_success_rendering_leads_with_name(capsys: pytest.CaptureFixture[str]) -> None:
    _two_pending_plans()
    (plan,) = [p for p in pending_plans() if p.name == "updates_tab_cached_open"]
    _render_approve_success(
        plan, "Approved as tale", "35553907-aaaa", "/tmp/response.json"
    )
    out = capsys.readouterr().out
    assert "✓" in out
    assert "updates_tab_cached_open" in out


def test_miss_rendering_ends_with_awaiting_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("no_such_plan_xyz")
    assert isinstance(outcome, PendingPlanMiss)
    render_miss(outcome, pending_plans())
    err = capsys.readouterr().err
    assert "✗" in err
    assert "Awaiting approval (2)" in err
    assert "updates_tab_cached_open" in err


def test_color_contract_no_color_wins(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("no_such_plan_xyz")
    assert isinstance(outcome, PendingPlanMiss)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    render_miss(outcome, pending_plans())
    assert "\x1b[" not in capsys.readouterr().err


def test_color_contract_force_color(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_pending_plans()
    outcome = resolve_pending_plan_selector("no_such_plan_xyz")
    assert isinstance(outcome, PendingPlanMiss)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    render_miss(outcome, pending_plans())
    assert "\x1b[" in capsys.readouterr().err


# --- plan_names --------------------------------------------------------------


def test_plan_names_import_stays_light() -> None:
    probe = (
        "import sys, sase.plan_names; "
        "loaded = set(sys.modules); "
        "bad = [m for m in loaded if m == 'rich' or m.startswith(('rich.', 'sase.ace', 'sase.notifications', 'sase.sdd'))]; "
        "assert not bad, bad; "
        "assert sase.plan_names.plan_name('202609/foo.md') == 'foo'; "
        "print('light-ok')"
    )
    env = dict(os.environ, PYTHONPATH="src")
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "light-ok" in completed.stdout
