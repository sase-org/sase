"""Keys, modes, and preview wiring for the Node Finder modal."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.events import Key
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.base import FilterInput
from sase.ace.tui.modals.node_finder_modal import NodeFinderModal, NodeFinderResult
from sase.ace.tui.modals.node_finder_preview_loader import NodeFinderPreviewPayload
from sase.ace.tui.models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    filter_node_finder,
)
from tests.ace.tui._member_jump_navigation_helpers import make_agent


class _ModalHost(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: NodeFinderModal) -> None:
        super().__init__()
        self.modal = modal
        self.leaked: list[str] = []

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self.modal)

    def on_key(self, event: Key) -> None:
        self.leaked.append(event.key)


def _payload(agent: Any, *, prompt: str = "PROMPTTEXT", reply: str = "REPLYTEXT"):
    return NodeFinderPreviewPayload(
        identity=agent.identity,
        source_name=agent.agent_name or "stub",
        prompt=prompt,
        reply=reply,
        reply_omitted_lines=0,
        reply_omitted_chars=0,
        token=(("stub", 1, 1),),
    )


def _stub_loader(agent: Any) -> NodeFinderPreviewPayload:
    return _payload(agent)


def _node(name: str, *, parent: int | None = None, **kwargs: Any) -> NodeFinderRow:
    agent = kwargs.pop("agent", None) or make_agent(name)
    return NodeFinderRow(
        role=NodeFinderRole.NODE,
        identity=agent.identity,
        agent=agent,
        name=name,
        kind_label="AGENT",
        kind_accent="#87AFFF",
        depth=1 if parent is None else 2,
        parent_row=parent,
        jumpable=True,
        **kwargs,
    )


def _snapshot(*rows: NodeFinderRow, here: int | None = None) -> NodeFinderSnapshot:
    fixed = tuple(
        replace(row, is_here=True) if pos == here else row
        for pos, row in enumerate(rows)
    )
    jumpable = sum(1 for row in fixed if row.jumpable)
    return NodeFinderSnapshot(
        rows=fixed,
        here_row=here,
        node_count=jumpable,
    )


def _plain(widget: Static) -> str:
    return widget.render().plain


def _modal(
    *rows: NodeFinderRow,
    here: int | None = None,
    has_back: bool = False,
    loader: Any = _stub_loader,
) -> NodeFinderModal:
    return NodeFinderModal(
        _snapshot(*rows, here=here),
        has_back=has_back,
        preview_loader=loader,
    )


def test_mount_handler_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(NodeFinderModal.on_mount)


@pytest.mark.asyncio
async def test_opens_with_list_focus_and_here_row_highlighted() -> None:
    modal = _modal(_node("alpha"), _node("beta"), _node("gamma"), here=1)
    async with _ModalHost(modal).run_test(size=(160, 40)):
        option_list = modal.query_one("#node-finder-list", OptionList)
        assert option_list.has_focus
        assert option_list.highlighted == 1
        assert "beta" in option_list.get_option_at_index(1).prompt.plain


@pytest.mark.asyncio
async def test_single_key_hint_dismisses_with_identity() -> None:
    alpha = _node("alpha")
    modal = _modal(alpha, _node("beta"))
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press("0")
        assert dismissed == [NodeFinderResult(identity=alpha.identity, name="alpha")]


@pytest.mark.asyncio
async def test_two_key_hint_goes_pending_then_completes() -> None:
    rows = [_node(f"node-{index:03d}") for index in range(63)]
    snapshot = _snapshot(*rows)
    view = filter_node_finder(snapshot, "")
    two_char = next(hint for hint in view.hint_to_identity if len(hint) == 2)
    target = view.hint_to_identity[two_char]
    modal = NodeFinderModal(snapshot, preview_loader=_stub_loader)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press(two_char[0])
        assert dismissed == []
        flash = modal.query_one("#node-finder-flash", Static)
        assert f"{two_char[0]}…" in _plain(flash)
        await pilot.press(two_char[1])
        target_name = next(row.name for row in rows if row.identity == target)
        assert dismissed == [NodeFinderResult(identity=target, name=target_name)]


@pytest.mark.asyncio
async def test_backspace_and_escape_cancel_pending_prefix() -> None:
    rows = [_node(f"node-{index:03d}") for index in range(63)]
    snapshot = _snapshot(*rows)
    view = filter_node_finder(snapshot, "")
    two_char = next(hint for hint in view.hint_to_identity if len(hint) == 2)
    modal = NodeFinderModal(snapshot, preview_loader=_stub_loader)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press(two_char[0])
        await pilot.press("backspace")
        assert modal._pending == ""
        assert dismissed == []
        await pilot.press(two_char[0])
        await pilot.press("escape")
        assert modal._pending == ""
        assert dismissed == []
        await pilot.press("escape")
        assert dismissed == [None]


@pytest.mark.asyncio
async def test_invalid_keys_flash_without_dismiss_or_app_leak() -> None:
    modal = _modal(_node("alpha"), _node("beta"))
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        host = pilot.app
        assert isinstance(host, _ModalHost)
        await pilot.press("!")
        assert dismissed == []
        flash = modal.query_one("#node-finder-flash", Static)
        assert "no hint" in _plain(flash)
        assert host.leaked == []


@pytest.mark.asyncio
async def test_tab_and_slash_round_trip_search_mode() -> None:
    modal = _modal(_node("alpha"), _node("beta"))
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        query = modal.query_one("#node-finder-query", FilterInput)
        option_list = modal.query_one("#node-finder-list", OptionList)
        await pilot.press("tab")
        assert query.has_focus
        await pilot.press("shift+tab")
        assert option_list.has_focus
        await pilot.press("/")
        assert query.has_focus
        query.value = "keep-me"
        await wait_for(pilot, lambda: query.value == "keep-me")
        await pilot.press("escape")
        assert option_list.has_focus
        assert query.value == "keep-me"


@pytest.mark.asyncio
async def test_tab_after_typing_reallocates_shorter_hints() -> None:
    rows = [_node(f"node-{index:03d}") for index in range(63)]
    rows.append(_node("unique-target"))
    modal = _modal(*rows)
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        query = modal.query_one("#node-finder-query", FilterInput)
        await pilot.press("tab")
        query.value = "unique-target"
        query.post_message(Input.Changed(query, "unique-target"))
        await wait_for(pilot, lambda: len(modal._view.identity_to_hint) == 1)
        await pilot.press("tab")
        hint = next(iter(modal._view.identity_to_hint.values()))
        assert len(hint) == 1
        option_list = modal.query_one("#node-finder-list", OptionList)
        assert option_list.has_focus


@pytest.mark.asyncio
async def test_enter_jumps_in_hints_mode() -> None:
    alpha = _node("alpha")
    modal = _modal(alpha, _node("beta"), here=0)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press("enter")
        assert dismissed == [NodeFinderResult(identity=alpha.identity, name="alpha")]


@pytest.mark.asyncio
async def test_enter_jumps_in_search_mode() -> None:
    beta = _node("beta")
    modal = _modal(_node("alpha"), beta, here=1)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press("tab")
        await pilot.press("enter")
        assert dismissed == [NodeFinderResult(identity=beta.identity, name="beta")]


@pytest.mark.asyncio
async def test_cursor_wraps_and_skips_context_rows() -> None:
    header = NodeFinderRow(
        role=NodeFinderRole.PANEL,
        panel_key=None,
        jumpable=False,
        jumpable_count=2,
        hidden_count=0,
    )
    alpha = _node("alpha", parent=0)
    beta = _node("beta", parent=0)
    modal = _modal(header, alpha, beta, here=1)
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        option_list = modal.query_one("#node-finder-list", OptionList)
        assert option_list.highlighted == 1
        await pilot.press("ctrl+n")
        assert option_list.highlighted == 2
        await pilot.press("down")
        assert option_list.highlighted == 1
        await pilot.press("ctrl+p")
        assert option_list.highlighted == 2
        await pilot.press("up")
        assert option_list.highlighted == 1
        await pilot.press("tab")
        await pilot.press("ctrl+n")
        assert option_list.highlighted == 2


@pytest.mark.asyncio
async def test_clicking_a_row_dismisses_with_identity() -> None:
    alpha = _node("alpha")
    beta = _node("beta")
    modal = _modal(alpha, beta, here=0)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        option_list = modal.query_one("#node-finder-list", OptionList)
        option = option_list.get_option_at_index(1)
        option_list.post_message(OptionList.OptionSelected(option_list, option, 1))
        await wait_for(pilot, lambda: bool(dismissed))
        assert dismissed == [NodeFinderResult(identity=beta.identity, name="beta")]


@pytest.mark.asyncio
async def test_quotation_mark_back_and_flash() -> None:
    modal = _modal(_node("alpha"), has_back=True)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press('"')
        assert dismissed == [NodeFinderResult(back=True)]

    modal = _modal(_node("alpha"), has_back=False)
    dismissed = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        await pilot.press('"')
        assert dismissed == []
        flash = modal.query_one("#node-finder-flash", Static)
        assert "no jump history" in _plain(flash)


@pytest.mark.asyncio
async def test_mutating_source_agents_after_open_does_not_change_hints() -> None:
    alpha = _node("alpha")
    modal = _modal(alpha, _node("beta"))
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        before = dict(modal._view.identity_to_hint)
        assert alpha.agent is not None
        alpha.agent.agent_name = "mutated"
        alpha.agent.presented_agent_name = "mutated"
        await pilot.press("0")
        assert modal._view.identity_to_hint == before
        assert dismissed == [NodeFinderResult(identity=alpha.identity, name="alpha")]


@pytest.mark.asyncio
async def test_echoed_option_highlighted_does_not_repaint_stale_preview() -> None:
    modal = _modal(_node("alpha"), _node("beta"), here=0)
    async with _ModalHost(modal).run_test(size=(160, 40)):
        preview = modal.query_one("#node-finder-preview", Static)
        before = _plain(preview)
        option_list = modal.query_one("#node-finder-list", OptionList)
        event = OptionList.OptionHighlighted(
            option_list, option_list.get_option_at_index(1), 1
        )
        modal._highlighting = True
        modal.on_option_list_option_highlighted(event)
        assert _plain(preview) == before


@pytest.mark.asyncio
async def test_tier1_drops_stale_results() -> None:
    alpha = _node("alpha")
    modal = _modal(alpha, _node("beta"), here=0)
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        preview = modal.query_one("#node-finder-preview", Static)
        stale_generation = modal._preview_generation
        modal._preview_generation = stale_generation + 1
        await modal._load_tier1(alpha.identity, stale_generation)
        assert "PROMPTTEXT" not in _plain(preview)
        await modal._load_tier1(alpha.identity, modal._preview_generation)
        await wait_for(pilot, lambda: "PROMPTTEXT" in _plain(preview))


@pytest.mark.asyncio
async def test_tier1_hits_lru_on_revisit() -> None:
    alpha = _node("alpha")
    assert alpha.agent is not None
    modal = _modal(alpha, _node("beta"), here=0)
    modal._cache.put(_payload(alpha.agent, prompt="cached-alpha"))
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        preview = modal.query_one("#node-finder-preview", Static)
        await wait_for(pilot, lambda: "cached-alpha" in _plain(preview))


@pytest.mark.asyncio
async def test_tier1_tasks_cancel_on_unmount() -> None:
    hang = asyncio.Event()

    async def _never() -> None:
        await hang.wait()

    modal = _modal(_node("alpha"))
    async with _ModalHost(modal).run_test(size=(160, 40)) as pilot:
        from sase.ace.tui.util.pump_tasks import spawn_pump_free_task

        task = spawn_pump_free_task(
            modal,
            _never(),
            name="node-finder-preview",
            registry_attr="_node_finder_preview_tasks",
        )
        assert task is not None
        await pilot.press("escape")
        await wait_for(pilot, lambda: task.cancelled() or task.done())
        assert task.cancelled() or task.done()
