"""Tests for the prompt preview modal."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class _PreviewModalTestApp(App[None]):
    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(PreviewPanelModal(self.payload))


def _payload() -> PreviewPayload:
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="src/example.py",
        source_path="/tmp/src/example.py",
        content="\n".join(f"print({idx})" for idx in range(120)),
        lexer="python",
        reference="file:src/example.py",
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
        "sase.ace.tui.modals.preview_panel_modal.copy_to_system_clipboard",
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
        "sase.ace.tui.modals.preview_panel_modal.build_editor_args",
        build_args,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.preview_panel_modal.suspend_for_external_tool",
        fake_suspend,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.preview_panel_modal.subprocess.run",
        run,
    )
    app = _PreviewModalTestApp(_payload())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

    build_args.assert_called_once_with("vim", ["/tmp/src/example.py"])
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
        "j/k scroll | ctrl+d/u page | g/G top/bottom | y contents | "
        "Y path | % copy | o editor | Z viewer | esc close"
    )


async def test_preview_modal_forwards_percent_to_app_copy_mode() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "chats"
        await page.expect_state("artifacts_subtab", "chats")
        page.app.push_screen(PreviewPanelModal(_payload()))
        await page.expect_modal("PreviewPanelModal")

        await page.press("%")

        assert page.app._copy_mode_active is True
