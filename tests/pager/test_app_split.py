"""Headless Pilot split-pane tests for ``SasePager``."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import SectionTimeState
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.split import PagerSplitLayout

from ._app_helpers import link_document, long_document, pager_screen, pager_view


def _footer_text(app: SasePager) -> str:
    footer = pager_screen(app).query_one("#pager-footer", Static)
    visual = getattr(footer, "visual", None)
    if visual is not None:
        return str(visual.plain)
    content = getattr(footer, "_content", "")
    return str(getattr(content, "plain", content))


async def test_open_below_splits_and_focuses_new_pane() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        assert len(screen.views) == 1
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen._focused_index == 1
        assert screen.focused_view.document is screen.views[0].document


async def test_open_beside_and_same_key_keeps_focused_pane() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert screen._split_state.layout is PagerSplitLayout.BESIDE
        focused = screen.focused_view
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen.views[0] is focused


async def test_rotate_keeps_documents_focus_and_ratio() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        first, second = screen.views
        await pilot.press("+")
        await pilot.pause()
        ratio = screen._split_state.ratio
        assert ratio != 50
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert screen._split_state.layout is PagerSplitLayout.BESIDE
        assert screen.views[0] is first
        assert screen.views[1] is second
        assert screen._split_state.ratio == ratio
        assert screen._focused_index == 1


async def test_ctrl_f_moves_focus_and_scopes_labels() -> None:
    app = SasePager(link_document(2))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert screen.focused_view._visible_label_count() > 0
        other = screen.views[0]
        assert other._visible_label_count() == 0
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen._focused_index == 0
        assert screen.focused_view._visible_label_count() > 0
        assert screen.views[1]._visible_label_count() == 0


async def test_q_closes_focused_pane_then_pager() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen._split_state.layout is PagerSplitLayout.SINGLE
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running


async def test_exhausted_backspace_closes_focused_pane() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1


async def test_clone_shares_document_and_trail() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        view = pager_view(app)
        for _ in range(5):
            await pilot.press("j")
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen.views[1].document is view.document
        assert screen.views[1]._back_trail == view._back_trail


async def test_follow_in_one_pane_leaves_other_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from ._app_helpers import path_link_document, target_document

    target = target_document()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT, document=target
        ),
    )
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        other = screen.views[1]
        other_document = other.document
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.2)
        await pilot.pause(0.2)
        assert screen.views[0].document is target
        assert other.document is other_document


async def test_plus_minus_steps_and_clamps() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        # The new pane takes focus, so growing it shrinks pane 0's share.
        assert screen._split_state.ratio == 50
        await pilot.press("+")
        await pilot.pause()
        assert screen._split_state.ratio == 30
        await pilot.press("+")
        await pilot.pause()
        assert screen._split_state.ratio == 30
        await pilot.press("-")
        await pilot.pause()
        assert screen._split_state.ratio == 50


async def test_too_small_split_refuses() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(40, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen._split_state.layout is PagerSplitLayout.SINGLE


async def test_footer_verbs_in_single_and_split() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "q close" in _footer_text(app)
        assert "^F pane" not in _footer_text(app)
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        text = _footer_text(app)
        assert "^F pane" in text
        assert "q close pane" in text


async def test_click_focuses_pane() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert screen._focused_index == 1
        screen.views[0].on_click(object())
        await pilot.pause()
        assert screen._focused_index == 0


async def test_split_seed_copies_history_and_syntax_state() -> None:
    section = PagerSection(
        identity="file:/tmp/seed.py",
        title="seed.py",
        kind="file",
        body="hello\n",
    )
    document = PagerDocument(
        sections=(section,), title="seed.py", origin=PagerOrigin.FILE
    )
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view = pager_view(app)
        view._syntax_prepared[("file:/tmp/seed.py", None)] = object()  # type: ignore[assignment]
        view._syntax_attempted.add(("file:/tmp/seed.py", None))
        view._dangling_refs[(object(), (), object())] = "x"
        state = SectionTimeState(
            provider_key="fake",
            subject_id="file:/tmp/seed.py",
            scope_key="",
            live_section=section,
        )
        state.body_cache[(1, "read")] = section
        state.comparison_cache[(1, 0)] = object()
        state.expanded_folds.add(3)
        view._history_states["file:/tmp/seed.py"] = state
        view._history_supported["file:/tmp/seed.py"] = True
        seed = view.split_seed()
        assert seed.document is view.document
        ((identity, clone),) = seed.history_states
        assert identity == "file:/tmp/seed.py"
        assert isinstance(clone, SectionTimeState)
        assert clone is not state
        assert clone.body_cache == state.body_cache
        assert clone.body_cache is not state.body_cache
        assert clone.comparison_cache == state.comparison_cache
        assert clone.comparison_cache is not state.comparison_cache
        assert clone.expanded_folds == {3}
        assert clone.expanded_folds is not state.expanded_folds
        assert dict(seed.history_supported) == {"file:/tmp/seed.py": True}
        assert dict(seed.syntax_prepared) == dict(view._syntax_prepared)
        assert set(seed.syntax_attempted) == set(view._syntax_attempted)
        assert dict(seed.dangling_refs) == dict(view._dangling_refs)


async def test_closing_pane_with_in_flight_resolve_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    from pathlib import Path

    from ._app_helpers import path_link_document, target_document

    target = target_document()

    def slow_resolve(ref: str, *, context: object | None = None) -> LinkTarget:
        time.sleep(0.3)  # sase-test-wait: slow resolve
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    monkeypatch.setattr("sase.pager.screen.resolve_ref", slow_resolve)
    app = SasePager(path_link_document(Path("/tmp/slow.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause(0.05)
        # Close the focused pane mid-resolve; the worker must no-op.
        await pilot.press("q")
        await pilot.pause(0.5)
        await pilot.pause(0.5)
        assert len(screen.views) == 1
