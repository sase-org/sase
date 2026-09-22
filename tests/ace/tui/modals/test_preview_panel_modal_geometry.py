"""Content-aware geometry tests for the prompt preview modal.

Pure sizing math lives in ``test_preview_panel_sizing.py``; the tests here
drive the modal itself (baseline/max floors, chrome guard, view toggles,
and terminal resizes).
"""

from __future__ import annotations

from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.modals.preview_panel_sizing import PanelGeometry
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from tests.ace.tui.modals.preview_panel_modal_test_helpers import (
    _PreviewModalTestApp,
    _StyledPreviewModalTestApp,
    _long_narrow_payload,
    _long_wide_payload,
    _properties_payload,
    _short_payload,
)


async def test_preview_modal_short_payload_keeps_baseline() -> None:
    app = _PreviewModalTestApp(_short_payload())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal._geometry_floor == PanelGeometry(96, 25)  # noqa: SLF001
        container = modal.query_one("#preview-modal-container", Container)
        assert container.styles.width.cells == 96
        assert container.styles.height.cells == 25


async def test_preview_modal_long_payload_hits_max() -> None:
    app = _PreviewModalTestApp(_long_narrow_payload())
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal._geometry_floor == PanelGeometry(150, 58)  # noqa: SLF001
        container = modal.query_one("#preview-modal-container", Container)
        assert container.styles.width.cells == 150
        assert container.styles.height.cells == 58

    wide_app = _PreviewModalTestApp(_long_wide_payload())
    async with wide_app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        modal = wide_app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal._geometry_floor == PanelGeometry(156, 58)  # noqa: SLF001
        container = modal.query_one("#preview-modal-container", Container)
        assert container.styles.width.cells == 156
        assert container.styles.height.cells == 58


async def test_preview_modal_chrome_guard_has_no_slack_or_scrollbar() -> None:
    payload = PreviewPayload(
        kind_label="file",
        icon="@",
        title="mid.py",
        source_path="/tmp/mid.py",
        content="\n".join(f"print({idx})" for idx in range(25)),
        lexer="python",
        reference="file:mid.py",
    )
    app = _StyledPreviewModalTestApp(payload)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        scroll = modal.query_one("#preview-scroll", VerticalScroll)
        content = modal.query_one("#preview-content", Static)
        assert scroll.max_scroll_y == 0
        assert scroll.scrollable_content_region.height == content.outer_size.height


async def test_preview_modal_toggle_never_shrinks() -> None:
    app = _StyledPreviewModalTestApp(_properties_payload())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        def container_height() -> int:
            return int(
                modal.query_one("#preview-modal-container", Container).outer_size.height
            )

        height_source = container_height()
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
        height_properties = container_height()
        assert modal._view_mode == "properties"  # noqa: SLF001
        await pilot.press("p")
        await pilot.pause()
        await pilot.pause()
        height_back = container_height()
        assert height_properties >= height_source
        assert height_back >= height_properties


async def test_preview_modal_rendered_grows_when_taller() -> None:
    content = "# A\n\nBody A.\n\n# B\n\nBody B.\n\n```python\nprint(1)\nprint(2)\n```\n"
    payload = PreviewPayload(
        kind_label="xprompt",
        icon="#",
        title="#md",
        source_path="/tmp/md.md",
        content=content,
        lexer="markdown",
        reference="#md",
        default_view="source",
    )
    app = _StyledPreviewModalTestApp(payload)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        before = int(
            modal.query_one("#preview-modal-container", Container).outer_size.height
        )
        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()
        assert modal._view_mode == "rendered"  # noqa: SLF001
        after = int(
            modal.query_one("#preview-modal-container", Container).outer_size.height
        )
        assert after >= before


async def test_preview_modal_resize_recomputes_geometry() -> None:
    app = _StyledPreviewModalTestApp(_long_narrow_payload())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        before = modal.query_one("#preview-modal-container", Container).outer_size
        assert modal._last_geometry_screen == (100, 30)  # noqa: SLF001
        await pilot.resize_terminal(160, 60)
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()
        container = modal.query_one("#preview-modal-container", Container)
        assert modal._last_geometry_screen == (160, 60)  # noqa: SLF001
        assert modal._geometry_floor == PanelGeometry(150, 58)  # noqa: SLF001
        assert container.styles.height.cells == 58
        assert container.outer_size.height >= before.height
