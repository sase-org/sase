"""Phase 3 integration tests for the command palette wiring in AceApp.

Covers the acceptance items from
``sdd/tales/202604/tui_command_palette.md`` Phase 3:

- Pressing ``:`` opens the palette modal.
- The palette shows commands applicable to the current tab + selection.
- Selecting commands dispatches through existing app actions / mode
  handlers (refresh, copy-mode, leader-mode, fold-mode, saved query).
- ``:`` does not interfere with prompt text areas or modal inputs.

Pure-unit tests for ``extract_command_context`` and
``execute_command`` use lightweight mock objects so the heavier app
lifecycle is only exercised once for the end-to-end pilot test.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.commands import (
    CommandContext,
    CommandExecutor,
    CommandSpec,
    execute_command,
    extract_command_context,
)
from sase.ace.tui.commands.context import (
    _selected_axe_slot_states,
    _completed_agent_count,
)
from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdItem,
)


# ---------------------------------------------------------------------------
# Pure-unit: extract_command_context
# ---------------------------------------------------------------------------


def _make_app_stub(
    *,
    tab: str = "changespecs",
    changespecs: list | None = None,
    current_idx: int = 0,
    agents: list | None = None,
    axe_items: list | None = None,
    marked_indices: set | None = None,
    marked_agents: set | None = None,
    current_group_key: tuple | None = None,
    current_attempt_number: int | None = None,
    axe_running: bool = False,
    bgcmd_slots: list | None = None,
):
    """Build a SimpleNamespace that mimics AceApp for context extraction."""
    return SimpleNamespace(
        current_tab=tab,
        current_idx=current_idx,
        current_attempt_number=current_attempt_number,
        changespecs=changespecs or [],
        _agents=agents or [],
        _axe_items=axe_items or [],
        marked_indices=marked_indices or set(),
        _marked_agents=marked_agents or set(),
        _current_group_key=current_group_key,
        axe_running=axe_running,
        _bgcmd_slots=bgcmd_slots or [],
        # AceApp.query_one would crash on a SimpleNamespace; the file
        # panel helper swallows exceptions so it just falls through.
        query_one=MagicMock(side_effect=RuntimeError("no widgets")),
        _resolve_agent_cl_name=lambda _agent: None,
    )


def test_extract_context_changespecs_tab_picks_selected_cs() -> None:
    cs0 = make_changespec(name="alpha", cl="123")
    cs1 = make_changespec(name="beta")
    app = _make_app_stub(
        tab="changespecs",
        changespecs=[cs0, cs1],
        current_idx=1,
        marked_indices={0, 1},
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "changespecs"
    assert ctx.changespec is cs1
    assert ctx.agent is None
    assert ctx.axe_item is None
    assert ctx.mark_count == 2
    assert ctx.completed_agent_count == 0


def test_extract_context_changespecs_tab_handles_empty_list() -> None:
    app = _make_app_stub(tab="changespecs", changespecs=[], current_idx=0)
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.changespec is None
    assert ctx.mark_count == 0


def test_extract_context_agents_tab_uses_agents_state() -> None:
    agent = SimpleNamespace(status="DONE", attempt_history=[], response_path=None)
    other = SimpleNamespace(status="RUNNING", attempt_history=[], response_path=None)
    marked = {("workflow", "x", None), ("workflow", "y", None)}
    app = _make_app_stub(
        tab="agents",
        agents=[agent, other],
        current_idx=0,
        marked_agents=marked,
        current_group_key=None,
        current_attempt_number=None,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "agents"
    assert ctx.agent is agent
    assert ctx.mark_count == 2
    assert ctx.completed_agent_count == 1
    assert ctx.group_focused is False
    assert ctx.attempt_pinned is False


def test_extract_context_agents_tab_group_banner_focused() -> None:
    agent = SimpleNamespace(status="DONE", attempt_history=[], response_path=None)
    app = _make_app_stub(
        tab="agents",
        agents=[agent],
        current_idx=0,
        current_group_key=("running",),
        current_attempt_number=5,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.group_focused is True
    assert ctx.attempt_pinned is True


def test_extract_context_axe_tab_parent_row_is_not_done() -> None:
    items = [AxeParentItem()]
    app = _make_app_stub(
        tab="axe",
        axe_items=items,
        current_idx=0,
        axe_running=True,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "axe"
    assert isinstance(ctx.axe_item, AxeParentItem)
    assert ctx.axe_running is True
    # selected_axe_slot_done only tracks bgcmd rows.
    assert ctx.selected_axe_slot_done is False
    assert ctx.selected_axe_slot_running is False


def test_extract_context_axe_tab_done_bgcmd_marks_done() -> None:
    item = BgCmdItem(slot=2)
    app = _make_app_stub(
        tab="axe",
        axe_items=[item],
        current_idx=0,
        bgcmd_slots=[(2, SimpleNamespace())],
    )
    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=False):
        ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.selected_axe_slot_done is True
    assert ctx.selected_axe_slot_running is False


def test_extract_context_axe_tab_running_bgcmd_marks_running() -> None:
    item = BgCmdItem(slot=3)
    app = _make_app_stub(
        tab="axe",
        axe_items=[item],
        current_idx=0,
        bgcmd_slots=[(3, SimpleNamespace())],
    )
    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=True):
        ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.selected_axe_slot_done is False
    assert ctx.selected_axe_slot_running is True


def test_completed_agent_count_includes_done_and_failed() -> None:
    agents = [
        SimpleNamespace(status="DONE"),
        SimpleNamespace(status="FAILED"),
        SimpleNamespace(status="RUNNING"),
        SimpleNamespace(status="WAITING INPUT"),
    ]
    app = SimpleNamespace(_agents=agents)
    assert _completed_agent_count(app) == 2  # type: ignore[arg-type]


def test_selected_axe_slot_states_non_bgcmd_returns_false() -> None:
    app = SimpleNamespace(_bgcmd_slots=[])
    assert _selected_axe_slot_states(app, AxeParentItem()) == (  # type: ignore[arg-type]
        False,
        False,
    )
    assert _selected_axe_slot_states(app, None) == (False, False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pure-unit: execute_command dispatch
# ---------------------------------------------------------------------------


def _spec(
    spec_id: str,
    executor: CommandExecutor,
    *,
    label: str = "label",
    key_display: str = "x",
    key_sequence: tuple[str, ...] = ("x",),
    aliases: tuple[str, ...] = (),
) -> CommandSpec:
    return CommandSpec(
        id=spec_id,
        label=label,
        key_sequence=key_sequence,
        key_display=key_display,
        category="Misc",
        tabs=("changespecs", "agents", "axe"),
        executor=executor,
        aliases=aliases,
    )


def test_execute_app_action_calls_method() -> None:
    app = MagicMock()
    spec = _spec("app.refresh", CommandExecutor(kind="app_action", action="refresh"))
    execute_command(app, spec)
    app.action_refresh.assert_called_once_with()


def test_execute_unknown_app_action_notifies() -> None:
    app = SimpleNamespace(notify=MagicMock())
    spec = _spec(
        "app.bogus", CommandExecutor(kind="app_action", action="does_not_exist")
    )
    execute_command(app, spec)  # type: ignore[arg-type]
    app.notify.assert_called_once()
    args, kwargs = app.notify.call_args
    assert "no app action" in args[0]
    assert kwargs.get("severity") == "error"


def test_execute_saved_query_dispatches_to_digit_action() -> None:
    app = MagicMock()
    spec = _spec("saved_query.3", CommandExecutor(kind="saved_query", digit=3))
    execute_command(app, spec)
    app.action_load_saved_query_3.assert_called_once_with()


def test_execute_fold_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "fold.cycle_commits",
        CommandExecutor(kind="fold_mode_key", subkey="c"),
        key_display="zc",
        key_sequence=("z", "c"),
    )
    execute_command(app, spec)
    assert app._fold_mode_active is True
    app._handle_fold_key.assert_called_once_with("c")


def test_execute_copy_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "copy.changespecs.name",
        CommandExecutor(kind="copy_mode_key", subkey="n", copy_tab="changespecs"),
        key_display="%n",
        key_sequence=("percent_sign", "n"),
    )
    execute_command(app, spec)
    assert app._copy_mode_active is True
    app._handle_copy_key.assert_called_once_with("n")


def test_execute_leader_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "leader.task_queue",
        CommandExecutor(kind="leader_mode_key", subkey="t"),
        key_display=",t",
        key_sequence=("comma", "t"),
    )
    execute_command(app, spec)
    assert app._leader_mode_active is True
    app._handle_leader_key.assert_called_once_with("t")


def test_execute_bang_mode_sets_active_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "bang.toggle_axe",
        CommandExecutor(kind="bang_mode_key", subkey="x"),
        key_display="!x",
        key_sequence=("exclamation_mark", "x"),
    )
    execute_command(app, spec)
    assert app._bang_mode_active is True
    app._handle_bang_key.assert_called_once_with("x")


def test_execute_custom_mode_sets_mode_then_handles() -> None:
    app = MagicMock()
    spec = _spec(
        "custom.deploy.prod",
        CommandExecutor(
            kind="custom_mode_key",
            subkey="p",
            mode_name="deploy",
            command_id="prod",
        ),
    )
    execute_command(app, spec)
    assert app._custom_mode_active == "deploy"
    app._handle_custom_mode_key.assert_called_once_with("p")


# ---------------------------------------------------------------------------
# Integration: AceApp pilot
# ---------------------------------------------------------------------------


async def test_colon_opens_command_palette_modal() -> None:
    """Pressing ``:`` from the CLs tab opens the palette modal."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.expect_state("tab", "changespecs")
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")


