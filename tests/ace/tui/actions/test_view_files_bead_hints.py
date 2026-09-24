"""Tests for bead-hint routing through the view-file hint flow."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.pager.document import PagerDocument, PagerSection
from sase.pager.link_scan import PagerOrigin
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind

from ._view_files_helpers import _drain_pump_free_clipboard_tasks, _make_app


def _bead_section(
    *,
    identity: str = "bead:sase-1",
    title: str = "sase-1 · Test bead",
) -> PagerSection:
    return PagerSection(
        identity=identity,
        title=title,
        kind="bead",
        body="bead body",
        origin=PagerOrigin.BEAD,
    )


def _bead_resolution(section: PagerSection) -> LinkResolution:
    return LinkResolution(
        target=LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=PagerDocument(
                sections=(section,),
                title=section.title,
                origin=PagerOrigin.BEAD,
            ),
        )
    )


async def test_bead_hint_opens_pager_with_bead_section() -> None:
    section = _bead_section()
    app = _make_app("bead:sase-1")
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    import sase.ace.tui.actions.hints._view_processing as processing

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        assert ref == "bead:sase-1"
        return _bead_resolution(section)

    original = processing.resolve_link
    processing.resolve_link = fake_resolve  # type: ignore[method-assign]
    try:
        await app._process_view_input("1")
    finally:
        processing.resolve_link = original  # type: ignore[method-assign]

    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert [s.identity for s in document.sections] == ["bead:sase-1"]
    assert document.title == section.title
    for call in app.notify.call_args_list:
        assert "File no longer exists" not in call.args[0]


async def test_mixed_bead_and_file_selection_orders_bead_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    section = _bead_section()
    app = _make_app("bead:sase-1", str(notes))
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        return _bead_resolution(section)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.resolve_link",
        fake_resolve,
    )

    await app._process_view_input("1 2")

    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert [s.identity for s in document.sections] == [
        "bead:sase-1",
        f"file:{notes}",
    ]


async def test_unresolved_bead_warns_without_opening_pager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app("bead:sase-1")
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        return LinkResolution(unresolved_message="bead:sase-1 could not be resolved")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.resolve_link",
        fake_resolve,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call(
        "bead:sase-1 could not be resolved",
        severity="warning",
    )


async def test_bead_resolution_runs_off_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    section = _bead_section()
    app = _make_app("bead:sase-1")
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    resolve_threads: list[int] = []

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        resolve_threads.append(threading.get_ident())
        return _bead_resolution(section)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.resolve_link",
        fake_resolve,
    )

    await app._process_view_input("1")

    assert resolve_threads
    assert all(t != event_loop_thread for t in resolve_threads)


async def test_bead_copy_suffix_copies_bare_id_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    copied_event = asyncio.Event()

    def copy(content: str) -> bool:
        copied.append(content)
        copied_event.set()
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        copy,
    )
    app = _make_app("bead:sase-1")

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        raise AssertionError("copy must not resolve beads")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.resolve_link",
        fake_resolve,
    )

    await app._process_view_input("1%")
    await asyncio.wait_for(copied_event.wait(), timeout=1.0)
    await _drain_pump_free_clipboard_tasks(app)

    assert copied == ["sase-1"]


async def test_bead_editor_suffix_warns_without_opening_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app("bead:sase-1")
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    def fake_resolve(ref: str, *, context=None) -> LinkResolution:
        raise AssertionError("editor must not resolve beads")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.resolve_link",
        fake_resolve,
    )

    await app._process_view_input("1@")

    app.notify.assert_any_call(
        "Beads cannot be opened in an editor: sase-1",
        severity="warning",
    )
    app._open_files_in_editor.assert_not_called()
