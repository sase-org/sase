"""Rendered-Markdown tests for the prompt preview modal."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Markdown, Static

from sase.ace.tui.modals.preview_panel_modal import (
    PreviewPanelModal,
    _fence_leading_yaml_frontmatter,
)
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_LINES
from tests.ace.tui.modals.preview_panel_modal_test_helpers import (
    _PreviewModalTestApp,
    _markdown_payload,
    _payload,
    _wait_for_modal_state,
)


def test_fence_leading_yaml_frontmatter() -> None:
    assert _fence_leading_yaml_frontmatter("---\ntitle: Demo\n---\n\n# Body\n") == (
        "```yaml\n---\ntitle: Demo\n---\n```\n\n# Body\n"
    )
    assert _fence_leading_yaml_frontmatter("# Body\n---\nnot frontmatter\n") == (
        "# Body\n---\nnot frontmatter\n"
    )
    assert _fence_leading_yaml_frontmatter("---\ntitle: Demo\n") == "---\ntitle: Demo\n"


async def test_preview_modal_opens_markdown_payload_rendered_by_default() -> None:
    app = _PreviewModalTestApp(_markdown_payload(default_view="rendered"))

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        await _wait_for_modal_state(
            pilot,
            lambda: modal._view_mode == "rendered",  # noqa: SLF001
        )

        source = modal.query_one("#preview-content", Static)
        rendered = modal.query_one("#preview-rendered", Markdown)
        title = modal.query_one("#preview-title", Static)

        assert source.display is False
        assert rendered.display is True
        assert "R source" in modal._build_footer()  # noqa: SLF001
        assert "PROPOSAL RENDERED" in title.render().plain


async def test_preview_modal_r_toggles_rendered_markdown_back_to_source() -> None:
    app = _PreviewModalTestApp(_markdown_payload(default_view="rendered"))

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        await _wait_for_modal_state(
            pilot,
            lambda: modal._view_mode == "rendered",  # noqa: SLF001
        )

        await pilot.press("R")
        await pilot.pause()

        source = modal.query_one("#preview-content", Static)
        rendered = modal.query_one("#preview-rendered", Markdown)

        assert modal._view_mode == "source"  # noqa: SLF001
        assert source.display is True
        assert rendered.display is False
        assert "R rendered" in modal._build_footer()  # noqa: SLF001


async def test_preview_modal_r_warns_for_non_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []
    app = _PreviewModalTestApp(_payload())

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()

    assert notifications == [("This preview is not Markdown", "warning")]


async def test_preview_modal_oversized_markdown_falls_back_to_source_and_warns_on_r(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []
    large_content = "\n".join("line" for _ in range(PLAIN_RENDER_MAX_LINES + 1))
    app = _PreviewModalTestApp(
        _markdown_payload(default_view="rendered", content=large_content)
    )

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal._view_mode == "source"  # noqa: SLF001
        assert modal.query_one("#preview-content", Static).display is True
        assert modal.query_one("#preview-rendered", Markdown).display is False

        await pilot.press("R")
        await pilot.pause()

    assert notifications == [
        ("This preview is too large to render as Markdown", "warning")
    ]
