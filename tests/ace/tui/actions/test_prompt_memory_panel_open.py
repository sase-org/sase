"""App-handler tests for opening the memory panel from the prompt bar."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow._prompt_bar_memory_panel import (
    PromptBarMemoryPanelMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.memory_panel_load import MemoryPanelInitialLoad
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _FakeTextArea:
    """Stand-in prompt pane used to pin focus restore."""

    def __init__(self, *, vim_mode: str = "insert", cursor: tuple[int, int] = (0, 4)):
        self._vim_mode = vim_mode
        self.cursor_location = cursor
        self.is_mounted = True
        self.focused = False

    def focus(self) -> None:
        self.focused = True

    def _enter_insert_mode(self) -> None:
        self._vim_mode = "insert"

    def _enter_normal_mode(self) -> None:
        self._vim_mode = "normal"


class _FakeBar:
    def __init__(self, text_area: _FakeTextArea) -> None:
        self._text_area = text_area

    def active_text_area(self) -> _FakeTextArea:
        return self._text_area


class _MemoryOpenHarness(PromptBarMemoryPanelMixin):
    """Drive the memory-panel handler without a live Textual DOM."""

    def __init__(
        self,
        bar: _FakeBar | None = None,
        *,
        prompt_context: PromptContext | None = None,
    ) -> None:
        self._prompt_context = prompt_context
        self._bar = bar
        self.opened: list[tuple[object, dict[str, object]]] = []

    def _open_config_center(self, initial_tab: object, **kwargs: object) -> None:
        self.opened.append((initial_tab, kwargs))

    def _mounted_prompt_bar(self) -> _FakeBar | None:  # type: ignore[override]
        return self._bar


class _MemoryOpenApp(PromptBarMemoryPanelMixin, App[None]):
    """Host a prompt bar and the real memory-panel handler."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self._initial_value = initial_value
        self._prompt_context = None

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode="prompt",
            id="prompt-input-bar",
        )

    def _open_config_center(self, initial_tab: object, **kwargs: object) -> None:
        self.push_screen(
            ConfigCenterModal(
                initial_tab=initial_tab,  # type: ignore[arg-type]
                config_entry=kwargs.get("config_entry"),  # type: ignore[arg-type]
            ),
            kwargs.get("on_dismissed"),  # type: ignore[arg-type]
        )


def _prompt_context(
    *, home: bool = False, workspace: str = "/tmp/sase"
) -> PromptContext:
    return PromptContext(
        project_name="sase",
        cl_name=None,
        project_file="sase/sase.yml",
        workspace_dir="" if home else workspace,
        workspace_num=1,
        workflow_name="ace(run)",
        timestamp="2026-08-17",
        history_sort_key="sase",
        display_name="sase",
        update_target="",
        is_home_mode=home,
    )


def _stub_panel_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.memory_pane.load_memory_panel_initial_state",
        lambda **_: MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None),
    )


def test_handler_opens_panel_with_seeded_note() -> None:
    text_area = _FakeTextArea(vim_mode="normal", cursor=(1, 2))
    harness = _MemoryOpenHarness(_FakeBar(text_area))

    harness.on_prompt_input_bar_memory_panel_requested(
        PromptInputBar.MemoryPanelRequested("#memory/sase_beads", "prompt")
    )

    assert len(harness.opened) == 1
    tab, kwargs = harness.opened[0]
    assert tab == "config"
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.subtab == "memory"
    assert entry.note == "sase/memory/sase_beads.md"
    assert entry.launch_workspace is None


def test_handler_passes_launch_workspace_from_prompt_context() -> None:
    harness = _MemoryOpenHarness(prompt_context=_prompt_context(workspace="/ws/sase"))

    harness.on_prompt_input_bar_memory_panel_requested(
        PromptInputBar.MemoryPanelRequested(None, "prompt")
    )

    _tab, kwargs = harness.opened[0]
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.launch_workspace == "/ws/sase"
    assert entry.note is None


def test_handler_skips_home_workspace() -> None:
    harness = _MemoryOpenHarness(prompt_context=_prompt_context(home=True))

    harness.on_prompt_input_bar_memory_panel_requested(
        PromptInputBar.MemoryPanelRequested(None, "prompt")
    )

    _tab, kwargs = harness.opened[0]
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.launch_workspace is None


def test_dismiss_restores_insert_mode_and_cursor() -> None:
    text_area = _FakeTextArea(vim_mode="insert", cursor=(0, 7))
    harness = _MemoryOpenHarness(_FakeBar(text_area))

    harness.on_prompt_input_bar_memory_panel_requested(
        PromptInputBar.MemoryPanelRequested(None, "prompt")
    )
    _tab, kwargs = harness.opened[0]
    callback = kwargs["on_dismissed"]
    assert callable(callback)

    text_area._vim_mode = "normal"
    text_area.cursor_location = (3, 0)
    text_area.focused = False
    callback(None)

    assert text_area.focused is True
    assert text_area._vim_mode == "insert"
    assert text_area.cursor_location == (0, 7)


def test_dismiss_restores_normal_mode() -> None:
    text_area = _FakeTextArea(vim_mode="normal", cursor=(2, 1))
    harness = _MemoryOpenHarness(_FakeBar(text_area))

    harness.on_prompt_input_bar_memory_panel_requested(
        PromptInputBar.MemoryPanelRequested(None, "prompt")
    )
    _tab, kwargs = harness.opened[0]
    callback = kwargs["on_dismissed"]
    assert callable(callback)

    text_area._vim_mode = "insert"
    callback(None)

    assert text_area._vim_mode == "normal"
    assert text_area.cursor_location == (2, 1)


async def test_gm_opens_panel_and_escape_restores_normal_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_panel_load(monkeypatch)
    app = _MemoryOpenApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 3)
        assert text_area._vim_mode == "normal"

        await pilot.press("g", "m")

        await wait_for(pilot, lambda: isinstance(app.screen, ConfigCenterModal))
        hub = app.screen.query_one(ConfigHubPane)
        await wait_for(pilot, lambda: hub._active_subtab == "memory")

        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, ConfigCenterModal)
        assert app.focused is text_area
        assert text_area._vim_mode == "normal"
        assert text_area.cursor_location == (0, 3)


async def test_ctrl_g_m_from_insert_restores_insert_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_panel_load(monkeypatch)
    app = _MemoryOpenApp("solo draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        assert text_area._vim_mode == "insert"
        cursor = text_area.cursor_location

        await pilot.press("ctrl+g", "m")

        await wait_for(pilot, lambda: isinstance(app.screen, ConfigCenterModal))
        hub = app.screen.query_one(ConfigHubPane)
        await wait_for(pilot, lambda: hub._active_subtab == "memory")

        await pilot.press("escape")
        await pilot.pause()

        assert app.focused is text_area
        assert text_area._vim_mode == "insert"
        assert text_area.cursor_location == cursor
