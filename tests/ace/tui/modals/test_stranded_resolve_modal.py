"""Behavioral coverage for the stranded-resolve modal."""

from __future__ import annotations

from datetime import datetime, timezone, UTC

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.modals.stranded_resolve_modal import StrandedResolveModal
from sase.ace.tui.models import agent_stranded
from sase.ace.tui.models.stranded_resolve import (
    StrandedResolveResult,
    build_stranded_resolve_view,
)
from sase.bead.stranded import StrandedReport
from sase.core.stranded_work_facade import StrandedWorkReport, StrandedWorkVerdict

ENDED = datetime(2026, 10, 22, 6, 28, tzinfo=UTC)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


@pytest.fixture(autouse=True)
def _clear_stranded_cache() -> None:
    agent_stranded._STRANDED_REPORT_CACHE.clear()
    yield
    agent_stranded._STRANDED_REPORT_CACHE.clear()


def _seed(*, last_turn: str | None = "sase-demo.1--3") -> None:
    verdict = StrandedWorkVerdict(
        bead_id="sase-demo.1",
        kind="phase",
        state="stranded",
        reason="kept",
        last_turn=last_turn,
        since=ENDED.timestamp(),
        blocks=("sase-demo",),
    )
    report = StrandedWorkReport(verdicts=(verdict,), stranded_ids=("sase-demo.1",))
    agent_stranded._STRANDED_REPORT_CACHE.set(
        "demo",
        StrandedReport(
            report=report,
            titles={"sase-demo.1": "Live proof"},
            generated_at=ENDED.timestamp() + 31 * 3600,
        ),
        "test",
    )


async def test_continue_dismisses_with_leaf() -> None:
    _seed()
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    dismissed: list[StrandedResolveResult | None] = []
    async with _TestApp().run_test(size=(80, 24)) as pilot:
        modal = StrandedResolveModal(view)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        body = str(modal.query_one("#stranded-resolve-body").render())
        assert "sase-demo.1" in body
        assert "Live proof" in body
        assert "sase-demo.1--3" in body
        await pilot.press("f")
        await pilot.pause()
    assert dismissed == [
        StrandedResolveResult(choice="continue", project="demo", leaf_id="sase-demo.1")
    ]


async def test_close_dismisses_with_leaf() -> None:
    _seed()
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    dismissed: list[StrandedResolveResult | None] = []
    async with _TestApp().run_test(size=(80, 24)) as pilot:
        modal = StrandedResolveModal(view)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
    assert dismissed == [
        StrandedResolveResult(choice="close", project="demo", leaf_id="sase-demo.1")
    ]


async def test_escape_cancels() -> None:
    _seed()
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    dismissed: list[StrandedResolveResult | None] = []
    async with _TestApp().run_test(size=(80, 24)) as pilot:
        modal = StrandedResolveModal(view)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert dismissed == [None]


async def test_continue_disabled_without_last_turn() -> None:
    _seed(last_turn=None)
    view = build_stranded_resolve_view("demo", "sase-demo.1")
    assert view is not None
    dismissed: list[StrandedResolveResult | None] = []
    async with _TestApp().run_test(size=(80, 24)) as pilot:
        modal = StrandedResolveModal(view)
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()
        footer = str(modal.query_one("#stranded-resolve-footer").render())
        assert "Continue disabled" in footer
        await pilot.press("f")
        await pilot.pause()
        assert dismissed == []
        await pilot.press("c")
        await pilot.pause()
    assert dismissed == [
        StrandedResolveResult(choice="close", project="demo", leaf_id="sase-demo.1")
    ]
