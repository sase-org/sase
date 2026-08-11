"""Tests for the Agents-tab wait modal."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.models.wait_bead_catalog import WaitBeadCandidate, WaitBeadCatalog
from sase.ace.tui.modals.wait_modal import (
    WaitAgentCandidate,
    WaitModal,
    WaitModalResult,
    _active_fragment,
    _candidate_option,
    _prefill_time_token,
    _replace_active_fragment,
    _validate_priority_token,
    _validate_runners_token,
    _validate_time_token,
)


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


class _TestApp(App[WaitModalResult | None]):
    """Minimal app harness for wait modal tests."""

    def compose(self) -> ComposeResult:
        yield from ()


def _candidate(
    wait_name: str,
    *,
    label: str | None = None,
    status: str = "RUNNING",
) -> WaitAgentCandidate:
    return WaitAgentCandidate(
        wait_name=wait_name,
        label=label or wait_name,
        status=status,
        model="claude / sonnet",
        start_time="12:03",
        duration="2m",
    )


def _bead(
    bead_id: str,
    *,
    title: str = "Title",
    status: str = "open",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> WaitBeadCandidate:
    return WaitBeadCandidate(
        bead_id=bead_id,
        title=title,
        status=status,
        type_label="task",
        created_at="2026-01-01T00:00:00Z",
        updated_at=updated_at,
    )


def _bead_catalog(
    *candidates: WaitBeadCandidate,
    available: bool = True,
    closed_ids: frozenset[str] = frozenset(),
) -> WaitBeadCatalog:
    return WaitBeadCatalog(
        candidates=candidates, available=available, closed_ids=closed_ids
    )


def _sync_loader(
    catalog: WaitBeadCatalog,
) -> Callable[..., WaitBeadCatalog]:
    def loader(
        project_key: str | None, *, own_bead_ids: frozenset[str] = frozenset()
    ) -> WaitBeadCatalog:
        return catalog

    return loader


async def _await_bead_catalog(modal: WaitModal, pilot: object) -> None:
    worker = modal._bead_catalog_worker
    if worker is not None:
        await worker.wait()
    await pilot.pause()  # type: ignore[attr-defined]


def test_active_fragment_uses_text_after_last_comma() -> None:
    assert _active_fragment("planner, cod") == "cod"
    assert _active_fragment("planner, ") == ""


def test_replace_active_fragment_appends_comma_for_multi_select() -> None:
    assert _replace_active_fragment("", "planner") == "planner, "
    assert _replace_active_fragment("planner, cod", "coder") == "planner, coder, "


def test_wait_candidate_colors_only_compact_tribe_portion() -> None:
    configured = WaitAgentCandidate(
        wait_name="planner",
        label="planner",
        status="RUNNING",
        role="root",
        tribe="@epic",
    )
    fallback = WaitAgentCandidate(
        wait_name="reviewer",
        label="reviewer",
        status="DONE",
        tribe="@unknown",
    )

    configured_text = _candidate_option(
        configured,
        0,
        tribe_colors={"epic": "#123456"},
    ).prompt
    fallback_text = _candidate_option(
        fallback,
        1,
        tribe_colors={"unknown": "#FFD75F"},
    ).prompt

    assert isinstance(configured_text, Text)
    assert isinstance(fallback_text, Text)
    assert (
        _style_at(
            configured_text,
            configured_text.plain.index("root"),
        )
        == "dim"
    )
    assert (
        _style_at(
            configured_text,
            configured_text.plain.index("@epic"),
        )
        == "dim #123456"
    )
    assert (
        _style_at(
            fallback_text,
            fallback_text.plain.index("@unknown"),
        )
        == "dim #FFD75F"
    )


def test_time_validation_states() -> None:
    empty = _validate_time_token("")
    assert empty.valid is True
    assert empty.token is None

    duration = _validate_time_token("1h30m")
    assert duration.valid is True
    assert duration.token == "1h30m"
    assert "waits 1h30m" in duration.message

    absolute = _validate_time_token("2359")
    assert absolute.valid is True
    assert absolute.token == "2359"
    assert absolute.message.startswith("until ")

    invalid = _validate_time_token("review")
    assert invalid.valid is False


def test_time_prefill_round_trips_duration_and_absolute() -> None:
    assert _prefill_time_token(300.0, None) == "5m"
    assert _prefill_time_token(90.0, None) == "1m30s"
    assert _prefill_time_token(None, "2030-04-15T09:00:00") == "300415/0900"


def test_runners_validation_accepts_zero_and_rejects_non_integers() -> None:
    default = _validate_runners_token("")
    assert default.valid is True
    assert default.value is None

    barrier = _validate_runners_token("0")
    assert barrier.valid is True
    assert barrier.value == 0
    assert "drain barrier" in barrier.message

    assert _validate_runners_token("-1").valid is False
    assert _validate_runners_token("1.5").valid is False


def test_priority_validation_accepts_zero_and_rejects_non_integers() -> None:
    default = _validate_priority_token("")
    assert default.valid is True
    assert default.value is None
    assert "default is 10" in default.message

    highest = _validate_priority_token("0")
    assert highest.valid is True
    assert highest.value == 0
    assert "lower values start first" in highest.message

    assert _validate_priority_token("-1").valid is False
    assert _validate_priority_token("1.5").valid is False


async def test_modal_filters_and_accepts_candidate_with_tab() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(candidates=[_candidate("planner"), _candidate("coder")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        agents_input.value = "cod"
        await pilot.pause()

        option_list = modal.query_one("#agent-completion", OptionList)
        assert option_list.option_count == 1

        await pilot.press("tab")
        await pilot.pause()

        assert agents_input.value == "coder, "

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=["coder"], time_token=None, run_now=False)


async def test_modal_enter_with_time_only_returns_time_wait() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        time_input = modal.query_one("#time-input", Input)
        time_input.value = "5m"
        time_input.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token="5m", run_now=False)


async def test_modal_invalid_time_does_not_dismiss() -> None:
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_value: WaitModalResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        time_input = modal.query_one("#time-input", Input)
        time_input.value = "review"
        time_input.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert time_input.has_focus

    assert dismiss_count == 0


async def test_modal_returns_explicit_runner_threshold() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_runners=0)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        runners_input = modal.query_one("#runners-input", Input)
        assert runners_input.value == "0"
        runners_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token=None, runners=0)


async def test_modal_prefills_and_returns_explicit_priority() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_priority=20)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        assert priority_input.value == "20"
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token=None, priority=20)


async def test_modal_invalid_priority_does_not_dismiss() -> None:
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_value: WaitModalResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = WaitModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        priority_input.value = "-1"
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert priority_input.has_focus

    assert dismiss_count == 0


async def test_modal_marks_cleared_priority_for_update() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_priority=20)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        priority_input.value = ""
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        update_priority=True,
        run_now=True,
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


async def test_modal_focus_swaps_completion_list_but_time_leaves_it_unchanged() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal)
        await pilot.pause()

        agent_list = modal.query_one("#agent-completion", OptionList)
        bead_list = modal.query_one("#bead-completion", OptionList)
        assert agent_list.display is True
        assert bead_list.display is False

        modal.query_one("#beads-input", Input).focus()
        await pilot.pause()
        assert agent_list.display is False
        assert bead_list.display is True

        modal.query_one("#time-input", Input).focus()
        await pilot.pause()
        assert agent_list.display is False
        assert bead_list.display is True


async def test_modal_tab_falls_through_to_focus_next_without_highlight() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        assert agents_input.has_focus

        await pilot.press("tab")
        await pilot.pause()

        assert not agents_input.has_focus


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
