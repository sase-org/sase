"""Mounted Textual tests for AliasHistoryModal (load lifecycle, jump, actions)."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from textual.widgets import OptionList, Static
from textual.worker import WorkerState

import sase.ace.tui.modals.alias_history_modal as alias_history_modal
from sase.ace.tui.modals.alias_history_modal import AliasHistoryModal
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from tests._alias_history_helpers import make_entry, make_group, make_run, make_view
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for


def _stub_load(monkeypatch, result_view) -> MagicMock:
    call = MagicMock(return_value=result_view)
    monkeypatch.setattr(alias_history_modal, "load_alias_history", call)
    return call


def _blocking_load(monkeypatch, result_view):
    started = threading.Event()
    release = threading.Event()

    def load(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return result_view

    monkeypatch.setattr(alias_history_modal, "load_alias_history", load)
    return started, release


# -- loading state ------------------------------------------------------


async def test_modal_paints_loading_option_before_worker_completes(monkeypatch) -> None:
    started, release = _blocking_load(monkeypatch, make_view([make_group("large", [])]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, started.is_set)

        option_list = modal.query_one("#alias-history-list", OptionList)
        assert option_list.option_count == 1
        assert option_list.get_option_at_index(0).disabled is True
        assert "Loading" in str(option_list.get_option_at_index(0).prompt)
        usage = str(modal.query_one("#alias-history-usage", Static).content)
        assert "Model usage · loading…" in usage

        release.set()
        await wait_for(pilot, lambda: modal._view is not None)


async def test_modal_cancels_worker_on_unmount(monkeypatch) -> None:
    started, release = _blocking_load(monkeypatch, make_view([make_group("large", [])]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, started.is_set)
        worker = modal._load_worker
        assert worker is not None

        pilot.app.pop_screen()
        await pilot.pause()
        release.set()

        assert worker.is_cancelled


# -- rendering / grouping -------------------------------------------------


async def test_modal_single_alias_renders_runs_without_group_header(
    monkeypatch,
) -> None:
    runs = [make_run(artifact_dir="/tmp/newest"), make_run(artifact_dir="/tmp/oldest")]
    _stub_load(monkeypatch, make_view([make_group("large", runs)]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        option_list = modal.query_one("#alias-history-list", OptionList)
        ids = [str(option.id) for option in option_list.options]
        assert ids == ["large:/tmp/newest", "large:/tmp/oldest"]


async def test_modal_bucket_renders_grouped_headers_with_single_spacer(
    monkeypatch,
) -> None:
    view = make_view(
        [
            make_group("research_a", [make_run(artifact_dir="/tmp/a1")]),
            make_group("research_b", [make_run(artifact_dir="/tmp/b1")]),
        ]
    )
    _stub_load(monkeypatch, view)
    entry = make_entry(("research_a", "research_b"), title_label="research")

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        option_list = modal.query_one("#alias-history-list", OptionList)
        ids = [str(option.id) for option in option_list.options]
        assert ids == [
            "__group__:research_a",
            "research_a:/tmp/a1",
            "__spacer__:research_b",
            "__group__:research_b",
            "research_b:/tmp/b1",
        ]
        assert option_list.get_option(ids[0]).disabled is True
        assert option_list.get_option("__spacer__:research_b").disabled is True


# -- errors -----------------------------------------------------------------


async def test_modal_load_error_warns_and_stays_usable(monkeypatch) -> None:
    def raising(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(alias_history_modal, "load_alias_history", raising)
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await wait_for(
            pilot,
            lambda: (
                modal._load_worker is None
                or modal._load_worker.state
                in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED)
            ),
        )
        await pilot.pause()

        modal.notify.assert_called_once()
        assert modal.notify.call_args.kwargs.get("severity") == "warning"
        option_list = modal.query_one("#alias-history-list", OptionList)
        assert option_list.option_count == 1
        assert option_list.get_option_at_index(0).disabled is True


# -- selection preservation and re-query actions -----------------------------


async def test_modal_preserves_selection_across_refresh(monkeypatch) -> None:
    runs = [make_run(artifact_dir="/tmp/a"), make_run(artifact_dir="/tmp/b")]
    call = _stub_load(monkeypatch, make_view([make_group("large", runs)]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        option_list = modal.query_one("#alias-history-list", OptionList)
        option_list.highlighted = option_list.get_option_index("large:/tmp/b")

        await pilot.press("r")
        await wait_for(pilot, lambda: call.call_count == 2)
        await pilot.pause()

        assert modal._highlighted_option_id() == "large:/tmp/b"


async def test_modal_ctrl_j_adds_page_size_and_reloads_cached(monkeypatch) -> None:
    monkeypatch.setattr(alias_history_modal, "get_ace_page_size", lambda: 100)
    call = _stub_load(
        monkeypatch, make_view([make_group("large", [make_run()])], limit_per_alias=10)
    )
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)
        assert modal._limit == 10

        await pilot.press("ctrl+j")
        await wait_for(pilot, lambda: call.call_count == 2)
        await pilot.pause()

        _, kwargs = call.call_args
        assert kwargs["limit_per_alias"] == 110
        assert kwargs["freshness"] == "cached"


async def test_modal_ctrl_k_unloads_to_initial_limit(monkeypatch) -> None:
    monkeypatch.setattr(alias_history_modal, "get_ace_page_size", lambda: 100)

    def load(aliases, *, limit_per_alias=None, **kwargs):
        del aliases, kwargs
        limit = 10 if limit_per_alias is None else limit_per_alias
        return make_view([make_group("large", [make_run()])], limit_per_alias=limit)

    call = MagicMock(side_effect=load)
    monkeypatch.setattr(alias_history_modal, "load_alias_history", call)
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)
        assert modal._limit == 10

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert call.call_count == 1

        await pilot.press("ctrl+j")
        await wait_for(pilot, lambda: call.call_count == 2)
        await wait_for(pilot, lambda: modal._limit == 110)

        await pilot.press("ctrl+k")
        await wait_for(pilot, lambda: call.call_count == 3)
        await wait_for(pilot, lambda: modal._limit == 10)
        assert call.call_args.kwargs["limit_per_alias"] == 10
        assert call.call_args.kwargs["freshness"] == "cached"


async def test_modal_r_revalidates_then_next_load_is_cached(monkeypatch) -> None:
    call = _stub_load(monkeypatch, make_view([make_group("large", [make_run()])]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        await pilot.press("r")
        await wait_for(pilot, lambda: call.call_count == 2)
        await pilot.pause()
        assert call.call_args.kwargs["freshness"] == "revalidate"

        await pilot.press("ctrl+j")
        await wait_for(pilot, lambda: call.call_count == 3)
        await pilot.pause()
        assert call.call_args.kwargs["freshness"] == "cached"


async def test_modal_dot_toggles_hidden_and_updates_footer(monkeypatch) -> None:
    def load(aliases, *, include_hidden, **kwargs):
        return make_view(
            [make_group("large", [make_run()])], include_hidden=include_hidden
        )

    call = MagicMock(side_effect=load)
    monkeypatch.setattr(alias_history_modal, "load_alias_history", call)
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)
        footer_before = str(modal.query_one("#alias-history-footer", Static).content)
        assert "excluded" in footer_before

        await pilot.press(".")
        await wait_for(pilot, lambda: call.call_count == 2)
        await pilot.pause()

        assert call.call_args.kwargs["include_hidden"] is True
        footer_after = str(modal.query_one("#alias-history-footer", Static).content)
        assert "showing" in footer_after


# -- navigation and jump -----------------------------------------------------


async def test_modal_navigation_skips_group_headers_and_spacers(monkeypatch) -> None:
    view = make_view(
        [
            make_group("a", [make_run(artifact_dir="/tmp/a1")]),
            make_group("b", [make_run(artifact_dir="/tmp/b1")]),
        ]
    )
    _stub_load(monkeypatch, view)
    entry = make_entry(("a", "b"), title_label="research")

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        assert modal._highlighted_option_id() == "a:/tmp/a1"
        await pilot.press("j")
        await pilot.pause()
        assert modal._highlighted_option_id() == "b:/tmp/b1"


async def test_modal_jump_targets_only_selectable_runs(monkeypatch) -> None:
    view = make_view(
        [
            make_group("a", [make_run(artifact_dir="/tmp/a1")]),
            make_group("b", [make_run(artifact_dir="/tmp/b1")]),
        ]
    )
    _stub_load(monkeypatch, view)
    entry = make_entry(("a", "b"), title_label="research")

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        assert modal._jump_target_keys() == ["a:/tmp/a1", "b:/tmp/b1"]


# -- prompt preview -----------------------------------------------------------


async def test_modal_enter_opens_prompt_preview(monkeypatch, tmp_path) -> None:
    prompt_path = tmp_path / "raw_xprompt.md"
    prompt_path.write_text("# The prompt\n", encoding="utf-8")
    run = make_run(artifact_dir=str(tmp_path))
    _stub_load(monkeypatch, make_view([make_group("large", [run])]))
    entry = make_entry(("large",), title_label="@large")

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PreviewPanelModal))

        preview = pilot.app.screen
        assert isinstance(preview, PreviewPanelModal)
        assert preview._payload.content == "# The prompt\n"
        assert preview._payload.lexer == "markdown"


async def test_modal_enter_warns_when_prompt_missing(monkeypatch, tmp_path) -> None:
    run = make_run(artifact_dir=str(tmp_path / "does-not-exist"))
    _stub_load(monkeypatch, make_view([make_group("large", [run])]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        await pilot.press("enter")
        await wait_for(pilot, lambda: modal.notify.called)
        await pilot.pause()

        assert pilot.app.screen is modal
        modal.notify.assert_called_once()
        assert modal.notify.call_args.kwargs.get("severity") == "warning"


# -- copy reference -----------------------------------------------------------


async def test_modal_y_copies_durable_agent_reference(monkeypatch) -> None:
    run = make_run(agent_name="worker_1")
    _stub_load(monkeypatch, make_view([make_group("large", [run])]))
    entry = make_entry(("large",))

    monkeypatch.setattr(
        alias_history_modal, "reference_for_agent_name", lambda name: f"agent:{name}"
    )
    copy_mock = MagicMock()
    monkeypatch.setattr(alias_history_modal, "schedule_copy_delivery", copy_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        await pilot.press("y")
        await pilot.pause()

        copy_mock.assert_called_once()
        args, kwargs = copy_mock.call_args
        assert args[1] == "@agent:worker_1"
        assert kwargs["copied_label"] == "agent reference (agent:worker_1)"


async def test_modal_y_warns_when_agent_has_no_durable_name(monkeypatch) -> None:
    run = make_run(agent_name=None)
    _stub_load(monkeypatch, make_view([make_group("large", [run])]))
    entry = make_entry(("large",))
    copy_mock = MagicMock()
    monkeypatch.setattr(alias_history_modal, "schedule_copy_delivery", copy_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._view is not None)

        await pilot.press("y")
        await pilot.pause()

        copy_mock.assert_not_called()
        modal.notify.assert_called_once()
        assert modal.notify.call_args.kwargs.get("severity") == "warning"


# -- model-usage strip --------------------------------------------------------


async def test_modal_usage_strip_shows_counts_after_load(monkeypatch) -> None:
    runs = [
        make_run(artifact_dir="/tmp/a", model="opus", llm_provider="claude"),
        make_run(artifact_dir="/tmp/b", model="opus", llm_provider="claude"),
        make_run(artifact_dir="/tmp/c", model="sonnet", llm_provider="claude"),
    ]
    _stub_load(monkeypatch, make_view([make_group("large", runs)]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._usage is not None)

        usage = str(modal.query_one("#alias-history-usage", Static).content)
        assert "Model usage" in usage
        assert "3 runs" in usage
        assert "opus" in usage
        assert modal._usage is not None
        assert modal._usage.counted_runs == 3


async def test_modal_load_more_refresh_and_hidden_repaint_usage(monkeypatch) -> None:
    monkeypatch.setattr(alias_history_modal, "get_ace_page_size", lambda: 10)

    def load(aliases, *, limit_per_alias=None, include_hidden=False, **kwargs):
        del aliases, kwargs
        if include_hidden:
            runs = [
                make_run(artifact_dir="/tmp/a", model="opus"),
                make_run(artifact_dir="/tmp/hidden", model="haiku", hidden=True),
            ]
            return make_view(
                [make_group("large", runs)], include_hidden=True, limit_per_alias=10
            )
        count = 10 if limit_per_alias is None or limit_per_alias <= 10 else 20
        runs = [
            make_run(artifact_dir=f"/tmp/{index}", model="opus")
            for index in range(count)
        ]
        return make_view(
            [make_group("large", runs)],
            include_hidden=False,
            limit_per_alias=count,
        )

    call = MagicMock(side_effect=load)
    monkeypatch.setattr(alias_history_modal, "load_alias_history", call)
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._usage is not None)
        assert modal._usage is not None
        assert modal._usage.counted_runs == 10
        first = modal._usage

        await pilot.press("ctrl+j")
        await wait_for(pilot, lambda: call.call_count == 2)
        await wait_for(
            pilot, lambda: modal._usage is not None and modal._usage is not first
        )
        assert modal._usage is not None
        assert modal._usage.counted_runs == 20
        more_text = str(modal.query_one("#alias-history-usage", Static).content)
        assert "20 runs" in more_text
        after_more = modal._usage

        await pilot.press("r")
        await wait_for(pilot, lambda: call.call_count == 3)
        await wait_for(
            pilot, lambda: modal._usage is not None and modal._usage is not after_more
        )
        assert modal._usage is not None
        assert modal._usage.counted_runs == 20
        after_refresh = modal._usage

        await pilot.press(".")
        await wait_for(pilot, lambda: call.call_count == 4)
        await wait_for(
            pilot,
            lambda: modal._usage is not None and modal._usage is not after_refresh,
        )
        assert modal._usage is not None
        assert modal._usage.counted_runs == 2
        hidden_text = str(modal.query_one("#alias-history-usage", Static).content)
        assert "2 runs" in hidden_text


async def test_modal_highlight_move_does_not_recompute_usage(monkeypatch) -> None:
    runs = [
        make_run(artifact_dir="/tmp/a", model="opus"),
        make_run(artifact_dir="/tmp/b", model="sonnet"),
    ]
    _stub_load(monkeypatch, make_view([make_group("large", runs)]))
    entry = make_entry(("large",))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = AliasHistoryModal(entry)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._usage is not None)
        usage_before = modal._usage

        await pilot.press("j")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()

        assert modal._usage is usage_before


# -- close --------------------------------------------------------------------


async def test_modal_escape_dismisses_to_none(monkeypatch) -> None:
    _stub_load(monkeypatch, make_view([make_group("large", [make_run()])]))
    entry = make_entry(("large",))
    result: object = "unset"

    async with ModelsPanelTestApp().run_test() as pilot:

        def on_dismiss(value: None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(AliasHistoryModal(entry), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result is None
