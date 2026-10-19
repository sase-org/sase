"""Pilot tests for pager same-document anchor links."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sase.pager._line_mark import LineMark, reading_scroll_y
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.split import PagerSplitLayout

from ._app_helpers import body_scroll, pager_screen, pager_view


def _anchor_body() -> tuple[str, int, int]:
    lines = ["Links: [Alpha](#alpha) [Beta](#beta)"]
    lines.extend(f"filler {index}" for index in range(2, 40))
    lines.append("## Alpha")
    lines.extend(f"filler {index}" for index in range(41, 60))
    lines.append("## Beta")
    lines.extend(f"filler {index}" for index in range(61, 81))
    body = "\n".join(lines) + "\n"
    return body, 40, 60


def _anchor_document() -> PagerDocument:
    body, _, _ = _anchor_body()
    section = PagerSection(
        identity="file:/tmp/anchors.md",
        title="anchors.md",
        kind="file",
        body=body,
        subject_ref="file:/tmp/anchors.md",
    )
    return PagerDocument(
        sections=(section,), title="anchors.md", origin=PagerOrigin.FILE
    )


def _expected_scroll(app: SasePager, section_index: int, line: int) -> int:
    screen = pager_screen(app)
    assert screen._body is not None
    start_row = screen._body.section_line_rows[section_index][line - 1]
    end_row = screen._last_row_for_section_line(section_index, line)
    assert end_row is not None
    scroll = body_scroll(app)
    return reading_scroll_y(
        start_row=start_row,
        end_row=end_row,
        viewport_height=max(int(scroll.size.height), 1),
        max_scroll_y=int(scroll.max_scroll_y),
    )


async def test_follow_anchor_jumps_in_place_without_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def failing_resolve(ref: str, **_kwargs: Any) -> Any:
        calls.append(ref)
        raise AssertionError(f"resolve_ref must not run for anchors: {ref}")

    monkeypatch.setattr("sase.pager.screen.resolve_ref", failing_resolve)
    _, alpha_line, _ = _anchor_body()
    app = SasePager(_anchor_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        before = screen.document
        assert len(screen._back_trail) == 0
        await pilot.press("0")
        await pilot.pause()

        assert calls == []
        assert screen.document is before
        assert screen._goto_mark == LineMark(0, alpha_line, alpha_line)
        # The trail band appears on first follow and steals a row, so the
        # pre-trail reading position can sit one row off the post-trail one.
        assert (
            abs(int(body_scroll(app).scroll_y) - _expected_scroll(app, 0, alpha_line))
            <= 1
        )
        assert len(screen._back_trail) == 1
        assert len(screen._forward_trail) == 0


async def test_back_and_forward_keep_syntax_generation() -> None:
    _, alpha_line, _ = _anchor_body()
    app = SasePager(_anchor_document())
    async with app.run_test(size=(80, 24)) as pilot:
        view = pager_view(app)
        await pilot.pause()
        before_scroll = int(body_scroll(app).scroll_y)
        before_mark = view._goto_mark
        before_generation = view._syntax_generation
        await pilot.press("0")
        await pilot.pause()
        assert view._goto_mark == LineMark(0, alpha_line, alpha_line)
        await pilot.press("backspace")
        await pilot.pause()
        assert int(body_scroll(app).scroll_y) == before_scroll
        assert view._goto_mark == before_mark
        assert view._syntax_generation == before_generation
        await pilot.press("ctrl+i")
        await pilot.pause()
        assert view._goto_mark == LineMark(0, alpha_line, alpha_line)


async def test_multi_section_anchor_lands_in_own_section() -> None:
    first = PagerSection(
        identity="file:/tmp/first.md",
        title="first.md",
        kind="file",
        body="## Shared\nbody\n",
        subject_ref="file:/tmp/first.md",
    )
    second_body_lines = ["Links: [Shared](#shared)"]
    second_body_lines.extend(f"filler {index}" for index in range(2, 20))
    second_body_lines.append("## Shared")
    second = PagerSection(
        identity="file:/tmp/second.md",
        title="second.md",
        kind="file",
        body="\n".join(second_body_lines) + "\n",
        subject_ref="file:/tmp/second.md",
    )
    document = PagerDocument(
        sections=(first, second), title="2 files", origin=PagerOrigin.FILE
    )
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()

        assert screen._goto_mark == LineMark(1, 20, 20)


async def test_line_range_anchor_and_clamp() -> None:
    body_lines = ["Links: [Range](#L5-L7) [Past](#L9999)"]
    body_lines.extend(f"line {index}" for index in range(2, 21))
    body = "\n".join(body_lines) + "\n"
    section = PagerSection(
        identity="file:/tmp/lines.md",
        title="lines.md",
        kind="file",
        body=body,
        subject_ref="file:/tmp/lines.md",
    )
    document = PagerDocument(
        sections=(section,), title="lines.md", origin=PagerOrigin.FILE
    )
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(document)
    app.notify = notify  # type: ignore[method-assign]
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()

        assert screen._goto_mark == LineMark(0, 5, 7)
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

        assert screen._goto_mark is not None
        assert screen._goto_mark.start_line == 20
        assert any(severity == "information" for _, severity in notifications)


async def test_missing_anchor_toasts_and_keeps_document() -> None:
    body_lines = ["Links: [Missing](#nope)"]
    body_lines.extend(f"filler {index}" for index in range(2, 40))
    body_lines.append("## Real")
    body = "\n".join(body_lines) + "\n"
    section = PagerSection(
        identity="file:/tmp/missing.md",
        title="missing.md",
        kind="file",
        body=body,
        subject_ref="file:/tmp/missing.md",
    )
    document = PagerDocument(
        sections=(section,), title="missing.md", origin=PagerOrigin.FILE
    )
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(document)
    app.notify = notify  # type: ignore[method-assign]
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        assert screen._label_layer is not None
        assert screen._label_layer.labels[0].dangling is True
        before = screen.document
        await pilot.press("0")
        await pilot.pause()

        assert screen.document is before
        assert len(screen._back_trail) == 0
        assert ("No heading or anchor matches #nope in missing.md.", "warning") in (
            notifications
        )


async def test_ctrl_w_anchor_opens_split_landing_on_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_resolve(ref: str, **_kwargs: Any) -> Any:
        raise AssertionError("anchors never resolve")

    monkeypatch.setattr("sase.pager.screen.resolve_ref", failing_resolve)
    _, alpha_line, _ = _anchor_body()
    app = SasePager(_anchor_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source_scroll = int(body_scroll(app).scroll_y)
        await pilot.press("ctrl+w")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()

        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen.views[0].document is screen.views[1].document
        assert screen.views[1]._goto_mark == LineMark(0, alpha_line, alpha_line)
        assert int(screen.views[0]._body_scroll().scroll_y) == source_scroll


async def test_e_anchor_opens_editor_at_heading_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs: list[dict[str, object]] = []

    @contextmanager
    def fake_suspend(_app: object, **metadata: object):  # type: ignore[no-untyped-def]
        handoffs.append(metadata)
        yield

    run_calls: list[list[str]] = []
    monkeypatch.setattr("sase.pager.screen.suspend_for_external_tool", fake_suspend)
    monkeypatch.setattr(
        "sase.pager.screen.subprocess.run",
        lambda argv, **_kwargs: run_calls.append(argv),
    )
    monkeypatch.setenv("EDITOR", "nvim")
    _, alpha_line, _ = _anchor_body()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=_anchor_document(),
            edit_path=Path("/tmp/anchors.md"),
            edit_line=5,
        ),
    )
    app = SasePager(_anchor_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert handoffs and handoffs[0]["action"] == "pager_open_editor"
    assert run_calls == [
        ["nvim", "-c", f"call cursor({alpha_line}, 1)", "/tmp/anchors.md"]
    ]


async def test_y_anchor_copies_authored_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(_anchor_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert copied == ["#alpha"]
