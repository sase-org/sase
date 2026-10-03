"""Changes-lens review state: watermark chip, dots, and mark-reviewed."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.modals.memory_pane_changes_header import (
    _changes_lens_footer,
    _changes_lens_header_detail,
)
from tests.ace.tui.modals._memory_pane_changes_lens_helpers import (
    make_authored,
    make_changeset,
    prepare_changes_panel,
    rail_texts,
)

_REVIEW_T0 = 1790486400


def _review_wire(
    *,
    sase_new: int = 2,
    sase_watermark: bool = True,
    home_new: int = 0,
) -> dict[str, Any]:
    sase_entry: dict[str, Any] = {
        "scope_key": "project:sase",
        "watermark": (
            {"commit": "w" * 40, "committer_time": _REVIEW_T0, "marked_at": _REVIEW_T0}
            if sase_watermark
            else None
        ),
        "new_count": sase_new,
        "newest_commit": "a" * 40,
    }
    home_entry: dict[str, Any] = {
        "scope_key": "home",
        "watermark": {
            "commit": "h" * 40,
            "committer_time": _REVIEW_T0,
            "marked_at": _REVIEW_T0,
        },
        "new_count": home_new,
        "newest_commit": "",
    }
    return {"scopes": [sase_entry, home_entry]}


def _review_feed() -> dict[str, Any]:
    def _named(name: str) -> list[dict[str, Any]]:
        return [
            make_authored(
                subject_id=f"note:project:sase/{name}",
                path=f"sase/memory/{name}.md",
            )
        ]

    return {
        "changesets": [
            make_changeset(
                commit="a" * 40,
                committer_time=_REVIEW_T0 + 300,
                subject="feat: newest",
                authored=_named("alpha"),
            ),
            make_changeset(
                commit="b" * 40,
                committer_time=_REVIEW_T0 + 100,
                subject="feat: newer",
                authored=_named("beta"),
            ),
            make_changeset(
                commit="c" * 40,
                committer_time=_REVIEW_T0 - 100,
                subject="feat: older",
                authored=_named("gamma"),
            ),
        ]
    }


def test_lens_header_detail_leads_with_review_chip() -> None:
    """The watermark chip opens the header detail when known."""
    detail = _changes_lens_header_detail(
        total=3, shown=3, scope_label="project:sase", review="● 2 new"
    )
    assert detail.startswith("● 2 new · ")
    plain = _changes_lens_header_detail(total=3, shown=3)
    assert not plain.startswith("●")


def test_lens_footer_names_mark_reviewed() -> None:
    """The Changes footer advertises the mark key."""
    from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps

    assert "m reviewed" in _changes_lens_footer(MemoryPanelKeymaps())


async def _open_review_lens(monkeypatch, **kwargs):  # noqa: ANN001, ANN202
    """Open the lens on the review feed; return ``(panel, app, pilot)``."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(
        monkeypatch, feed=_review_feed(), review=_review_wire(), **kwargs
    )
    pilot_context = app.run_test(size=(120, 40))
    pilot = await pilot_context.__aenter__()
    try:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await wait_for(pilot, lambda: tuple(panel._changes_review) != ())
        await pilot.pause()
        return panel, app, pilot, pilot_context
    except Exception:
        await pilot_context.__aexit__(None, None, None)
        raise


