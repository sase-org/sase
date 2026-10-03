"""Tests for the Changes lens (phase `changes-lens`).

Covers the pure lens builders (day-grouped rows over the shared
``feed_model``, regen folding, the bounded window, the whole-feed
filter, ``All scopes`` merging with home tags, failed-scope chips,
provenance chips, totals, and section titles) and the mixin behaviors
that do not need git (lens open/close with Notes restore, inert keys,
window extension, stale-load drops, and the pager hand-off in the
diff view at the right version). Headless rail tests mount the
production host (``MemoryPane``) with a deterministic stub history
service.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.modals.memory_pane_changes_lens import (
    MORE_ROW_ID,
    MemoryPaneChangesLensMixin,
    _changes_day_label,
    _changes_lens_footer,
    _changes_lens_header_detail,
    _changes_lens_rows,
    _changes_provenance_text,
    _changes_row_id,
    _changes_row_is_selectable,
    _changes_section_title,
    _changes_totals_text,
)

_DAY_ONE = 1790486400
_DAY_TWO = 1790400000


def _authored(
    subject_id: str = "note:project:sase/glossary/artifact",
    ordinal: int = 3,
    class_name: str = "authored",
    path: str = "sase/memory/glossary/artifact.md",
) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "ordinal": ordinal,
        "class": class_name,
        "summary": {
            "section_paths": ["Definition"],
            "words_added": 20,
            "words_removed": 3,
        },
        "path": path,
        "commit": "d" * 40,
    }


def _changeset(
    commit: str = "d" * 40,
    committer_time: int = _DAY_ONE,
    subject: str = "feat(tabs): something",
    scope_key: str = "project:sase",
    bead: str = "sase-1bu.7",
    agent: str = "athena.sase-1bu.7",
    authored: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    regen_only: bool = False,
) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "commit": commit,
        "committer_time": committer_time,
        "provenance": {"subject": subject, "bead": bead, "agent": agent},
        "regen_only": regen_only,
        "authored": authored if authored is not None else [_authored()],
        "consequences": consequences
        if consequences is not None
        else [
            {
                "subject_id": "instructions:project:sase/.",
                "ordinal": 12,
                "class": "rendered",
                "summary": {},
                "path": "AGENTS.md",
            }
        ],
    }


def _feed(*changesets: dict[str, Any]) -> dict[str, Any]:
    if not changesets:
        return {
            "changesets": [
                _changeset(),
                _changeset(
                    commit="e" * 40,
                    committer_time=_DAY_ONE + 600,
                    subject="feat(home): tweak",
                    scope_key="home",
                    bead="",
                    agent="",
                    authored=[],
                    consequences=[],
                ),
                _changeset(
                    commit="f" * 40,
                    committer_time=_DAY_TWO,
                    subject="chore: regen",
                    bead="",
                    agent="",
                    authored=[],
                    consequences=[],
                    regen_only=True,
                ),
            ]
        }
    return {"changesets": list(changesets)}


def test_lens_rows_group_days_with_changesets() -> None:
    listed, total, older, regen = _changes_lens_rows(_feed(), now_epoch=_DAY_ONE + 7200)
    assert total == 2
    assert older == 0
    assert regen == 1
    kinds = [row["kind"] for row in listed]
    assert kinds[0] == "day"
    assert listed[0]["title"] == "Today"
    assert kinds.count("changeset") == 2
    assert kinds[-1] == "regen"


def test_lens_rows_survive_missing_feed() -> None:
    assert _changes_lens_rows(None) == ((), 0, 0, 0)
    assert _changes_lens_rows({})[1] == 0


def test_day_headers_are_not_selectable() -> None:
    listed, _, _, _ = _changes_lens_rows(_feed())
    day = next(row for row in listed if row["kind"] == "day")
    changeset = next(row for row in listed if row["kind"] == "changeset")
    assert _changes_row_is_selectable(day) is False
    assert _changes_row_is_selectable(changeset) is True
    assert _changes_row_is_selectable(None) is False


def test_day_labels_name_today_and_yesterday() -> None:
    today_key = datetime.datetime.fromtimestamp(_DAY_ONE).strftime("%Y-%m-%d")
    assert _changes_day_label(today_key, "Whatever", now_epoch=_DAY_ONE) == "Today"
    yesterday = datetime.datetime.fromtimestamp(_DAY_ONE) - datetime.timedelta(days=1)
    assert (
        _changes_day_label(
            yesterday.strftime("%Y-%m-%d"), "Whatever", now_epoch=_DAY_ONE
        )
        == "Yesterday"
    )
    assert (
        _changes_day_label("2020-01-01", "Wed Jan 01", now_epoch=_DAY_ONE)
        == "Wed Jan 01"
    )


def test_window_bounds_newest_and_appends_more_row() -> None:
    feed = _feed(
        *[
            _changeset(commit=f"{index:040d}", committer_time=_DAY_ONE + index)
            for index in range(250)
        ]
    )
    listed, total, older, _ = _changes_lens_rows(feed, limit=100)
    assert total == 250
    assert older == 150
    assert listed[-1]["kind"] == "more"
    assert listed[-1]["id"] == MORE_ROW_ID
    assert listed[-1]["older"] == 150


def test_filter_matches_whole_feed() -> None:
    feed = _feed()
    listed, total, _, _ = _changes_lens_rows(feed, query="glossary")
    assert total == 2
    assert sum(1 for row in listed if row["kind"] == "changeset") == 1
    listed_all, _, _, _ = _changes_lens_rows(feed, query="sase-1bu.7")
    assert sum(1 for row in listed_all if row["kind"] == "changeset") == 1
    listed_none, _, _, _ = _changes_lens_rows(feed, query="no-such-thing")
    assert [row["kind"] for row in listed_none] == ["regen"]


def test_all_scopes_merge_and_tag_home() -> None:
    listed, total, _, _ = _changes_lens_rows(_feed())
    views = [row["view"] for row in listed if row["kind"] == "changeset"]
    assert total == 2
    home = next(view for view in views if view.scope_key == "home")
    assert home.home is True


def test_failed_scope_shows_as_chip() -> None:
    detail = _changes_lens_header_detail(
        scope_label="project:sase",
        shown=2,
        total=2,
        failed_scopes=("home",),
    )
    assert "home unavailable" in detail
    assert "project:sase" in detail


def test_header_detail_names_window_and_regen() -> None:
    detail = _changes_lens_header_detail(
        scope_label="project:sase", shown=100, total=489, older=389, regen_folded=9
    )
    assert "last 100 of 489" in detail
    assert "9 regen-only folded" in detail
    assert _changes_lens_header_detail() == "no changes"


def test_changes_row_ids_are_stable() -> None:
    assert _changes_row_id("d" * 40, "project:sase") == _changes_row_id(
        "d" * 40, "project:sase"
    )
    assert _changes_row_id("d" * 40, "project:sase") != _changes_row_id(
        "e" * 40, "project:sase"
    )


def test_provenance_uses_artifact_icons() -> None:
    listed, _, _, _ = _changes_lens_rows(_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    chips = _changes_provenance_text(view)
    assert "◈ sase-1bu.7" in chips
    assert "⬡ athena.sase-1bu.7" in chips
    assert "◉ ddddddd" in chips


def test_totals_count_subjects_and_regenerated() -> None:
    listed, _, _, _ = _changes_lens_rows(_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    totals = _changes_totals_text(view)
    assert "1 subject" in totals
    assert "+20w" in totals
    assert "⟳ 1 regenerated" in totals


def test_section_titles_number_subjects() -> None:
    listed, _, _, _ = _changes_lens_rows(_feed())
    view = next(row["view"] for row in listed if row["kind"] == "changeset")
    (subject,) = view.authored
    title = _changes_section_title(1, subject)
    assert title.startswith(".1 ◆ glossary/artifact")
    assert "+20w" in title


def test_lens_footer_names_configured_keys() -> None:
    from sase.ace.tui.keymaps.app_keymaps import MemoryPanelKeymaps

    footer = _changes_lens_footer(MemoryPanelKeymaps())
    assert "j/k changeset" in footer
    assert "⏎/.N open" in footer
    assert "p/P scope" in footer
    assert "esc notes" in footer
    # The one-line footer ellipsizes past ~103 cells: the whole strip
    # must fit, including the newest verb.
    assert len(footer) <= 100


def _prepare_changes_panel(monkeypatch, feed=None, review=None, mark_error=None):  # noqa: ANN001, ANN202
    """Mount ``MemoryPane`` with one note and a stub feed-backed history.

    *review* is the ``review_state`` wire the stub service returns (``{}``
    when ``None``: no chip, no dots). The stub records ``mark_reviewed``
    calls on ``history.marked`` (raising *mark_error* instead when set)
    and advances its own watermark so the confirm refetch reads zeros.
    Reach it later through ``panel._ace_history()``.
    """
    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
        memory_note,
        scope_ref,
        scope_snapshot,
    )

    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("gotchas"), memory_note("zebra")))
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    payload = _feed() if feed is None else feed
    sase_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")
    home_scope = SimpleNamespace(scope_key="home", repo_root="/tmp")

    review_box: dict[str, Any] = {"wire": review}
    marked: list[tuple[str, str]] = []
    review_calls: list[list[str]] = []

    class _FakeHistory:
        def __init__(self) -> None:
            self.marked = marked
            self.review_calls = review_calls
            self.review_box = review_box
            self.mark_error = mark_error
            self.service = SimpleNamespace(
                review_state=self._review_state,
                mark_reviewed=self._mark_reviewed,
            )

        def _review_state(self, scopes):  # noqa: ANN001, ANN202
            self.review_calls.append(
                [str(getattr(scope, "scope_key", "") or "") for scope in scopes]
            )
            wire = self.review_box["wire"]
            if isinstance(wire, BaseException):
                raise wire
            if not isinstance(wire, dict):
                return {}
            return wire

        def _mark_reviewed(self, scope, through_commit, **_kwargs):  # noqa: ANN001, ANN202
            if self.mark_error is not None:
                raise self.mark_error
            key = str(getattr(scope, "scope_key", "") or "")
            through = str(through_commit or "")
            self.marked.append((key, through))
            # Mirror core: the watermark advances to the through commit,
            # so its stamp is that changeset's committer time.
            stamp = 0
            for changeset in payload.get("changesets", ()):
                if str(changeset.get("commit", "")) == through:
                    try:
                        stamp = int(changeset.get("committer_time", 0) or 0)
                    except (TypeError, ValueError):
                        stamp = 0
                    break
            wire = self.review_box["wire"]
            if isinstance(wire, dict):
                entries = []
                seen = False
                for raw in wire.get("scopes", ()):
                    entry = dict(raw)
                    if str(entry.get("scope_key", "")) == key:
                        entry["new_count"] = 0
                        entry["watermark"] = {
                            "commit": through,
                            "committer_time": stamp,
                            "marked_at": stamp,
                        }
                        seen = True
                    entries.append(entry)
                if not seen:
                    entries.append(
                        {
                            "scope_key": key,
                            "watermark": {
                                "commit": through,
                                "committer_time": stamp,
                                "marked_at": stamp,
                            },
                            "new_count": 0,
                            "newest_commit": through,
                        }
                    )
                self.review_box["wire"] = {"scopes": entries}
            return {"scope_key": key}

        def scope_for_ref(self, _ref):
            return sase_scope

        def feed(self, _scopes):
            return dict(payload)

        def version_body(self, _scope, _selector, version):
            return {
                "body": f"body {version}\n",
                "body_missing": False,
                "blob_oid": f"blob-{version}",
            }

        def comparison(self, _scope, _selector, _base, _target):
            return {"ops": []}

    history = _FakeHistory()
    monkeypatch.setattr(panel, "_ace_history", lambda: history)
    import sase.ace.tui.modals.memory_panel_history as history_module

    monkeypatch.setattr(
        history_module,
        "history_scopes_for_ring",
        lambda _ring, _svc: [sase_scope, home_scope],
    )

    pushed: list = []

    class _FakePager(Screen):
        def __init__(self, document: object, **_kwargs: object) -> None:
            super().__init__()
            self.document = document
            pushed.append(self)

        def compose(self):  # noqa: ANN202
            yield Static("pager")

    import sase.pager.screen as pager_screen_module
    import sase.pager.syntax_policy as syntax_policy_module

    monkeypatch.setattr(pager_screen_module, "PagerScreen", _FakePager)
    monkeypatch.setattr(
        syntax_policy_module,
        "pager_syntax_session_from_config",
        lambda: SimpleNamespace(syntax_enabled=False),
    )
    return panel, app, pushed


def _rail_texts(panel) -> list[str]:  # noqa: ANN001, ANN202
    from tests.ace.tui.modals.memory_panel_test_helpers import note_row_text

    count = int(panel._note_list().option_count)
    return [note_row_text(panel, index) for index in range(count)]


async def test_changes_lens_opens_and_esc_restores_notes(monkeypatch) -> None:
    """``C`` turns the rail into changesets; ``Esc`` restores Notes."""
    from textual.widgets import Static

    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        before = panel._current_note
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        texts = _rail_texts(panel)
        assert any("Today" in text or "━" in text for text in texts)
        assert any("artifact" in text for text in texts)
        header = panel.query_one("#memory-panel-header", Static)
        assert "changes" in str(header.content.plain)
        await pilot.press("escape")
        await wait_for(pilot, lambda: panel._lens == "notes")
        assert panel._current_note == before
        restored = _rail_texts(panel)
        assert any("gotchas" in text for text in restored)


async def test_timeline_key_is_inert_in_changes(monkeypatch) -> None:
    """``@`` does nothing inside the Changes lens."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await pilot.press("@")
        await pilot.pause()
        assert panel._lens == "changes"