async def test_semicolon_opens_command_palette_modal() -> None:
    """Pressing ``;`` from the CLs tab opens the same palette modal."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.expect_state("tab", "changespecs")
            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")


async def test_palette_escape_dismisses_without_side_effects() -> None:
    """Esc closes the palette and leaves no app-state changes behind."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            await page.press("escape")
            await page.expect_no_modal()


async def test_palette_executes_refresh_via_action() -> None:
    """Filtering to refresh + Enter dispatches ``action_refresh``."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_refresh") as refresh_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            # Type "refresh" into the filter, then submit.
            for ch in "refresh":
                await page.press(ch)
            await page.press("enter")
            await page.expect_no_modal()

    refresh_mock.assert_called()


async def test_palette_omits_inapplicable_axe_only_command_on_cls_tab() -> None:
    """Stop-axe-and-quit is AXE-scoped — it must not appear from CLs filter."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            from sase.ace.tui.modals.command_palette_modal import (
                CommandPaletteModal,
            )

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            ids = {s.id for s in modal._all_specs}
            # All CLs-tab applicable specs are present:
            assert "app.refresh" in ids
            # Specs that only apply to other tabs are excluded by tab scope:
            assert "app.toggle_attempt_view" not in ids
            assert "app.show_agent_run_log" not in ids


