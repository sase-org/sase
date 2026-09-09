"""Tests for view-file pager screen wiring and link resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.tui.actions.hints._files import (
    _COMMIT_TARGET_KIND,
    _resolve_ref_from_link_index,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager import PagerExit, PagerScreen
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import (
    LinkResolution,
    LinkTarget,
    LinkTargetKind,
    link_target_for_artifact_entry_target,
)

from ._view_files_helpers import _make_app
from ._view_files_pager_helpers import (
    _PagerHost,
    _ViewHost,
    _attached_label_document,
    _multi_section_document,
)


def test_view_files_with_pager_screen_pushes_screen_without_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/a.py", title="a.py", kind="file", body="hi\n"
            ),
        ),
        title="1 file",
        origin=PagerOrigin.FILE,
    )
    captured: dict[str, object] = {}

    class _FakePagerScreen:
        def __init__(
            self,
            doc: PagerDocument,
            *,
            attached_handlers=None,
            resolve_ref_fn=None,
            syntax_enabled: bool = True,
        ) -> None:
            captured["document"] = doc
            captured["handlers"] = attached_handlers
            captured["resolve_ref_fn"] = resolve_ref_fn
            captured["syntax_enabled"] = syntax_enabled
            captured["screen"] = self

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.PagerScreen", _FakePagerScreen
    )
    app = _make_app()

    app._view_files_with_pager_screen(document)

    app.push_screen.assert_called_once_with(captured["screen"])
    assert not app.suspend_recorder.entered
    assert captured["document"] is document
    assert _COMMIT_TARGET_KIND in captured["handlers"]  # type: ignore[operator]
    assert callable(captured["resolve_ref_fn"])


def test_view_files_with_pager_screen_toasts_when_push_fails() -> None:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/a.py", title="a.py", kind="file", body="hi\n"
            ),
        ),
        title="1 file",
        origin=PagerOrigin.FILE,
    )
    app = _make_app()
    app.push_screen.side_effect = RuntimeError("boom")

    app._view_files_with_pager_screen(document)

    app.notify.assert_called_once_with("Could not open pager: boom", severity="error")


async def test_pager_screen_runs_inside_an_existing_textual_app() -> None:
    app = _PagerHost()
    async with app.run_test(size=(80, 10)) as pilot:
        screen = PagerScreen(_multi_section_document())
        app.push_screen(screen, callback=app.dismissed.append)
        await pilot.pause()

        assert app.is_running
        assert app.screen is screen
        scroll = screen.query_one("#pager-body-scroll", VerticalScroll)

        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 1

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y > 1

        await pilot.press("q")
        await pilot.pause()

        assert app.is_running
        assert app.screen is not screen
        assert app.dismissed == [PagerExit()]


async def test_view_request_pushes_real_pager_screen_inside_running_host(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _ViewHost({1: str(notes)})

    async with app.run_test(size=(80, 10)) as pilot:
        await app._process_view_input("1")
        await pilot.pause()

        assert isinstance(app.screen, PagerScreen)
        assert app.screen.document.sections[0].identity == f"file:{notes}"


async def test_pager_screen_modal_label_key_does_not_reach_host_binding() -> None:
    app = _PagerHost()
    handled: list[tuple[object, str]] = []
    async with app.run_test(size=(80, 12)) as pilot:
        screen = PagerScreen(
            _attached_label_document(11),
            attached_handlers={
                _COMMIT_TARGET_KIND: lambda target, action: handled.append(
                    (target.target, action)
                )
            },
        )
        app.push_screen(screen)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()

        assert screen._last_activated_label is not None
        assert screen._last_activated_label.hint == "a"
        assert handled == [("target-10", "follow")]
        assert app.host_a_count == 0


def test_link_index_backed_pager_resolver_prefers_indexed_file_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "indexed.md"
    path.write_text("indexed\n", encoding="utf-8")
    ref = f"file:{path}"

    class _Index:
        targets_by_ref = {ref: ArtifactEntryTarget("files", (str(path),))}

        def target_for(self, value: str) -> ArtifactEntryTarget | None:
            return self.targets_by_ref[value]

    class _App:
        _link_index = _Index()

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.resolve_link",
        lambda value, **_kwargs: (_ for _ in ()).throw(AssertionError(value)),
    )

    resolution = _resolve_ref_from_link_index(_App(), ref, context=None)
    target = resolution.target

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert target.document.sections[0].plain_text == "indexed\n"


def test_link_index_backed_pager_resolver_forwards_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "indexed.md"
    path.write_text("indexed\n", encoding="utf-8")
    ref = f"file:{path}"
    context = LinkResolutionContext(anchors=(LinkAnchor(tmp_path),))
    seen: list[LinkResolutionContext | None] = []

    class _Index:
        targets_by_ref = {ref: ArtifactEntryTarget("files", (str(path),))}

        def target_for(self, value: str) -> ArtifactEntryTarget | None:
            return self.targets_by_ref[value]

    class _App:
        _link_index = _Index()

    real = link_target_for_artifact_entry_target

    def spy(
        value: str,
        target: ArtifactEntryTarget,
        *,
        context: LinkResolutionContext | None = None,
    ) -> object:
        seen.append(context)
        return real(value, target, context=context)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.link_target_for_artifact_entry_target",
        spy,
    )

    resolution = _resolve_ref_from_link_index(_App(), ref, context=context)

    assert resolution.target is not None
    assert seen == [context]


def test_link_index_backed_pager_resolver_falls_back_for_unknown_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fallback = LinkTarget(kind=LinkTargetKind.DOCUMENT)
    context = LinkResolutionContext(anchors=(LinkAnchor(tmp_path),))
    calls: list[tuple[str, LinkResolutionContext | None]] = []

    class _Index:
        targets_by_ref: dict[str, ArtifactEntryTarget | None] = {}

        def target_for(self, value: str) -> ArtifactEntryTarget | None:
            raise AssertionError(value)

    class _App:
        _link_index = _Index()

    def fake_resolve(
        value: str,
        *,
        context: LinkResolutionContext | None = None,
    ) -> LinkResolution:
        calls.append((value, context))
        return LinkResolution(target=fallback if value == "bead:unknown" else None)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.resolve_link",
        fake_resolve,
    )

    assert (
        _resolve_ref_from_link_index(_App(), "bead:unknown", context=context).target
        is fallback
    )
    assert calls == [("bead:unknown", context)]
