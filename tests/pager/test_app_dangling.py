"""Headless Pilot dangling-ref tests for the standalone ``SasePager`` app."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import LinkResolution, LinkTarget, LinkTargetKind, resolve_link

from ._app_helpers import pager_screen, target_document


async def test_unresolvable_label_toasts_marks_it_dangling_and_does_not_renavigate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    loop_thread = threading.current_thread()
    git_calls: list[Path] = []
    resolve_threads: list[int | None] = []

    def fake_git(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return ()

    def spy_resolve(
        ref: str, *, context: LinkResolutionContext | None = None
    ) -> LinkResolution:
        resolve_threads.append(threading.current_thread().ident)
        assert threading.current_thread() is not loop_thread
        return resolve_link(ref, context=context)

    monkeypatch.setattr("sase.pager._resolve_path_search._git_ls_files", fake_git)
    monkeypatch.setattr("sase.pager.screen.resolve_ref", spy_resolve)
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="see src/missing.py for details\n",
        link_anchors=(LinkAnchor(workspace),),
    )
    app = SasePager(
        PagerDocument(sections=(section,), title="source.py", origin=PagerOrigin.FILE)
    )
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert git_calls == [workspace.resolve()]
        assert screen.document.title == "source.py"
        assert not screen._back_trail
        assert (
            "src/missing.py not found (searched 1 locations)",
            "warning",
        ) in notifications
        assert screen._label_layer is not None
        assert screen._label_layer.labels[0].dangling is True

        await pilot.press("0")
        await pilot.pause(0.1)

    assert git_calls == [workspace.resolve()]
    assert len(resolve_threads) == 1
    assert (
        notifications.count(
            ("src/missing.py not found (searched 1 locations)", "warning")
        )
        == 2
    )


async def test_refresh_clears_dangling_so_retry_can_succeed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls: list[str] = []

    def fake_resolve(
        ref: str, *, context: LinkResolutionContext | None = None
    ) -> LinkResolution:
        del context
        calls.append(ref)
        if len(calls) == 1:
            return LinkResolution(
                unresolved_message=f"{ref} checkout is unavailable",
                retryable=True,
            )
        return LinkResolution(
            target=LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target_document())
        )

    monkeypatch.setattr("sase.pager.screen.resolve_ref", fake_resolve)
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="see src/missing.py for details\n",
        link_anchors=(LinkAnchor(workspace),),
    )
    app = SasePager(
        PagerDocument(sections=(section,), title="source.py", origin=PagerOrigin.FILE)
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen.document.title == "source.py"
        assert screen._dangling_refs == {}

        await pilot.press("r")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen.document.title == "target"
        assert len(calls) == 2


async def test_dangling_refs_are_scoped_to_link_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    calls: list[LinkResolutionContext | None] = []

    def fake_resolve(
        _ref: str,
        *,
        context: LinkResolutionContext | None = None,
    ) -> None:
        calls.append(context)
        return None

    monkeypatch.setattr("sase.pager.screen.resolve_ref", fake_resolve)
    sections = (
        PagerSection(
            identity="file:/tmp/first.py",
            title="first.py",
            kind="file",
            body="see src/shared.py\n",
            link_anchors=(LinkAnchor(first),),
        ),
        PagerSection(
            identity="file:/tmp/second.py",
            title="second.py",
            kind="file",
            body="see src/shared.py\n",
            link_anchors=(LinkAnchor(second),),
        ),
    )
    app = SasePager(
        PagerDocument(sections=sections, title="2 files", origin=PagerOrigin.FILE)
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen._label_layer is not None
        assert [label.dangling for label in screen._label_layer.labels] == [
            True,
            False,
        ]

        await pilot.press("1")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert len(calls) == 2
    assert calls[0] is not None
    assert calls[1] is not None
    assert calls[0].base_dirs == (first,)
    assert calls[1].base_dirs == (second,)
