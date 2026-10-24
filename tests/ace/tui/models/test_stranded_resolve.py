"""Memory-only stranded-resolve view models and continue prefill."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.stranded_resolve import (
    _continue_stub,
    _format_stranded_ended_at,
    blocking_line,
    build_stranded_resolve_view,
    stranded_continue_prompt,
)
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

ENDED = datetime(2026, 10, 22, 6, 28, tzinfo=UTC)
NOW = ENDED.timestamp() + 31 * 3600


@pytest.fixture(autouse=True)
def _clear_stranded_cache() -> None:
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _seed(*verdicts: StrandedWorkVerdict, titles: dict[str, str] | None = None) -> None:
    report = StrandedWorkReport(
        verdicts=verdicts,
        stranded_ids=tuple(v.bead_id for v in verdicts if v.state == "stranded"),
        blocked_ids=tuple(v.bead_id for v in verdicts if v.state == "blocked"),
    )
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(report=report, titles=titles or {}, generated_at=NOW),
        "test",
    )


def test_blocking_line_names_nearest_and_root() -> None:
    assert blocking_line(()) == ""
    assert blocking_line(("sase-1",)) == "1 bead · sase-1"
    assert (
        blocking_line(("sase-1.2", "sase-1.1", "sase-1"))
        == "3 beads · sase-1.2 … sase-1"
    )


def test_continue_prompt_prefills_bead_fork_and_stub() -> None:
    prompt = stranded_continue_prompt(
        leaf_id="sase-demo.1",
        last_turn="sase-demo.1--3",
        cause="ended with bead_action keep; nothing resumes it",
        vcs_tag="%git:main ",
        tab_name="sase",
    )
    assert prompt.startswith(
        "%git:main %tab:sase %id(bead=sase-demo.1) #fork:sase-demo.1--3 "
    )
    assert "Continue stranded phase `sase-demo.1`" in prompt
    assert (
        _continue_stub(
            leaf_id="sase-demo.1",
            last_turn="sase-demo.1--3",
            cause="ended with bead_action keep; nothing resumes it",
        )
        in prompt
    )


def test_ended_at_label_is_utc() -> None:
    assert _format_stranded_ended_at(ENDED.timestamp()) == "Oct 22 06:28"
    assert _format_stranded_ended_at(None) == ""


def test_build_view_from_warm_cache_for_stranded_leaf() -> None:
    _seed(
        StrandedWorkVerdict(
            bead_id="sase-demo.1",
            kind="phase",
            state="stranded",
            reason="kept",
            last_turn="sase-demo.1--3",
            since=ENDED.timestamp(),
            blocks=("sase-demo",),
        ),
        titles={"sase-demo.1": "Live proof"},
    )
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    assert view.focus_state == "stranded"
    assert view.title_kind == "phase"
    leaf = view.selected_leaf
    assert leaf.bead_id == "sase-demo.1"
    assert leaf.last_turn == "sase-demo.1--3"
    assert leaf.ended_at_label == "Oct 22 06:28"
    assert leaf.continue_disabled_reason is None
    assert "bead_action keep" in leaf.cause


def test_continue_disabled_without_last_turn() -> None:
    _seed(
        StrandedWorkVerdict(
            bead_id="sase-demo.1",
            kind="phase",
            state="stranded",
            reason="lost",
        )
    )
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    assert view.selected_leaf.continue_disabled_reason == "No last turn to fork"


def test_blocked_row_lists_stranded_leaves() -> None:
    _seed(
        StrandedWorkVerdict(
            "sase-demo",
            "epic",
            "blocked",
            blocked_by=("sase-demo.1", "sase-demo.2"),
        ),
        StrandedWorkVerdict(
            "sase-demo.1",
            "phase",
            "stranded",
            reason="kept",
            last_turn="sase-demo.1--3",
        ),
        StrandedWorkVerdict(
            "sase-demo.2",
            "phase",
            "stranded",
            reason="failed",
            last_turn="sase-demo.2--1",
        ),
    )
    view = build_stranded_resolve_view("demo", "sase-demo")
    assert view is not None
    assert view.focus_state == "blocked"
    assert view.title_kind == "epic"
    assert [leaf.bead_id for leaf in view.leaves] == ["sase-demo.1", "sase-demo.2"]


def test_force_stranded_refresh_expires_ttl() -> None:
    _seed(
        StrandedWorkVerdict("sase-demo.1", "phase", "stranded", reason="kept"),
    )
    assert agent_stranded.should_resolve_stranded_report("demo") is False
    agent_stranded.force_stranded_refresh("demo")
    assert agent_stranded.should_resolve_stranded_report("demo") is True
    assert agent_stranded.cached_stranded_report("demo") is not None