async def test_changes_key_is_inert_in_timeline(monkeypatch) -> None:
    """``C`` stays inert inside the Timeline lens (D3)."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        panel._lens = "timeline"
        await pilot.press("C")
        await pilot.pause()
        assert panel._lens == "timeline"


async def test_pager_handoff_uses_diff_view_at_changeset_version(monkeypatch) -> None:
    """``H`` in the lens opens the pager in diff view at the right version."""
    from sase.ace.testing import wait_for

    panel, app, pushed = _prepare_changes_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    seen: dict = {}
    sentinel = object()
    monkeypatch.setattr(
        pager_provider_module,
        "build_history_document",
        lambda **kwargs: (seen.update(kwargs), sentinel)[1],
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        # Move onto the first changeset row (past the day header).
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert seen["initial_revision"] == "v3"
        assert seen["view"] == "diff"
        assert seen["subject"] == "sase/memory/glossary/artifact.md"
        assert pushed[0].document is sentinel


async def test_window_extends_at_more_row(monkeypatch) -> None:
    """Reaching the trailing row grows the window by 100."""
    from sase.ace.testing import wait_for

    big = _feed(
        *[
            _changeset(commit=f"{index:040d}", committer_time=_DAY_ONE + index)
            for index in range(150)
        ]
    )
    panel, app, _pushed = _prepare_changes_panel(monkeypatch, feed=big)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        assert panel._changes_limit == 100
        assert panel._changes_older == 50
        panel._changes_extend_window()
        assert panel._changes_limit == 200
        assert panel._changes_older == 0


async def test_changes_filter_routes_to_lens_rows(monkeypatch) -> None:
    """``/`` in the lens filters changesets, leaving the Notes filter alone."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(monkeypatch)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._changes_feed is not None)
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        await pilot.press("g")
        await pilot.press("l")
        await pilot.press("o")
        await pilot.pause()
        texts = _rail_texts(panel)
        assert any("artifact" in text for text in texts)
        assert panel._filter_text == ""
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert panel._lens == "notes"


