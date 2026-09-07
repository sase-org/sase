"""Pager tests for in-memory merge and workspace-number dangling identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.screen import PagerScreen


def _target_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/target.py", title="target.py", kind="file", body="target\n"
    )
    return PagerDocument(sections=(section,), title="target", origin=PagerOrigin.FILE)


def _pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


async def test_label_activation_merge_does_not_touch_the_filesystem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    alias = workspace / ".." / workspace.name
    target_document = _target_document()

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("label activation must not touch the filesystem")

    monkeypatch.setattr("sase.pager.link_context._existing_dir", boom)
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda _ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=target_document,
        ),
    )
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body="see src/target.py\n",
        link_anchors=(LinkAnchor(directory=alias, workspace_num=4),),
    )
    app = SasePager(
        PagerDocument(
            sections=(section,),
            title="source.py",
            origin=PagerOrigin.FILE,
            link_context=LinkResolutionContext(
                anchors=(LinkAnchor(directory=workspace, workspace_num=4),)
            ),
        )
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert screen.document is target_document


async def test_dangling_typed_refs_are_scoped_to_workspace_num(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
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
            body="see plan:202608/doc.md\n",
            link_anchors=(LinkAnchor(directory=shared, workspace_num=11),),
        ),
        PagerSection(
            identity="file:/tmp/second.py",
            title="second.py",
            kind="file",
            body="see plan:202608/doc.md\n",
            link_anchors=(LinkAnchor(directory=shared, workspace_num=12),),
        ),
    )
    app = SasePager(
        PagerDocument(sections=sections, title="2 files", origin=PagerOrigin.FILE)
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
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

        assert [label.dangling for label in screen._label_layer.labels] == [
            True,
            True,
        ]

    assert len(calls) == 2
    assert calls[0] is not None
    assert calls[1] is not None
    assert [anchor.workspace_num for anchor in calls[0].anchors] == [11]
    assert [anchor.workspace_num for anchor in calls[1].anchors] == [12]
    assert calls[0].base_dirs == calls[1].base_dirs == (shared,)
