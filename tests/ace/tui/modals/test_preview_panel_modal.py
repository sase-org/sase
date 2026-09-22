"""Core interaction tests for the prompt preview modal.

Scrolling, close, clipboard, path actions, editor handoff, and chrome.
Markdown, properties, search, and geometry cases live in sibling
``test_preview_panel_modal_*`` files.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from tests.ace.tui.modals.preview_panel_modal_test_helpers import (
    _PreviewModalTestApp,
    _payload,
)


async def test_preview_modal_scrolls_and_closes() -> None:
    app = _PreviewModalTestApp(_payload())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        scroll = modal.query_one("#preview-scroll")

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], PreviewPanelModal)


async def test_preview_modal_copies_contents_and_path_off_pump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
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
        await pilot.press("y")
        await pilot.press("Y")
        await pilot.pause()
        await pilot.pause()

    assert set(copied) == {_payload().content, "/tmp/src/example.py"}
    assert ("Copied file contents", "information") in notifications
    assert ("Copied path", "information") in notifications


async def test_preview_modal_path_actions_warn_without_a_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []
    payload = replace(_payload(), source_path=None)
    app = _PreviewModalTestApp(payload)

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
        assert "Y path" not in modal._build_footer()
        assert "o editor" not in modal._build_footer()
        assert "Z viewer" not in modal._build_footer()

        await pilot.press("Y")
        await pilot.press("o")
        await pilot.press("Z")
        await pilot.pause()

    assert notifications == [
        ("This preview does not have a path to copy", "warning"),
        ("This preview does not have a file to edit", "warning"),
        ("This preview does not have a file to view", "warning"),
    ]


async def test_preview_modal_opens_source_in_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs: list[dict[str, object]] = []

    @contextmanager
    def fake_suspend(_app: object, **metadata: object) -> Iterator[None]:
        handoffs.append(metadata)
        yield

    build_args = MagicMock(return_value=["vim", "/tmp/src/example.py"])
    run = MagicMock()
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.build_jump_editor_argv",
        build_args,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.suspend_for_external_tool",
        fake_suspend,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.subprocess.run",
        run,
    )
    app = _PreviewModalTestApp(_payload())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

    build_args.assert_called_once_with("vim", "/tmp/src/example.py", None, None)
    run.assert_called_once_with(["vim", "/tmp/src/example.py"], check=False)
    assert handoffs == [
        {
            "action": "preview_open_editor",
            "tool_kind": "editor",
            "command": "vim",
            "path_count": 1,
        }
    ]


def test_preview_modal_chrome_includes_reference_path_and_dynamic_footer() -> None:
    modal = PreviewPanelModal(_payload())

    assert (
        modal._build_title().plain
        == "@ FILE  src/example.py\nfile:src/example.py  →  /tmp/src/example.py"
    )
    assert modal._build_footer() == (
        "j/k scroll | ctrl+d/u page | g/G top/bottom | / search | "
        "y contents | Y path | % copy | o editor | Z viewer | esc close"
    )
