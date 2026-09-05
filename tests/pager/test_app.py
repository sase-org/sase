"""Headless Pilot key-binding tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.graphics import ArtifactFileViewSpec, ArtifactFileViewerResult
from sase.pager._help import PagerHelpScreen
from sase.pager.app import PagerExit, SasePager
from sase.pager.document import AttachedTarget, PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.screen import PagerScreen


def _lines(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {index}" for index in range(count)) + "\n"


def _long_document(title: str = "one file") -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/long.py",
        title="long.py",
        kind="file",
        body=_lines("line", 80),
    )
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def _multi_section_document() -> PagerDocument:
    sections = tuple(
        PagerSection(
            identity=f"file:/tmp/{name}.py",
            title=f"{name}.py",
            kind="file",
            body=_lines(name, 30),
        )
        for name in ("alpha", "beta", "gamma")
    )
    return PagerDocument(sections=sections, title="3 files", origin=PagerOrigin.FILE)


def _link_document(count: int) -> PagerDocument:
    body = "\n".join(f"https://example.test/{index}" for index in range(count)) + "\n"
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(sections=(section,), title="links", origin=PagerOrigin.FILE)


def _path_link_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=f"see {path} for details\n",
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def _target_document(title: str = "target") -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/target.py", title="target.py", kind="file", body="target\n"
    )
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def _long_link_source_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=f"{_lines('source', 80)}see {path} for details\n",
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def _searchable_link_source_document(path: Path) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/source.py",
        title="source.py",
        kind="file",
        body=(
            f"top\n{_lines('spacer', 40)}needle target line\nsee {path} for details\n"
        ),
        subject_ref="file:/tmp/source.py",
    )
    return PagerDocument(
        sections=(section,), title="source.py", origin=PagerOrigin.FILE
    )


def _attached_target_document(*, kind: str = "commit") -> PagerDocument:
    section = PagerSection(
        identity="pager-commits",
        title="Selected commits",
        kind="commit",
        body="abc1234  a commit subject\n",
        targets=(AttachedTarget(kind=kind, target="commit-object", start=0, end=7),),
    )
    return PagerDocument(sections=(section,), title="1 file", origin=PagerOrigin.FILE)


def _pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def _body_scroll(app: SasePager) -> VerticalScroll:
    return _pager_screen(app).query_one("#pager-body-scroll", VerticalScroll)


async def test_q_closes_the_pager_with_a_pager_exit() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("q")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_backspace_on_empty_trail_exits_with_exhausted_marker() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("backspace")
        await pilot.pause()

    assert app.return_value == PagerExit(trail_exhausted=True)


async def test_escape_also_closes_the_pager() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("escape")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_j_and_k_scroll_one_line_at_a_time() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 1

        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 2

        await pilot.press("k")
        await pilot.pause()
        assert scroll.scroll_y == 1


async def test_ctrl_d_and_ctrl_u_scroll_half_a_page() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        half_page = scroll.size.height // 2

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y == half_page

        await pilot.press("ctrl+u")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_g_and_shift_g_jump_to_top_and_bottom() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        assert scroll.max_scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_ctrl_n_and_ctrl_p_scroll_to_the_next_and_previous_section() -> None:
    app = SasePager(_multi_section_document())
    async with app.run_test(size=(80, 10)) as pilot:
        screen = _pager_screen(app)
        scroll = _body_scroll(app)
        assert screen._body is not None
        offsets = screen._body.section_offsets

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == offsets[1]

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == offsets[2]

        # the last section: ctrl+n goes to the end rather than doing nothing.
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert scroll.scroll_y == offsets[1]

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert scroll.scroll_y == offsets[0]


async def test_ctrl_n_is_inert_for_a_single_section_document() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_question_mark_opens_and_closes_the_help_screen() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, PagerHelpScreen)

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, PagerHelpScreen)
        assert app.return_value is None


async def test_slash_search_highlights_and_scrolls_to_a_match() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        await pilot.press("slash")
        await pilot.pause()
        for character in "line 60":
            await pilot.press(character)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert scroll.scroll_y > 0
        command = _pager_screen(app).query_one("#pager-search-command", Static)
        assert "hidden" not in command.classes

        await pilot.press("escape")
        await pilot.pause()
        assert "hidden" in command.classes


async def test_footer_shows_entity_nav_only_for_multi_section_documents() -> None:
    single = SasePager(_long_document())
    async with single.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = _pager_screen(pilot.app).query_one("#pager-footer", Static)
        assert "^N/^P" not in footer.visual.plain  # type: ignore[attr-defined]

    multi = SasePager(_multi_section_document())
    async with multi.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = _pager_screen(pilot.app).query_one("#pager-footer", Static)
        assert "^N/^P" in footer.visual.plain  # type: ignore[attr-defined]


async def test_painted_link_key_records_the_selected_label() -> None:
    app = SasePager(_link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert screen._last_activated_label is not None
    assert screen._last_activated_label.hint == "1"
    assert screen._last_activated_label.target.text == "https://example.test/1"


async def test_uppercase_painted_link_key_uses_event_character() -> None:
    app = SasePager(_link_document(30))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()

    assert screen._last_activated_label is not None
    assert screen._last_activated_label.hint == "A"


async def test_pending_prefix_is_shown_in_the_footer_and_invalid_clears_it() -> None:
    app = SasePager(_link_document(53))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("Z")
        await pilot.pause()

        footer = screen.query_one("#pager-footer", Static)
        assert "Z… link" in footer.visual.plain  # type: ignore[attr-defined]
        assert screen._label_pending_prefix == "Z"

        await pilot.press("x")
        await pilot.pause()

        footer = screen.query_one("#pager-footer", Static)
        assert "Z… link" not in footer.visual.plain  # type: ignore[attr-defined]
        assert screen._label_pending_prefix == ""


async def test_footer_offers_copy_and_edit_once_links_are_painted() -> None:
    app = SasePager(_link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = _pager_screen(app).query_one("#pager-footer", Static)
        assert "y copy" in footer.visual.plain  # type: ignore[attr-defined]
        assert "E edit" in footer.visual.plain  # type: ignore[attr-defined]


async def test_pressing_a_label_follows_it_into_a_new_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_document = _target_document()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref: LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target_document),
    )
    app = SasePager(_path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert screen.document is target_document


async def test_follow_back_and_forward_restore_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_document = _target_document()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref: LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target_document),
    )
    source = _long_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        scroll = _body_scroll(app)
        trail = screen.query_one("#pager-trail", Static)
        footer = screen.query_one("#pager-footer", Static)
        scroll.scroll_to(y=12, animate=False, immediate=True)
        screen._update_subject()
        await pilot.pause()

        assert "hidden" in trail.classes

        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen.document is target_document
        assert screen._back_trail
        assert "hidden" not in trail.classes
        assert "⌫/^O back" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document is source
        assert int(scroll.scroll_y) == 12
        assert not screen._back_trail
        assert screen._forward_trail
        assert "hidden" in trail.classes
        assert "^I forward" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert screen.document is target_document
        assert screen._back_trail
        assert not screen._forward_trail


async def test_back_restores_committed_search_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_document = _target_document()
    source = _searchable_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        scroll = _body_scroll(app)
        await pilot.press("slash")
        for character in "needle":
            await pilot.press(character)
        await pilot.press("enter")
        await pilot.pause()

        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        source_scroll_y = int(scroll.scroll_y)
        assert source_scroll_y > 0

        screen._apply_resolution(
            "/tmp/target.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target_document),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is target_document
        assert screen._search.mode == "off"

        await pilot.press("ctrl+o")
        await pilot.pause()

        command = screen.query_one("#pager-search-command", Static)
        assert screen.document is source
        assert int(scroll.scroll_y) == source_scroll_y
        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        assert "hidden" not in command.classes


async def test_unresolvable_label_toasts_marks_it_dangling_and_does_not_renavigate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_resolve(ref: str) -> None:
        calls.append(ref)
        return None

    monkeypatch.setattr("sase.pager.screen.resolve_ref", fake_resolve)
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert calls == ["/tmp/target.py"]
        assert screen.document.title == "source.py"
        assert not screen._back_trail
        assert ("/tmp/target.py could not be resolved.", "warning") in notifications
        assert screen._label_layer is not None
        assert screen._label_layer.labels[0].dangling is True

        # Pressing the now-dangling label again does not re-resolve.
        await pilot.press("0")
        await pilot.pause(0.1)

    assert calls == ["/tmp/target.py"]


async def test_pressing_a_url_label_copies_without_a_y_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(_link_document(2))
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
    app = SasePager(_path_link_document(target))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
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


async def test_yy_copies_the_current_sections_subject_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: copied.append(value) or True,
    )
    app = SasePager(_path_link_document(Path("/tmp/target.py")))
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
        lambda ref: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=_target_document(),
            edit_path=Path("/tmp/target.py"),
            edit_line=5,
        ),
    )
    app = SasePager(_path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
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
        lambda ref: LinkTarget(
            kind=LinkTargetKind.MEDIA,
            media_specs=(ArtifactFileViewSpec(Path("/tmp/target.png"), kind="image"),),
        ),
    )
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
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
        lambda ref: resolve_calls.append(ref) or None,
    )
    calls: list[tuple[str, str]] = []
    app = SasePager(
        _attached_target_document(),
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
        _attached_target_document(),
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
        lambda ref: resolve_calls.append(ref) or None,
    )
    app = SasePager(_attached_target_document(kind="other"))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

    assert resolve_calls == ["abc1234"]
