"""Tests for the teal `↪` epic-follow hand-off in rows, lanes, and timeline."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.actions.agents._epic_follow_toasts import (
    announce_epic_follow_transitions,
    epic_follow_toast_messages,
)
from sase.ace.tui.models.agent_epic_follow_progress import (
    _EPIC_FOLLOW_PROGRESS_CACHE,
    EpicFollowProgress,
    cached_epic_follow_progress_snapshot,
    warm_epic_follow_progress,
)
from sase.ace.tui.widgets._agent_list_render_agent_status import (
    append_agent_row_status,
)
from sase.ace.tui.widgets.prompt_panel._agent_wait_section import build_wait_lanes
from sase.core.wait_epic_follow_view import EpicFollowView
from tests.ace.tui.widgets._agent_display_helpers import make_agent

_SINCE = datetime(2026, 10, 6, 14, 32).timestamp()
_SINCE_TEXT = datetime.fromtimestamp(_SINCE).strftime("%H:%M")


def _follow_view(**overrides: object) -> EpicFollowView:
    defaults: dict[str, object] = {
        "target": "planner",
        "state": "following",
        "epic_ids": ("sase-7k",),
        "since": _SINCE,
    }
    defaults.update(overrides)
    return EpicFollowView(**defaults)  # type: ignore[arg-type]


def _waiting_agent(**overrides: object) -> object:
    defaults: dict[str, object] = {
        "status": "WAITING",
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
    }
    defaults.update(overrides)
    return make_agent(**defaults)


def _lane_text(agent: object, **overrides: object) -> str:
    from sase.ace.tui.widgets.prompt_panel._agent_wait_section import (
        ResponsiveWaitSection,
    )

    arguments: dict[str, object] = {
        "agent_status_buckets": {"planner": "Done"},
        "clan_wait_member_statuses": None,
        "tribe_wait_bindings": None,
        "wait_bead_statuses": None,
    }
    arguments.update(overrides)
    lanes = build_wait_lanes(agent, **arguments)  # type: ignore[arg-type]
    return ResponsiveWaitSection(lanes).logical_text.plain


def _agents_line(agent: object, **overrides: object) -> str:
    text = _lane_text(agent, **overrides)
    return next(line for line in text.splitlines() if line.startswith("Wait: [agents]"))


def test_row_launching_reads_pending_token() -> None:
    agent = _waiting_agent(
        wait_epic_follows=[_follow_view(state="launching", epic_ids=())],
    )
    text = Text()
    append_agent_row_status(text, agent)  # type: ignore[arg-type]

    assert "WAITING" in text.plain
    assert "↪ epic…" in text.plain
    assert "sase-7k" not in text.plain


def test_row_armed_without_stage_adds_no_noise() -> None:
    agent = _waiting_agent(wait_epic_follows=[])
    text = Text()
    append_agent_row_status(text, agent)  # type: ignore[arg-type]

    assert "↪" not in text.plain


def test_row_single_follow_names_epic_with_status() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    counts = WaitDependencyStatusCounts(
        agents=WaitAgentStatusCounts(done=1),
        follows=WaitBeadStatusCounts(in_progress=1),
    )
    text = Text()
    append_agent_row_status(text, agent, wait_dependency_counts=counts)  # type: ignore[arg-type]

    assert "✓1 ↪ ◐ sase-7k" in text.plain


def test_row_single_follow_cold_cache_names_epic_without_glyph() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    text = Text()
    append_agent_row_status(text, agent)  # type: ignore[arg-type]

    assert "↪ sase-7k" in text.plain
    assert "◐" not in text.plain
    assert "?" not in text.plain


def test_row_multi_follow_aggregates_status_counts() -> None:
    agent = _waiting_agent(
        wait_epic_follows=[
            _follow_view(epic_ids=("sase-7k", "sase-7m")),
        ]
    )
    counts = WaitDependencyStatusCounts(
        follows=WaitBeadStatusCounts(in_progress=2),
    )
    text = Text()
    append_agent_row_status(text, agent, wait_dependency_counts=counts)  # type: ignore[arg-type]

    assert "↪ ◐2" in text.plain


def test_row_blocked_follow_reads_red_bang() -> None:
    agent = _waiting_agent(
        wait_epic_follows=[
            _follow_view(
                state="blocked",
                epic_ids=(),
                reason="launch_ended_without_epic",
            )
        ],
    )
    text = Text()
    append_agent_row_status(text, agent)  # type: ignore[arg-type]

    assert "↪ !" in text.plain


def test_row_ignores_stale_follow_targets() -> None:
    agent = _waiting_agent(waiting_for=["other"], wait_epic_follows=[_follow_view()])
    text = Text()
    append_agent_row_status(text, agent)  # type: ignore[arg-type]

    assert "↪" not in text.plain


def test_lane_following_narrates_epic_progress_and_since() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    line = _agents_line(
        agent,
        wait_bead_statuses=(("sase-7k", "in_progress"),),
        epic_follow_progress={"sase-7k": EpicFollowProgress(2, 5)},
    )

    assert "planner ✓" in line
    assert "↪ sase-7k ◐ in progress" in line
    assert "2/5 phases" in line
    assert f"since {_SINCE_TEXT}" in line


def test_lane_launching_reads_pending_text() -> None:
    agent = _waiting_agent(
        wait_epic_follows=[_follow_view(state="launching", epic_ids=())],
    )
    line = _agents_line(agent)

    assert "↪ epic launching…" in line
    assert f"since {_SINCE_TEXT}" in line


def test_lane_blocked_names_resume_command() -> None:
    agent = _waiting_agent(
        wait_epic_follows=[
            _follow_view(
                state="blocked",
                epic_ids=(),
                reason="launch_ended_without_epic",
                resume_command="sase bead work plan:202610/x.md",
            )
        ],
    )
    line = _agents_line(agent)

    assert "↪ !" in line
    assert "epic launch ended without an epic" in line
    assert "resume: sase bead work plan:202610/x.md" in line


def test_lane_cold_cache_never_claims_bead_missing() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    line = _agents_line(agent)

    assert "↪ sase-7k" in line
    assert "?" not in line
    assert "◐" not in line


def test_lane_armed_running_target_shows_dim_hand_off() -> None:
    agent = _waiting_agent(wait_epic_follows=[])
    line = _agents_line(
        agent,
        agent_status_buckets={"planner": "Running"},
    )

    assert "planner ▶" in line
    assert "↪" in line
    assert "agent only" not in line


def test_lane_opt_out_stays_quiet_while_default_is_off() -> None:
    agent = _waiting_agent(wait_for_epics_of=[])
    line = _agents_line(agent)

    assert "agent only" not in line


def test_lane_followed_epics_leave_the_beads_lane() -> None:
    agent = _waiting_agent(
        waiting_for_beads=["sase-7k", "user-bead"],
        wait_epic_follows=[
            _follow_view(added_bead_ids=("sase-7k",)),
        ],
    )
    text = _lane_text(
        agent,
        wait_bead_statuses=(("sase-7k", "in_progress"), ("user-bead", "open")),
    )

    assert "↪ sase-7k" in text
    beads_line = next(
        line for line in text.splitlines() if line.startswith("      [beads]")
    )
    assert "user-bead" in beads_line
    assert "sase-7k" not in beads_line


def test_lane_closed_resolution_replaces_status_word() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    line = _agents_line(
        agent,
        wait_bead_statuses=(("sase-7k", "closed"),),
        epic_follow_progress={
            "sase-7k": EpicFollowProgress(1, 3, resolution="canceled")
        },
    )

    assert "↪ sase-7k ● canceled" in line


def test_timeline_milestone_names_epic_and_launcher() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    display = agent.timestamps_display  # type: ignore[attr-defined]

    assert "↪EPIC" in display
    assert "sase-7k ← planner" in display


def test_toast_coalesces_waiters_per_epic() -> None:
    previous = {1: frozenset(), 2: frozenset(), 3: frozenset()}
    current = {
        1: frozenset({("sase-7k", "planner")}),
        2: frozenset({("sase-7k", "planner")}),
        3: frozenset({("sase-7k", "planner")}),
    }
    names = {1: "a", 2: "b", 3: "c"}

    assert epic_follow_toast_messages(previous, current, names) == [
        "3 agents now wait on epic sase-7k (launched by planner)"
    ]


def test_toast_names_single_waiter_and_skips_repeats() -> None:
    edge = frozenset({("sase-7k", "planner")})
    assert epic_follow_toast_messages({1: frozenset()}, {1: edge}, {1: "reviewer"}) == [
        "reviewer now waits on epic sase-7k (launched by planner)"
    ]
    assert epic_follow_toast_messages({1: edge}, {1: edge}, {1: "reviewer"}) == []


def test_toast_never_fires_on_startup_load() -> None:
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    calls: list[str] = []

    messages = announce_epic_follow_transitions(
        calls.append,
        [],
        [agent],
        first_load=True,
    )

    assert messages == []
    assert calls == []


def test_follow_progress_warms_and_caches() -> None:
    _EPIC_FOLLOW_PROGRESS_CACHE.clear()
    agent = _waiting_agent(wait_epic_follows=[_follow_view()])
    assert cached_epic_follow_progress_snapshot(agent) == {"sase-7k": None}

    import sase.ace.tui.models.agent_epic_follow_progress as progress_module

    def _fake_read(
        project_key: str, epic_ids: object
    ) -> dict[str, EpicFollowProgress | None]:
        assert project_key == "tmp"
        return {"sase-7k": EpicFollowProgress(closed=2, total=5)}

    original = progress_module.read_epic_follow_progress
    progress_module.read_epic_follow_progress = _fake_read  # type: ignore[assignment]
    try:
        changed = warm_epic_follow_progress([agent])
    finally:
        progress_module.read_epic_follow_progress = original
        _EPIC_FOLLOW_PROGRESS_CACHE.clear()

    assert changed == {agent.identity}  # type: ignore[attr-defined]