async def test_stale_feed_load_is_dropped(monkeypatch) -> None:
    """A feed that lands after a refetch never paints (last wins)."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    history = panel._ace_history()
    real_feed = history.feed

    def _slow_feed(scopes):  # noqa: ANN001, ANN202
        started.set()
        assert release.wait(timeout=10)
        return real_feed(scopes)

    history.feed = _slow_feed
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        await wait_for(pilot, lambda: started.is_set())
        panel._changes_generation += 1  # A refetch won before the load landed.
        release.set()
        await wait_for(pilot, lambda: panel._changes_worker.is_finished)
        await pilot.pause()
        assert panel._changes_feed is None


def test_preview_fire_drops_superseded_motion() -> None:
    """A scheduled preview older than the cursor never renders."""
    panel = MemoryPaneChangesLensMixin.__new__(MemoryPaneChangesLensMixin)
    panel._lens = "changes"  # type: ignore[attr-defined]
    panel._changes_cursor = 2  # type: ignore[attr-defined]
    panel._changes_scheduled = 1  # type: ignore[attr-defined]
    rendered: list = []
    panel._render_note_card = lambda: rendered.append(True)  # type: ignore[method-assign]
    panel._changes_preview_fire()
    assert rendered == []


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
            _authored(
                subject_id=f"note:project:sase/{name}",
                path=f"sase/memory/{name}.md",
            )
        ]

    return {
        "changesets": [
            _changeset(
                commit="a" * 40,
                committer_time=_REVIEW_T0 + 300,
                subject="feat: newest",
                authored=_named("alpha"),
            ),
            _changeset(
                commit="b" * 40,
                committer_time=_REVIEW_T0 + 100,
                subject="feat: newer",
                authored=_named("beta"),
            ),
            _changeset(
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

    panel, app, _pushed = _prepare_changes_panel(
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
        texts = _rail_texts(panel)
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
        assert not any("● " in text for text in _rail_texts(panel))
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
        assert not any("● " in text for text in _rail_texts(panel))
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
        assert len([text for text in _rail_texts(panel) if "● " in text]) == 2
        await pilot.press("m")
        await wait_for(
            pilot,
            lambda: any(
                "could not mark reviewed" in text for text, _severity in toasts
            ),
        )
        await pilot.pause()
        restored = [text for text in _rail_texts(panel) if "● " in text]
        assert len(restored) == 2
        header = panel.query_one("#memory-panel-header", Static).content.plain
        assert "● 2 new" in header
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_mark_key_is_inert_outside_changes(monkeypatch) -> None:
    """``m`` in Notes or Timeline never touches the watermark."""
    from sase.ace.testing import wait_for

    panel, app, _pushed = _prepare_changes_panel(
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

    feed = _review_feed()
    feed["changesets"].append(
        _changeset(
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
    panel, app, _pushed = _prepare_changes_panel(monkeypatch, feed=feed, review=wire)
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
