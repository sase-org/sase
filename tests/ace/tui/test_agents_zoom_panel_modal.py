"""Tests for Agents-tab zoom panel modal basics."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import Label

from sase.agent.status_buckets import FEEDBACK_STATUS
from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import (
    _renderable_to_text,
    _status_text,
    _ZoomToolsPanel,
)
from sase.ace.tui.models.agent_status import (
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
)
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.file_panel import AgentFilePanel

from tests.ace.tui._agents_zoom_panel_helpers import (
    _DetailTestApp,
    _FakeZoomApp,
    _ModalTestApp,
    _make_agent,
)
from tests.ace.tui.widgets._tools_panel_helpers import _entry

from sase.ace.tui.widgets.tools_panel import ToolDetailLevel


def test_zoom_status_text_renders_stopped_identity() -> None:
    text = _status_text(STOPPED_STATUS)

    assert text.plain == f"{STOPPED_GLYPH} {STOPPED_STATUS}"
    assert str(text.style) == f"bold {STOPPED_COLOR}"


def test_zoom_status_text_renders_feedback_as_terminal_magenta() -> None:
    text = _status_text(FEEDBACK_STATUS)

    assert text.plain == f"● {FEEDBACK_STATUS}"
    assert str(text.style) == "bold #FF5FD7"


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


async def test_zoom_tools_detail_level_seed_and_keys() -> None:
    agent = _make_agent(status="RUNNING")
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.TOOLS,
        seed=ZoomPanelSeed(
            tools_renderable=Text("seed tools"),
            has_tools_content=True,
            tools_detail_level=ToolDetailLevel.EXPANDED,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        panel = modal.query_one("#zoom-tools-panel", _ZoomToolsPanel)
        assert panel.detail_level == ToolDetailLevel.EXPANDED
        hint = modal.query_one("#zoom-panel-hints", Label)
        assert "h/l detail" in str(hint.content)

        panel._last_entries = (
            _entry(tool_input_summary={"command": "echo " + "x" * 120}),
        )
        panel._last_fetch_time = datetime(2026, 5, 14, 10, 30, 0)

        await pilot.press("l")
        assert panel.detail_level == ToolDetailLevel.FULL

        await pilot.press("h")
        assert panel.detail_level == ToolDetailLevel.EXPANDED
