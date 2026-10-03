"""Rail recency glance and deleted subjects (phase rail-glance)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.modals.memory_pane_rail_glance import (
    DeletedSubject,
    build_deleted_row_text,
    build_recency_map,
    deleted_subjects,
    glance_glyph_only,
    glance_suffix,
    history_only_node,
    is_promotion_class,
    node_glance_path,
    subject_displays,
)
from sase.ace.tui.modals.memory_panel_rendering import build_note_row_text

_NOW = 1790769600
_DAY = 86400


def _entry(
    subject_id: str,
    path: str,
    class_name: str,
    ordinal: int = 3,
) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "ordinal": ordinal,
        "class": class_name,
        "summary": {},
        "path": path,
    }


def _changeset(
    *entries: dict[str, Any],
    committer_time: int = _NOW - _DAY,
    commit: str = "d" * 40,
    consequences: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    return {
        "scope_key": "project:sase",
        "commit": commit,
        "committer_time": committer_time,
        "provenance": {},
        "authored": list(entries),
        "consequences": list(consequences),
    }


def _feed(*changesets: dict[str, Any]) -> dict[str, Any]:
    return {"changesets": list(changesets)}


def test_recency_map_newest_wins_across_authored_and_consequences() -> None:
    feed = _feed(
        _changeset(
            _entry("note:project:sase/b", "sase/memory/b.md", "authored"),
            committer_time=_NOW - _DAY,
            commit="n" * 40,
        ),
        _changeset(
            committer_time=_NOW - 2 * _DAY,
            commit="o" * 40,
            consequences=(
                _entry("note:project:sase/b", "sase/memory/b.md", "promoted"),
            ),
        ),
    )
    recency = build_recency_map(feed)
    assert recency["sase/memory/b.md"] == ("authored", _NOW - _DAY)


def test_recency_map_skips_malformed_entries() -> None:
    feed = _feed(
        _changeset(
            {"subject_id": "x", "class": "authored"},
            _entry("", "", "authored"),
            _entry("note:project:sase/ok", "sase/memory/ok.md", ""),
            _entry("note:project:sase/good", "sase/memory/good.md", "authored"),
            committer_time=_NOW - 3600,
        )
    )
    recency = build_recency_map(feed)
    assert set(recency) == {"sase/memory/good.md"}


def test_recency_map_survives_malformed_feed() -> None:
    assert build_recency_map(None) == {}
    assert build_recency_map({}) == {}
    assert build_recency_map({"changesets": "nope"}) == {}
    assert deleted_subjects(None) == ()
    assert subject_displays(None) == {}


def test_node_glance_path_covers_notes_webs_and_strands() -> None:
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        memory_note,
        memory_web_with_mentioning_strands,
    )

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    note_node = MemoryRailNode(note=memory_note("gotchas"), depth=0)
    assert node_glance_path(note_node) == "sase/memory/gotchas.md"

    web = memory_web_with_mentioning_strands()
    web_node = MemoryRailNode(note=memory_note("glossary"), depth=0, web=web)
    assert node_glance_path(web_node) == "sase/memory/glossary.md"

    strand = web.strands[0]
    strand_node = MemoryRailNode(
        note=memory_note("alpha"), depth=1, web=web, strand=strand
    )
    assert node_glance_path(strand_node) == "sase/memory/glossary/alpha.md"


def test_deleted_subjects_keep_latest_deletion_only() -> None:
    feed = _feed(
        # Newest first: recreated subject's latest entry is a creation.
        _changeset(
            _entry("note:project:sase/back", "sase/memory/back.md", "created"),
            committer_time=_NOW - _DAY,
            commit="n" * 40,
        ),
        _changeset(
            _entry("note:project:sase/gone", "sase/memory/gone.md", "deleted"),
            committer_time=_NOW - 2 * _DAY,
            commit="m" * 40,
        ),
        _changeset(
            _entry(
                "note:project:sase/back",
                "sase/memory/back.md",
                "deleted",
                ordinal=2,
            ),
            committer_time=_NOW - 10 * _DAY,
            commit="o" * 40,
        ),
        _changeset(
            _entry(
                "strand:project:sase/glossary/old",
                "sase/memory/glossary/old.md",
                "deleted",
            ),
            committer_time=_NOW - _DAY,
            commit="p" * 40,
        ),
    )
    deleted = deleted_subjects(feed)
    assert [subject.path for subject in deleted] == [
        "sase/memory/gone.md",
        "sase/memory/glossary/old.md",
    ]


def test_deleted_subjects_use_display_names_with_stem_fallback() -> None:
    feed = _feed(
        _changeset(
            _entry("note:project:sase/gone", "sase/memory/gone.md", "deleted"),
            committer_time=_NOW - _DAY,
        )
    )
    (only,) = deleted_subjects(feed, displays={"note:project:sase/gone": "Gone Note"})
    assert only.display == "Gone Note"
    (fallback,) = deleted_subjects(feed)
    assert fallback.display == "gone"


def test_glance_suffix_uses_kit_glyph_and_age() -> None:
    assert glance_suffix("promoted", _NOW - 8 * _DAY, now_epoch=_NOW) == "⇧ 8d"
    assert glance_suffix("authored", _NOW - 3 * 3600, now_epoch=_NOW) == "◆ 3h"
    assert glance_suffix("rendered", _NOW - 60, now_epoch=_NOW) == "⟳ 1m"
    assert glance_glyph_only("deleted") == "✖"
    assert is_promotion_class("promoted") is True
    assert is_promotion_class("demoted") is True
    assert is_promotion_class("authored") is False


def test_note_row_sheds_age_then_glyph() -> None:
    from tests.ace.tui.modals.memory_panel_test_helpers import memory_note

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    node = MemoryRailNode(note=memory_note("gotchas"), depth=0)
    full = build_note_row_text(
        node,
        generated_paths=frozenset(),
        glance="⇧ 8d",
        glance_glyph="⇧",
        content_width=60,
    )
    assert full.plain.endswith("⇧ 8d")

    shed = build_note_row_text(
        node,
        generated_paths=frozenset(),
        glance="⇧ 8d",
        glance_glyph="⇧",
        content_width=len("○ gotchas") + 3,
    )
    assert shed.plain.endswith("⇧")
    assert "8d" not in shed.plain

    gone = build_note_row_text(
        node,
        generated_paths=frozenset(),
        glance="⇧ 8d",
        glance_glyph="⇧",
        content_width=len("○ gotchas"),
    )
    assert "⇧" not in gone.plain


def test_note_row_promotions_keep_highlight() -> None:
    from tests.ace.tui.modals.memory_panel_test_helpers import memory_note

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode

    node = MemoryRailNode(note=memory_note("gotchas"), depth=0)
    text = build_note_row_text(
        node,
        generated_paths=frozenset(),
        glance="⇧ 8d",
        glance_glyph="⇧",
        glance_promoted=True,
    )
    assert text.plain.endswith("⇧ 8d")
    assert "bold" in (text.spans[-1].style if text.spans else "")


def test_deleted_row_text() -> None:
    text = build_deleted_row_text("gone", _NOW - 21 * _DAY, now_epoch=_NOW)
    assert text.plain == "✖ gone   deleted 21d"


def test_history_only_node_marks_kind_and_ordinal() -> None:
    subject = DeletedSubject(
        subject_id="note:project:sase/gone",
        path="sase/memory/gone.md",
        display="gone",
        committer_time=_NOW - _DAY,
        ordinal=4,
        commit="m" * 40,
    )
    node = history_only_node(subject)
    assert node.history_only is True
    assert node.deleted_ordinal == 4
    assert node.identity == "sase/memory/gone.md"


def _deleted_row(ordinal: int = 2, **override: object) -> dict:
    base: dict = {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": _NOW - _DAY,
        "class": "authored",
        "hidden": False,
        "summary": {},
        "path": "sase/memory/old.md",
        "blob_oid": f"blob{ordinal}",
    }
    base.update(override)
    return base


def _prepare_glance_panel(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feed: dict | None = None,
    subjects: dict | None = None,
    timeline: dict | None = None,
    fail_glance: bool = False,
):  # noqa: ANN001, ANN202
    """Mount ``MemoryPane`` with one live note and a stub history service."""
    from sase.ace.testing import wait_for  # noqa: F401
    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
        memory_note,
        scope_ref,
        scope_snapshot,
    )

    ref = scope_ref("sase", "sase")
    snapshots = {"sase": scope_snapshot(ref, (memory_note("gotchas"),))}
    install_fixed_load(monkeypatch, (ref,), snapshots)
    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    payload = dict(feed) if feed is not None else {}
    subject_payload = dict(subjects) if subjects is not None else {"subjects": []}
    timeline_payload = dict(timeline) if timeline is not None else None
    sase_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")

    class _FakeHistory:
        def scope_for_ref(self, _ref):
            return sase_scope

        def subjects(self, _scope):
            if fail_glance:
                raise RuntimeError("index unavailable")
            return dict(subject_payload)

        def feed(self, _scopes):
            if fail_glance:
                raise RuntimeError("index unavailable")
            return dict(payload)

        def timeline(self, _scope, _selector, include_hidden=False):
            if timeline_payload is None:
                raise RuntimeError("no timeline")
            return dict(timeline_payload)

        def version_body(self, _scope, _selector, version):
            return {
                "body": f"last content {version}\n",
                "body_missing": False,
                "blob_oid": f"blob-{version}",
            }

    monkeypatch.setattr(panel, "_ace_history", lambda: _FakeHistory())
    return panel, app


def _rail_texts(panel) -> list[str]:  # noqa: ANN001, ANN202
    from tests.ace.tui.modals.memory_panel_test_helpers import note_row_text

    count = int(panel._note_list().option_count)
    return [note_row_text(panel, index) for index in range(count)]


async def test_glance_column_lands_on_live_rows(monkeypatch) -> None:
    """Rows paint first, then gain the glyph-and-age column off-thread."""
    from sase.ace.testing import wait_for

    feed = _feed(
        _changeset(
            _entry(
                "note:project:sase/gotchas",
                "sase/memory/gotchas.md",
                "promoted",
            ),
            committer_time=_NOW - 8 * _DAY,
        )
    )
    panel, app = _prepare_glance_panel(monkeypatch, feed=feed)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._glance_map))
        await pilot.pause()
        texts = _rail_texts(panel)
        assert any("⇧" in text for text in texts)


async def test_failed_glance_keeps_rail_without_column(monkeypatch) -> None:
    """A failed glance load omits the column and keeps the rail usable."""
    from sase.ace.testing import wait_for

    panel, app = _prepare_glance_panel(monkeypatch, feed=_feed(), fail_glance=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: panel._glance_failed)
        await pilot.pause()
        texts = _rail_texts(panel)
        assert any("gotchas" in text for text in texts)
        assert all("⇧" not in text and "◆" not in text for text in texts)


async def test_deleted_toggle_lists_tombstones_and_header(monkeypatch) -> None:
    """``D`` appends the DELETED group; the header gains ``· N deleted``."""
    from textual.widgets import Static

    from sase.ace.testing import wait_for

    feed = _feed(
        _changeset(
            _entry("note:project:sase/old", "sase/memory/old.md", "deleted", ordinal=2),
            committer_time=_NOW - 21 * _DAY,
        )
    )
    subjects = {
        "subjects": [
            {
                "id": "note:project:sase/old",
                "kind": "note",
                "display_name": "old.md",
                "paths": ["sase/memory/old.md"],
            }
        ]
    }
    panel, app = _prepare_glance_panel(monkeypatch, feed=feed, subjects=subjects)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._glance_map))
        await pilot.press("D")
        await wait_for(pilot, lambda: panel._show_deleted)
        await pilot.pause()
        texts = _rail_texts(panel)
        assert texts[-1].startswith("✖")
        assert "deleted" in texts[-1]
        header = panel.query_one("#memory-panel-header", Static)
        assert "1 deleted" in str(header.content.plain)
        await pilot.press("D")
        await wait_for(pilot, lambda: not panel._show_deleted)
        await pilot.pause()
        assert all("✖" not in text for text in _rail_texts(panel))


async def test_deleted_toggle_empty_toasts_and_stays_off(monkeypatch) -> None:
    """``D`` with no deleted subjects toasts instead of opening a group."""
    from sase.ace.testing import wait_for

    panel, app = _prepare_glance_panel(monkeypatch, feed=_feed())
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(
            pilot,
            lambda: (
                panel._glance_worker is not None and panel._glance_worker.is_finished
            ),
        )
        await pilot.pause()
        await pilot.press("D")
        await pilot.pause()
        assert panel._show_deleted is False


async def test_history_only_rows_refuse_mutations(monkeypatch) -> None:
    """Tombstone rows are read-only: edit/delete/source refuse with a toast."""
    from sase.ace.testing import wait_for

    feed = _feed(
        _changeset(
            _entry("note:project:sase/old", "sase/memory/old.md", "deleted", ordinal=2),
            committer_time=_NOW - 21 * _DAY,
        )
    )
    panel, app = _prepare_glance_panel(monkeypatch, feed=feed)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._glance_map))
        await pilot.press("D")
        await wait_for(pilot, lambda: panel._show_deleted)
        await pilot.press("G")
        await wait_for(
            pilot,
            lambda: (
                (panel._selected_row() is not None)
                and panel._selected_row().history_only
            ),
        )
        node = panel._selected_row()
        assert node is not None and node.history_only
        assert panel._selected_is_writable() is False
        panel.action_edit_note()
        panel.action_delete_note()
        panel.action_open_source()
        await pilot.pause()
        assert panel._current_note == node.identity


async def test_tombstone_selection_pins_deletion_ordinal(monkeypatch) -> None:
    """Selecting a tombstone pins its deletion version for the past card."""
    from sase.ace.testing import wait_for

    feed = _feed(
        _changeset(
            _entry("note:project:sase/old", "sase/memory/old.md", "deleted", ordinal=2),
            committer_time=_NOW - 21 * _DAY,
        )
    )
    timeline = {
        "selector": "sase/memory/old.md",
        "scope_key": "project:sase",
        "state": "tracked",
        "versions": [
            _deleted_row(1),
            _deleted_row(2, **{"class": "deleted"}),
        ],
        "total": 2,
        "dirty": False,
    }
    panel, app = _prepare_glance_panel(monkeypatch, feed=feed, timeline=timeline)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await wait_for(pilot, lambda: bool(panel._glance_map))
        await pilot.press("D")
        await wait_for(pilot, lambda: panel._show_deleted)
        await pilot.press("G")
        await wait_for(
            pilot,
            lambda: (
                (panel._selected_row() is not None)
                and panel._selected_row().history_only
            ),
        )
        node = panel._selected_row()
        assert node is not None and node.history_only
        key = panel._time_key(node)
        assert key is not None
        await wait_for(pilot, lambda: panel._time_pins.get(key, 0) == 2)
        await wait_for(pilot, lambda: panel._time_applied_ordinal(node) == 2)
