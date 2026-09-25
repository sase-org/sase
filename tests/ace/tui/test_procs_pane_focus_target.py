"""Proc focus-target tests for the Admin Center Procs pane."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import (
    AdminCenterSessionState,
    ProcsSessionState,
)
from sase.ace.tui.modals.procs_pane import ProcsPane
from sase.ace.tui.modals.procs_filter_bar import ProcsFilterBar
from tests.ace.tui._procs_pane_helpers import (
    ProcsTestApp,
    open_procs_pane,
    patch_other_panes,
    queue,
    task,
)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


async def test_focus_target_selects_a_visible_row() -> None:
    first = task("first", label="bead list", status="success", age_seconds=2)
    second = task("second", label="bead show", status="success", age_seconds=1)

    async with ProcsTestApp(queue(first, second)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)

        assert pane.focus_proc_target("first") is True
        await pilot.pause()

        selected = pane._get_selected_task()
        assert selected is not None
        assert selected.proc_id == "first"
        assert pilot.app.notifications == []


async def test_focus_target_clears_a_hiding_filter_with_a_notice() -> None:
    target = task("target", label="bead list", status="success", age_seconds=2)
    other = task("other", label="sync sase-1", status="success", age_seconds=1)
    session_state = AdminCenterSessionState(procs=ProcsSessionState(query="name:sync"))

    async with ProcsTestApp(queue(target, other)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=session_state)
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1

        assert pane.focus_proc_target("target") is True
        await pilot.pause()

        assert pane._filter_query == ""
        assert pane.query_one(ProcsFilterBar)._last_query_text == ""  # type: ignore[attr-defined]
        selected = pane._get_selected_task()
        assert selected is not None
        assert selected.proc_id == "target"
        assert pilot.app.notifications == [
            ("Filter cleared to show bead list", "information")
        ]


async def test_focus_target_returns_false_for_an_unknown_proc() -> None:
    only = task("only", label="bead list", status="success", age_seconds=1)

    async with ProcsTestApp(queue(only)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)

        assert pane.focus_proc_target("missing") is False
        assert pilot.app.notifications == []


async def test_initial_procs_tab_delivers_focus_target_on_the_app_loop() -> None:
    """A real Procs pane receives the target after its direct initial open."""
    target = task("target", label="bead list", status="success", age_seconds=1)

    async with ProcsTestApp(queue(target)).run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="procs", proc_focus_target="target")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._proc_focus_target is None)

        pane = modal.query_one("#procs", ProcsPane)
        selected = pane._get_selected_task()
        assert selected is not None
        assert selected.proc_id == "target"


class _FakeFocusPane:
    def __init__(self, *, found: bool) -> None:
        self.seen: list[str] = []
        self._found = found

    def focus_proc_target(self, proc_id: str) -> bool:
        self.seen.append(proc_id)
        return self._found


def test_modal_delivers_proc_focus_target_to_the_procs_pane() -> None:
    from sase.ace.tui.modals.config_center_modal import ConfigCenterModal

    modal = ConfigCenterModal(initial_tab="procs", proc_focus_target="p1")
    pane = _FakeFocusPane(found=True)
    modal._panes["procs"] = pane  # type: ignore[assignment]

    assert modal._deliver_proc_focus_target() is True
    assert pane.seen == ["p1"]
    assert modal._proc_focus_target is None
    # Consumed targets never redeliver.
    assert modal._deliver_proc_focus_target() is False


def test_modal_keeps_an_unresolved_focus_target() -> None:
    from sase.ace.tui.modals.config_center_modal import ConfigCenterModal

    modal = ConfigCenterModal(initial_tab="procs", proc_focus_target="p9")
    pane = _FakeFocusPane(found=False)
    modal._panes["procs"] = pane  # type: ignore[assignment]

    assert modal._deliver_proc_focus_target() is False
    assert pane.seen == ["p9"]
    assert modal._proc_focus_target == "p9"


def test_modal_without_a_focus_target_delivers_nothing() -> None:
    from sase.ace.tui.modals.config_center_modal import ConfigCenterModal

    modal = ConfigCenterModal(initial_tab="procs")
    pane = _FakeFocusPane(found=True)
    modal._panes["procs"] = pane  # type: ignore[assignment]

    assert modal._deliver_proc_focus_target() is False
    assert pane.seen == []