async def test_changes_lens_shows_review_chip_and_dots(monkeypatch) -> None:
    """The header names N-new and only newer rows carry the dot."""
    from textual.widgets import Static

    panel, _app, pilot, pilot_context = await _open_review_lens(monkeypatch)
    try:
        header = panel.query_one("#memory-panel-header", Static).content.plain
        assert "● 2 new" in header
        texts = rail_texts(panel)
        dotted = [text for text in texts if "● " in text]
        assert len(dotted) == 2
        assert any("alpha" in text for text in dotted)
        assert any("beta" in text for text in dotted)
        assert not any("gamma" in text for text in dotted)
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_opening_changes_lens_marks_nothing(monkeypatch) -> None:
    """Opening the lens reads the watermark but never advances it."""
    panel, _app, _pilot, pilot_context = await _open_review_lens(monkeypatch)
    try:
        history = panel._ace_history()
        assert history.review_calls != []
        assert history.marked == []
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_mark_reviewed_clears_dots_and_toasts(monkeypatch) -> None:
    """``m`` clears dots optimistically, persists, and toasts the count."""
    from sase.ace.testing import wait_for

    panel, _app, pilot, pilot_context = await _open_review_lens(monkeypatch)
    try:
        toasts: list[tuple[str, Any]] = []
        monkeypatch.setattr(
            panel,
            "notify",
            lambda message, *args, **kwargs: toasts.append(
                (str(message), kwargs.get("severity"))
            ),
        )
        await pilot.press("m")
        # Optimistic: dots clear synchronously inside the key action.
        assert not any("● " in text for text in rail_texts(panel))
        history = panel._ace_history()
        await wait_for(pilot, lambda: history.marked != [])
        # Marked through the scope's newest changeset (the CLI `-m` rule).
        assert history.marked == [("project:sase", "a" * 40)]
        await wait_for(
            pilot,
            lambda: any(
                "marked 2 changesets reviewed · project:sase" in text
                for text, _severity in toasts
            ),
        )
        await pilot.pause()
        assert not any("● " in text for text in rail_texts(panel))
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_mark_reviewed_failure_restores_dots(monkeypatch) -> None:
    """A failed persist restores the dots and toasts the failure."""
    from textual.widgets import Static

    from sase.ace.testing import wait_for

    panel, _app, pilot, pilot_context = await _open_review_lens(
        monkeypatch, mark_error=RuntimeError("store gone")
    )
    try:
        toasts: list[tuple[str, Any]] = []
        monkeypatch.setattr(
            panel,
            "notify",
            lambda message, *args, **kwargs: toasts.append(
                (str(message), kwargs.get("severity"))
            ),
        )
        assert len([text for text in rail_texts(panel) if "● " in text]) == 2
        await pilot.press("m")
        await wait_for(
            pilot,
            lambda: any(
                "could not mark reviewed" in text for text, _severity in toasts
            ),
        )
        await pilot.pause()
        restored = [text for text in rail_texts(panel) if "● " in text]
        assert len(restored) == 2
        header = panel.query_one("#memory-panel-header", Static).content.plain
        assert "● 2 new" in header
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_mark_key_is_inert_outside_changes(monkeypatch) -> None:
    """``m`` in Notes or Timeline never touches the watermark."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = prepare_changes_panel(
        monkeypatch, feed=_review_feed(), review=_review_wire()
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("m")
        await pilot.pause()
        assert panel._ace_history().marked == []
        panel._lens = "timeline"
        await pilot.press("m")
        await pilot.pause()
        assert panel._ace_history().marked == []
        assert panel._lens == "timeline"


async def test_mark_reviewed_marks_each_scope_in_all_scopes(monkeypatch) -> None:
    """``m`` in All scopes marks every shown scope through its newest."""
    from sase.ace.testing import wait_for

    payload = _review_feed()
    payload["changesets"].append(
        make_changeset(
            commit="h" * 40,
            committer_time=_REVIEW_T0 + 50,
            subject="feat: home tweak",
            scope_key="home",
            bead="",
            agent="",
            authored=[],
            consequences=[],
        )
    )
    wire = _review_wire(home_new=1)
    wire["scopes"][1]["newest_commit"] = "h" * 40
    panel, app, _pushed = prepare_changes_panel(monkeypatch, feed=payload, review=wire)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await wait_for(pilot, lambda: tuple(panel._changes_review) != ())
        await pilot.pause()
        panel._changes_all_scopes = True  # The `p` ring's All entry.
        toasts: list[tuple[str, Any]] = []
        monkeypatch.setattr(
            panel,
            "notify",
            lambda message, *args, **kwargs: toasts.append(
                (str(message), kwargs.get("severity"))
            ),
        )
        await pilot.press("m")
        history = panel._ace_history()
        await wait_for(pilot, lambda: len(history.marked) == 2)
        assert ("project:sase", "a" * 40) in history.marked
        assert ("home", "h" * 40) in history.marked
        await wait_for(
            pilot,
            lambda: any(
                "marked 3 changesets reviewed · all scopes" in text
                for text, _severity in toasts
            ),
        )
