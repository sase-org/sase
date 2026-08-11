"""Tests for bead waits in the Agents-tab wait modal."""

from __future__ import annotations

from textual.widgets import Input, OptionList, Static

from sase.ace.tui.models.wait_bead_catalog import WaitBeadCatalog
from sase.ace.tui.modals.wait_modal import WaitModal, WaitModalResult
from tests.ace.tui._wait_modal_helpers import (
    WaitModalTestApp as _TestApp,
    await_bead_catalog as _await_bead_catalog,
    bead as _bead,
    bead_catalog as _bead_catalog,
    sync_loader as _sync_loader,
)


async def test_modal_beads_field_is_editable_and_round_trips_prefill() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_waiting_for_beads=["sase-87.2", "sase-87.3"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        beads_input = modal.query_one("#beads-input", Input)
        assert beads_input.value == "sase-87.2, sase-87.3"

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=["sase-87.2", "sase-87.3"],
    )


async def test_modal_run_now_cancels_bead_waits() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_waiting_for_beads=["sase-87.2"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=[],
        run_now=True,
    )


async def test_modal_beads_field_parses_order_preserving_deduplicated_ids() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = "sase-2, sase-1, sase-2"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result is not None
    assert result.beads == ["sase-2", "sase-1"]


async def test_modal_clearing_beads_keeps_agents_wait() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            current_waiting_for=["planner"],
            current_waiting_for_beads=["sase-1"],
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = ""
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=["planner"],
        time_token=None,
        beads=[],
    )


async def test_modal_clearing_every_field_returns_run_now() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            current_waiting_for=["planner"],
            current_waiting_for_beads=["sase-1"],
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#agents-input", Input).value = ""
        modal.query_one("#beads-input", Input).value = ""
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=[],
        run_now=True,
    )


async def test_modal_bead_completion_filters_by_id_and_title_then_tab_inserts() -> None:
    catalog = _bead_catalog(
        _bead("sase-1", title="Fix login bug"),
        _bead("sase-2", title="Improve throughput"),
    )

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            bead_project_key="proj",
            bead_catalog_loader=_sync_loader(catalog),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = "login"
        await pilot.pause()

        option_list = modal.query_one("#bead-completion", OptionList)
        assert option_list.option_count == 1

        beads_input.value = "throughput"
        await pilot.pause()
        assert option_list.option_count == 1

        beads_input.value = ""
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        assert beads_input.value == "sase-1, "


async def test_modal_risky_wait_guard_requires_second_enter() -> None:
    result: WaitModalResult | None = None
    catalog = _bead_catalog(_bead("sase-1"))

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            bead_project_key="proj",
            bead_catalog_loader=_sync_loader(catalog),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = "sase-nope"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result is None
        assert beads_input.has_focus
        footer = modal.query_one("#wait-footer", Static)
        assert "enter again" in footer.render().plain

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=["sase-nope"],
    )


async def test_modal_editing_beads_disarms_risky_wait_guard() -> None:
    catalog = _bead_catalog(_bead("sase-1"))

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            bead_project_key="proj",
            bead_catalog_loader=_sync_loader(catalog),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = "sase-nope"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert modal._bead_guard_armed is True

        beads_input.value = "sase-nope2"
        await pilot.pause()

        assert modal._bead_guard_armed is False


async def test_modal_unavailable_bead_store_reports_neutral_and_never_arms_guard() -> (
    None
):
    result: WaitModalResult | None = None
    catalog = _bead_catalog(available=False)

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            bead_project_key="proj",
            bead_catalog_loader=_sync_loader(catalog),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        beads_input.value = "sase-anything"
        await pilot.pause()

        preview = modal.query_one("#beads-preview", Static)
        assert "unavailable" in preview.render().plain

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=["sase-anything"],
    )


async def test_modal_own_bead_excluded_from_candidates_and_errors_when_typed() -> None:
    catalog = _bead_catalog(_bead("sase-1"), _bead("sase-2"))
    captured: dict[str, object] = {}

    def loader(
        project_key: str | None, *, own_bead_ids: frozenset[str] = frozenset()
    ) -> WaitBeadCatalog:
        captured["own_bead_ids"] = own_bead_ids
        filtered = tuple(
            candidate
            for candidate in catalog.candidates
            if candidate.bead_id not in own_bead_ids
        )
        return WaitBeadCatalog(candidates=filtered, available=True)

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            bead_project_key="proj",
            own_bead_ids=frozenset({"sase-2"}),
            bead_catalog_loader=loader,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        assert captured["own_bead_ids"] == frozenset({"sase-2"})

        beads_input = modal.query_one("#beads-input", Input)
        beads_input.focus()
        await pilot.pause()

        option_list = modal.query_one("#bead-completion", OptionList)
        assert option_list.option_count == 1

        beads_input.value = "sase-2"
        await pilot.pause()

        preview = modal.query_one("#beads-preview", Static)
        assert "own bead" in preview.render().plain


async def test_modal_enter_on_focused_bead_completion_list_accepts_highlighted() -> (
    None
):
    catalog = _bead_catalog(_bead("sase-1"))

    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            bead_project_key="proj",
            bead_catalog_loader=_sync_loader(catalog),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        await _await_bead_catalog(modal, pilot)

        modal.query_one("#beads-input", Input).focus()
        await pilot.pause()
        modal.query_one("#bead-completion", OptionList).focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        beads_input = modal.query_one("#beads-input", Input)
        assert beads_input.value == "sase-1, "
