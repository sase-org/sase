"""Tests for the Agents-tab zoom panel action and modal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
from sase.ace.tui.app import AceApp
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import _renderable_to_text, _status_text
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.file_panel import AgentFilePanel


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "zoom-agent",
        "project_file": "/tmp/project/project.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 6, 12, 12, 0, 0),
        "raw_suffix": "20260612-120000",
        "agent_name": "zoom.agent",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakePanel:
    def __init__(self, content: object) -> None:
        self.content = content


class _FakeFilePanel(_FakePanel):
    def __init__(self) -> None:
        super().__init__(Text("file"))
        self._file_list = ["/tmp/one.diff", "/tmp/two.md"]
        self.current_file_index = 1


class _FakeDetail:
    def __init__(
        self,
        *,
        info: bool = False,
        file_visible: bool = True,
        tools_visible: bool = False,
        layout_swapped: bool = False,
        has_file: bool = True,
        has_tools: bool = False,
    ) -> None:
        self._info = info
        self._file_visible = file_visible
        self._tools_visible = tools_visible
        self._layout_swapped = layout_swapped
        self._has_file_content = has_file
        self._has_tools_content = has_tools
        self.attempt_view_mode = "current-only"
        self._prompt = _FakePanel(Text("metadata"))
        self._file = _FakeFilePanel()
        self._tools = _FakePanel(Text("tools"))

    def is_info_mode(self) -> bool:
        return self._info

    def is_file_visible(self) -> bool:
        return self._file_visible

    def is_tools_visible(self) -> bool:
        return self._tools_visible

    def is_layout_swapped(self) -> bool:
        return self._layout_swapped

    def query_one(self, selector: str, *_: Any) -> Any:
        return {
            "#agent-prompt-panel": self._prompt,
            "#agent-file-panel": self._file,
            "#agent-tools-panel": self._tools,
        }[selector]


class _FakeZoomApp(AgentPanelDetailMixin):
    def __init__(
        self,
        *,
        agent: Agent | None = None,
        detail: _FakeDetail | None = None,
        current_attempt_number: int | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number = current_attempt_number
        self.refresh_interval = 10
        self._agent = agent
        self._agents = [agent] if agent is not None else []
        self._agents_with_children = list(self._agents)
        self._marked_agents = set()
        self._detail = detail or _FakeDetail()
        self.pushed: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []

    def _get_selected_agent(self) -> Agent | None:
        return self._agent

    def query_one(self, selector: str, *_: Any) -> Any:
        if selector == "#agent-detail-panel":
            return self._detail
        raise KeyError(selector)

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        del callback
        self.pushed.append(screen)

    def notify(self, message: str, *, severity: str | None = None, **_: Any) -> None:
        self.notifications.append((message, severity))


@pytest.mark.parametrize(
    ("detail", "attempt", "expected"),
    [
        (_FakeDetail(file_visible=True), None, ZoomPanelTarget.FILE),
        (
            _FakeDetail(tools_visible=True, file_visible=False, has_tools=True),
            None,
            ZoomPanelTarget.TOOLS,
        ),
        (
            _FakeDetail(layout_swapped=True, tools_visible=True, has_tools=True),
            None,
            ZoomPanelTarget.METADATA,
        ),
        (_FakeDetail(info=True, file_visible=False), None, ZoomPanelTarget.METADATA),
        (_FakeDetail(file_visible=True), 2, ZoomPanelTarget.METADATA),
    ],
)
def test_action_zoom_panel_selects_expected_initial_target(
    detail: _FakeDetail,
    attempt: int | None,
    expected: ZoomPanelTarget,
) -> None:
    app = _FakeZoomApp(
        agent=_make_agent(),
        detail=detail,
        current_attempt_number=attempt,
    )

    app.action_zoom_panel()

    assert len(app.pushed) == 1
    modal = app.pushed[0]
    assert isinstance(modal, ZoomPanelModal)
    assert modal._target == expected
    assert modal._seed.attempt_view_mode == "current-only"


def test_action_zoom_panel_warns_without_agent() -> None:
    app = _FakeZoomApp(agent=None)

    app.action_zoom_panel()

    assert app.pushed == []
    assert app.notifications == [("No agent selected", "warning")]


def test_action_zoom_panel_provider_resolves_fresh_agent_by_identity() -> None:
    agent = _make_agent(status="RUNNING")
    app = _FakeZoomApp(agent=agent)

    app.action_zoom_panel()
    modal = app.pushed[0]
    refreshed = _make_agent(status="DONE")
    app._agents = [refreshed]
    app._agents_with_children = [refreshed]

    assert modal._agent_provider() is refreshed


def test_default_z_bindings_route_fold_then_zoom() -> None:
    registry = load_keymap_registry({})
    bindings = build_app_bindings(registry.app)

    assert registry.app.start_fold_mode == "z"
    assert registry.app.zoom_panel == "z"
    assert [binding.action for binding in bindings if binding.key == "z"] == [
        "start_fold_mode",
        "zoom_panel",
    ]


def test_zoom_and_fold_actions_are_tab_gated() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    changespecs_app = AceApp(auto_start_axe=False, initial_tab="changespecs")

    assert agents_app.check_action("start_fold_mode", ()) is False
    assert agents_app.check_action("zoom_panel", ()) is not False
    assert changespecs_app.check_action("zoom_panel", ()) is False
    assert changespecs_app.check_action("start_fold_mode", ()) is not False


def test_zoom_status_text_renders_stopped_identity() -> None:
    text = _status_text(STOPPED_STATUS)

    assert text.plain == f"{STOPPED_GLYPH} {STOPPED_STATUS}"
    assert str(text.style) == f"bold {STOPPED_COLOR}"


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _DetailTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _wait_for_file_content(
    pilot: Any,
    panel: Any,
    expected: str,
    *,
    attempts: int = 20,
) -> str:
    rendered = ""
    for _ in range(attempts):
        await pilot.pause()
        rendered = _renderable_to_text(getattr(panel, "content", None)) or ""
        if panel._full_content is not None and expected in rendered:
            return rendered
    assert panel._full_content is not None
    assert expected in rendered
    return rendered


async def test_zoom_modal_z_closes() -> None:
    agent = _make_agent(status="DONE")
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed metadata")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert isinstance(pilot.app.screen, ZoomPanelModal)
        await pilot.press("z")
        await pilot.pause()

        assert not isinstance(pilot.app.screen, ZoomPanelModal)


async def test_zoom_seed_uses_textual_content_and_paints_file_panel() -> None:
    file_renderable = Text("seeded file content")
    agent = _make_agent(status="DONE")

    async with _DetailTestApp().run_test(size=(120, 40)) as pilot:
        detail = pilot.app.query_one("#agent-detail-panel", AgentDetail)
        file_panel = detail.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.update(file_renderable)
        detail._has_file_content = True

        app = _FakeZoomApp(agent=agent, detail=detail)
        seed = app._zoom_seed_from_detail(detail)

        assert seed.file_renderable is not None
        assert "seeded file content" in (
            _renderable_to_text(seed.file_renderable) or ""
        )

        modal = ZoomPanelModal(
            agent_provider=lambda: None,
            initial_agent=agent,
            initial_target=ZoomPanelTarget.FILE,
            seed=seed,
            refresh_interval=10,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        zoom_file_panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert "seeded file content" in (
            _renderable_to_text(zoom_file_panel.content) or ""
        )


async def test_completed_agent_zoom_loads_seeded_file_list_without_refresh(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=tuple(agent.all_files),
            has_file_content=True,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert panel._full_content == "first file body\n"
        assert str(first_path) in rendered


async def test_zoom_next_file_shows_next_seeded_file(tmp_path: Any) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=tuple(agent.all_files),
            has_file_content=True,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "first file body")

        await pilot.press("ctrl+n")
        rendered = await _wait_for_file_content(pilot, panel, "second file body")

        assert panel.current_file_index == 1
        assert panel._full_content == "second file body\n"
        assert str(second_path) in rendered


async def test_zoom_metadata_copy_fallback_uses_textual_content() -> None:
    agent = _make_agent(status="DONE")
    modal = ZoomPanelModal(
        agent_provider=lambda: None,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("metadata copy body")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal._zoom_text() == "metadata copy body"


async def test_zoom_file_show_all_survives_periodic_refresh(tmp_path: Any) -> None:
    content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    file_path = tmp_path / "notes.md"
    file_path.write_text(content, encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(file_path)])
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(has_file_content=True),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert panel.is_trimmed  # default page trim applied after layout

        await pilot.press("equals_sign")  # show all lines
        await pilot.pause()
        assert not panel.is_trimmed

        # A periodic refresh tick must not revert the user's show-all.
        modal._refresh_active_panel(force=False)
        await pilot.pause()
        await pilot.pause()
        assert not panel.is_trimmed
