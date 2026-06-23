"""Tests for Agents-tab zoom panel modal basics."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import _renderable_to_text, _status_text
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


def test_zoom_status_text_renders_stopped_identity() -> None:
    text = _status_text(STOPPED_STATUS)

    assert text.plain == f"{STOPPED_GLYPH} {STOPPED_STATUS}"
    assert str(text.style) == f"bold {STOPPED_COLOR}"


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
