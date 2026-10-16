"""Tests for the live clan Summary WAVES ladder."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_hint_cache import (
    agent_hint_render_cache_key,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent

_START = datetime(2026, 10, 15, 12, 0, 0)


def _member(
    suffix: str,
    status: str,
    minute: int,
    *,
    waits: tuple[str, ...] = (),
    phase_bead: str | None = None,
    epic_bead: str | None = None,
) -> Agent:
    member = make_clan_agent(
        f"research.{suffix}",
        status=status,
        start=_START + timedelta(minutes=minute),
        stop=_START + timedelta(minutes=minute + 1)
        if status in {"DONE", "FAILED"}
        else None,
    )
    member.waiting_for = list(waits)
    member.phase_bead_id = phase_bead
    member.epic_bead_id = epic_bead
    return member


def _render(members: list[Agent], level: FoldLevel) -> tuple[Agent, str]:
    container = project_clan_tree(members)[0]
    return container, build_clan_detail_text(container, fold_level=level).plain


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        ("FAILED", "wave 1 failed"),
        ("QUESTION", "wave 1 needs you"),
        ("RUNNING", "wave 1 in flight"),
        ("DONE", "all waves done"),
        ("WAITING", "not started"),
    ),
)
def test_wave_heading_phrase_uses_worst_state_first(
    state: str,
    expected: str,
) -> None:
    _container, detail = _render(
        [
            _member("first", state, 0),
            _member(
                "second",
                "DONE" if state == "DONE" else "WAITING",
                1,
                waits=("research.first",),
            ),
        ],
        FoldLevel.COLLAPSED,
    )

    assert expected in detail


def test_seal_heading_identifies_failed_epic_land() -> None:
    _container, detail = _render(
        [
            _member("phase", "DONE", 0, phase_bead="sase-demo.1"),
            _member(
                "land",
                "FAILED",
                1,
                waits=("research.phase",),
                epic_bead="sase-demo",
            ),
        ],
        FoldLevel.COLLAPSED,
    )

    assert "land failed" in detail
    assert "∎" in detail


def test_after_column_compresses_more_than_three_predecessors() -> None:
    members = [
        _member(suffix, "DONE", minute)
        for minute, suffix in enumerate(("one", "two", "three", "four"))
    ]
    members.append(
        _member(
            "five",
            "WAITING",
            5,
            waits=(
                "research.one",
                "research.two",
                "research.three",
                "research.four",
            ),
        )
    )

    _container, detail = _render(members, FoldLevel.EXPANDED)

    assert "after wave 1" in detail
    assert "after research.one" not in detail


def test_after_column_reports_ghosts_and_external_waits() -> None:
    _container, detail = _render(
        [
            _member(
                "waiter",
                "WAITING",
                0,
                waits=("research.dismissed", "foreign.agent"),
            )
        ],
        FoldLevel.EXPANDED,
    )

    assert "1 dismissed" in detail
    assert "+1 outside" in detail


def test_fully_expanded_ladder_names_each_live_predecessor() -> None:
    _container, detail = _render(
        [
            _member("first", "RUNNING", 0),
            _member("second", "WAITING", 1, waits=("research.first",)),
        ],
        FoldLevel.FULLY_EXPANDED,
    )

    assert ".second  waits on .first ▶" in detail


def test_ladder_singular_and_zero_wave_wording() -> None:
    _container, detail = _render(
        [
            _member("phase", "DONE", 0, phase_bead="sase-demo.1"),
            _member(
                "land",
                "WAITING",
                1,
                waits=("research.phase",),
                epic_bead="sase-demo",
            ),
        ],
        FoldLevel.COLLAPSED,
    )

    assert "1 + land" in detail
    assert "1 waves" not in detail
    assert "1 WAVES" not in detail

    solo = _member("solo", "DONE", 0)
    cyc_first = _member("cyc1", "WAITING", 1, waits=("research.cyc2",))
    cyc_second = _member("cyc2", "WAITING", 2, waits=("research.cyc1",))
    _mixed, mixed_detail = _render([solo, cyc_first, cyc_second], FoldLevel.COLLAPSED)

    assert "1 wave ·" in mixed_detail
    assert "1 waves" not in mixed_detail

    first = _member("first", "WAITING", 0, waits=("research.second",))
    second = _member("second", "WAITING", 1, waits=("research.first",))
    _cycle, cycle_detail = _render([first, second], FoldLevel.COLLAPSED)

    assert "0 waves" not in cycle_detail
    assert "·  ·" not in cycle_detail
    assert "wait cycle" in cycle_detail


def test_ladder_non_contiguous_predecessors_share_roster_phrase() -> None:
    members = [
        _member("one", "DONE", 0),
        _member("two", "DONE", 1),
        _member("extra", "DONE", 2),
        _member("three", "DONE", 3, waits=("research.one",)),
        _member("four", "DONE", 4, waits=("research.three",)),
        _member(
            "five",
            "WAITING",
            5,
            waits=(
                "research.one",
                "research.two",
                "research.extra",
                "research.four",
            ),
        ),
    ]
    _container, detail = _render(members, FoldLevel.EXPANDED)

    # More than three predecessors compress to waves, never to a member count.
    assert "after 4 members" not in detail
    assert "after waves 1, 3" in detail


def test_hint_cache_key_tracks_wave_and_member_render_signatures() -> None:
    container = project_clan_tree(
        [
            _member("first", "RUNNING", 0),
            _member("second", "WAITING", 1, waits=("research.first",)),
        ]
    )[0]
    widget = SimpleNamespace()

    baseline = agent_hint_render_cache_key(widget, container)
    original = container.clan_waves
    assert original is not None
    changed_first_wave = replace(original.waves[0], state=original.waves[1].state)
    container.clan_waves = replace(
        original,
        waves=(changed_first_wave, *original.waves[1:]),
    )
    assert agent_hint_render_cache_key(widget, container) != baseline

    changed_summary = container.clan_waves
    assert changed_summary is not None
    second_view = changed_summary.members[-1]
    container.clan_waves = replace(
        changed_summary,
        members=(
            *changed_summary.members[:-1],
            replace(second_view, predecessors=()),
        ),
    )
    assert agent_hint_render_cache_key(widget, container) != baseline

    container.clan_waves = original
    baseline = agent_hint_render_cache_key(widget, container)
    container.runtime_children[-1].status = "RUNNING"
    assert agent_hint_render_cache_key(widget, container) != baseline