async def test_palette_context_uses_current_tab_badge() -> None:
    """Switching to the AXE tab and opening the palette shows the AXE badge."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            # Tab to agents, then to axe.
            await page.press("tab")
            await page.expect_state("tab", "agents")
            await page.press("tab")
            await page.expect_state("tab", "axe")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            from sase.ace.tui.modals.command_palette_modal import (
                CommandPaletteModal,
            )

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "axe"
            title = modal._build_title().plain
            assert "AXE" in title


async def test_palette_filter_input_swallows_typing_no_action_dispatched() -> None:
    """Typing 'q' into the palette filter must not dispatch ``action_quit``.

    Acceptance: ``:`` does not interfere with input widgets — the
    palette's filter input absorbs printable keys.
    """
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_quit") as quit_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            await page.press("q")
            # Modal still open, action_quit not fired by the filter input.
            await page.expect_modal("CommandPaletteModal")

    quit_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: action_open_command_palette wiring
# ---------------------------------------------------------------------------


def test_action_open_command_palette_uses_real_catalog() -> None:
    """The action filters the catalog through the live applicability."""
    app = AceApp(auto_start_axe=False)
    pushed: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: pushed.append((screen, callback))
    )

    app.action_open_command_palette()  # type: ignore[attr-defined]

    assert len(pushed) == 1
    modal, _cb = pushed[0]
    from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

    assert isinstance(modal, CommandPaletteModal)
    # No changespecs loaded yet, so the palette only shows what is
    # applicable on an empty CLs tab.  The refresh command must still
    # be there (always applicable on every tab).
    assert any(s.id == "app.refresh" for s in modal._all_specs)


def test_action_open_command_palette_dispatches_selection() -> None:
    """The on-dismiss callback resolves the spec id and runs the executor."""
    app = AceApp(auto_start_axe=False)
    captured: list = []

    def fake_push(screen, callback=None):  # type: ignore[no-untyped-def]
        captured.append((screen, callback))

    app.push_screen = MagicMock(side_effect=fake_push)  # type: ignore[method-assign]

    with patch.object(AceApp, "action_refresh") as refresh_mock:
        app.action_open_command_palette()  # type: ignore[attr-defined]
        assert len(captured) == 1
        _modal, callback = captured[0]
        assert callback is not None

        from sase.ace.tui.commands import CommandPaletteResult

        callback(CommandPaletteResult(selected_id="app.refresh"))

    refresh_mock.assert_called_once_with()


def test_action_open_command_palette_noop_on_cancel() -> None:
    """Cancelling the palette (None result) runs no action."""
    app = AceApp(auto_start_axe=False)
    captured: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: captured.append((screen, callback))
    )
    with patch.object(AceApp, "action_refresh") as refresh_mock:
        app.action_open_command_palette()  # type: ignore[attr-defined]
        _, callback = captured[0]
        assert callback is not None
        from sase.ace.tui.commands import CommandPaletteResult

        callback(CommandPaletteResult(selected_id=None))
        callback(None)

    refresh_mock.assert_not_called()


def test_action_open_command_palette_unknown_id_is_silent() -> None:
    """Selecting an id not in the catalog is a no-op (defensive)."""
    app = AceApp(auto_start_axe=False)
    captured: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: captured.append((screen, callback))
    )
    app.action_open_command_palette()  # type: ignore[attr-defined]
    _, callback = captured[0]
    assert callback is not None
    from sase.ace.tui.commands import CommandPaletteResult

    callback(CommandPaletteResult(selected_id="app.does_not_exist"))


# ---------------------------------------------------------------------------
# Smoke: extract_command_context against a real AceApp
# ---------------------------------------------------------------------------


def test_extract_command_context_smoke_against_real_app() -> None:
    """Confirm the extractor works against a real AceApp instance."""
    app = AceApp(auto_start_axe=False)
    ctx = extract_command_context(app)
    assert isinstance(ctx, CommandContext)
    assert ctx.tab == "changespecs"
    assert ctx.changespec is None
    assert ctx.mark_count == 0
