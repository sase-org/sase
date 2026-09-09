"""Headless Pilot action tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace.tui.graphics import ArtifactFileViewSpec, ArtifactFileViewerResult
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._app_helpers import (
    attached_target_document,
    link_document,
    pager_screen,
    path_link_document,
    target_document,
)


async def test_pressing_a_url_label_copies_without_a_y_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert copied == ["https://example.test/1"]


async def test_y_then_label_copies_the_links_resolved_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    target = Path("/tmp/target.py")
    app = SasePager(path_link_document(target))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        footer = screen.query_one("#pager-footer", Static)
        assert "y… copy" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert copied == [str(target.resolve())]
    assert screen._pending_action == "follow"


async def test_y_then_label_copies_using_merged_link_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    workspace = tmp_path / "workspace"
    live = workspace / "src" / "target.py"
    live.parent.mkdir(parents=True)
    live.write_text("target\n", encoding="utf-8")
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="see src/target.py\n",
        link_anchors=(LinkAnchor(workspace),),
    )
    app = SasePager(
        PagerDocument(sections=(section,), title="source.py", origin=PagerOrigin.FILE)
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert copied == [str(live.resolve())]


async def test_yy_copies_the_current_sections_subject_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("y")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert copied == ["file:/tmp/source.py"]


async def test_e_then_label_opens_the_editor_at_its_line(
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
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=target_document(),
            edit_path=Path("/tmp/target.py"),
            edit_line=5,
        ),
    )
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("E")
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert handoffs and handoffs[0]["action"] == "pager_open_editor"
    assert run_calls == [["nvim", "-c", "call cursor(5, 1)", "/tmp/target.py"]]
    # Following a label to edit it does not navigate the pager itself.
    assert screen.document.title == "source.py"


async def test_media_target_suspends_the_pager_and_shows_a_viewer_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs: list[dict[str, object]] = []

    @contextmanager
    def fake_suspend(_app: object, **metadata: object):  # type: ignore[no-untyped-def]
        handoffs.append(metadata)
        yield

    monkeypatch.setattr("sase.pager.screen.suspend_for_external_tool", fake_suspend)
    monkeypatch.setattr(
        "sase.pager.screen.view_artifact_files",
        lambda specs: ArtifactFileViewerResult(ok=False, warning="no viewer available"),
    )
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(Path("/tmp/target.png"), kind="image"),),
        ),
    )
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert handoffs and handoffs[0]["action"] == "pager_view_media"
    assert ("no viewer available", "warning") in notifications
    assert screen.document.title == "source.py"


async def test_attached_handler_receives_a_caller_kind_target_on_follow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls: list[str] = []
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: resolve_calls.append(ref) or None,
    )
    calls: list[tuple[str, str]] = []
    app = SasePager(
        attached_target_document(),
        attached_handlers={
            "commit": lambda target, action: calls.append((str(target.target), action))
        },
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()

    assert calls == [("commit-object", "follow")]
    # A registered handler owns resolution entirely — `resolve_ref` (which
    # only understands ref strings) must never see a non-ref attached kind.
    assert resolve_calls == []


async def test_attached_handler_receives_the_pending_copy_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    app = SasePager(
        attached_target_document(),
        attached_handlers={
            "commit": lambda target, action: calls.append((str(target.target), action))
        },
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("0")
        await pilot.pause()

    assert calls == [("commit-object", "copy")]


async def test_unregistered_attached_kind_falls_back_to_resolve_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls: list[str] = []
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: resolve_calls.append(ref) or None,
    )
    app = SasePager(attached_target_document(kind="other"))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert resolve_calls == ["abc1234"]
