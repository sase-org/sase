"""Stranded Enter-target placement, ordering, and footer labels."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.tui.actions.agents._agent_enter_models import CLAN_EMPTY_MESSAGE
from sase.ace.tui.actions.agents._agent_enter_resolver import (
    enter_action_label_for_targets,
)
from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.agent import Agent
from sase.bead.stranded import StrandedReport
from sase.bead.stranded_presentation import STRANDED_GLYPH
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

from ._agent_enter_targets_helpers import (
    _matching_action_data,
    _notification,
    _resolve,
    _sources,
)
from ._agent_unread_helpers import make_agent

_CLAN = "testclan"
_GEN = "20260918010101"


@pytest.fixture(autouse=True)
def _clear_stranded_cache() -> None:
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _seed_stranded(bead_id: str = "sase-demo.1") -> None:
    verdict = StrandedWorkVerdict(
        bead_id=bead_id,
        kind="phase",
        state="stranded",
        reason="kept",
        last_turn=f"{bead_id}--3",
    )
    report = StrandedWorkReport(
        verdicts=(verdict,),
        stranded_ids=(bead_id,),
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(report=report, titles={}, generated_at=1.0),
        "test",
    )


def _owner(bead_id: str = "sase-demo.1") -> Agent:
    return replace(
        make_agent(name="~", status="DONE", raw_suffix="20260918020202"),
        phase_bead_id=bead_id,
        agent_name=bead_id,
    )


def _clan_member(
    name: str,
    status: str,
    *,
    suffix: str,
    bead_id: str | None = None,
) -> Agent:
    member = replace(
        make_agent(name=name, status=status, raw_suffix=suffix),
        agent_clan=_CLAN,
        agent_clan_generation=_GEN,
    )
    if bead_id is not None:
        member = replace(member, phase_bead_id=bead_id, agent_name=bead_id)
    return member


def _clan_container(members: list[Agent]) -> Agent:
    container = replace(
        make_agent(name=_CLAN, raw_suffix=_GEN),
        is_clan_container=True,
        agent_clan=_CLAN,
        agent_clan_generation=_GEN,
    )
    container.runtime_children = list(members)
    return container


def test_owner_row_offers_stranded_before_patch() -> None:
    _seed_stranded()
    agent = replace(
        make_agent(name="sase-demo.1", status="DONE", raw_suffix="20260918020202"),
        phase_bead_id="sase-demo.1",
        agent_name="sase-demo.1",
    )
    resolution = _resolve(agent)
    assert _sources(resolution) == ["stranded", "patch"]
    [stranded, patch] = resolution.targets
    assert stranded.kind == "stranded"
    assert stranded.label == "resolve stranded"
    assert stranded.detail == "sase-demo.1"
    assert stranded.badge == STRANDED_GLYPH
    assert stranded.bead_id == "sase-demo.1"
    assert stranded.project_key == "demo"
    assert patch.kind == "patch"
    assert enter_action_label_for_targets(resolution.targets) == "choose action"


def test_lone_stranded_footer_label() -> None:
    _seed_stranded()
    resolution = _resolve(_owner())
    stranded_only = (resolution.targets[0],)
    assert enter_action_label_for_targets(stranded_only) == "resolve stranded"


def test_waiting_row_offers_stranded_target() -> None:
    _seed_stranded()
    waiter = replace(
        make_agent(name="waiter", status="WAITING", raw_suffix="20260918030303"),
        waiting_for_beads=("sase-demo.1",),
        phase_bead_id="sase-demo.2",
        agent_name="sase-demo.2",
    )
    resolution = _resolve(waiter)
    assert "stranded" in _sources(resolution)
    stranded = next(item for item in resolution.targets if item.kind == "stranded")
    assert stranded.bead_id == "sase-demo.1"


def test_gate_still_sorts_before_stranded() -> None:
    _seed_stranded()
    agent = replace(
        make_agent(name="sase-demo.1", status="DONE", raw_suffix="20260918020202"),
        phase_bead_id="sase-demo.1",
        agent_name="sase-demo.1",
    )
    notification = _notification(
        "n-sudo",
        "SudoRequest",
        action_data=_matching_action_data(agent),
    )
    resolution = _resolve(agent, [notification])
    assert _sources(resolution)[0] == "notification"
    assert "stranded" in _sources(resolution)
    assert _sources(resolution)[-1] == "patch"


def test_clan_with_stranded_leaf_replaces_empty_message() -> None:
    _seed_stranded()
    first = _clan_member(
        "sase-demo.1", "DONE", suffix="20260918020202", bead_id="sase-demo.1"
    )
    second = _clan_member("other", "DONE", suffix="20260918030303")
    clan = _clan_container([first, second])
    resolution = _resolve(clan)
    assert resolution.empty_message is None
    assert "stranded" in _sources(resolution)
    stranded = next(item for item in resolution.targets if item.kind == "stranded")
    assert stranded.bead_id == "sase-demo.1"


def test_clan_without_stranded_keeps_empty_message() -> None:
    first = _clan_member("~", "PLAN", suffix="20260918020202")
    second = _clan_member("plan", "PLAN", suffix="20260918030303")
    clan = _clan_container([first, second])
    resolution = _resolve(clan)
    assert resolution.targets == ()
    assert resolution.empty_message == CLAN_EMPTY_MESSAGE
