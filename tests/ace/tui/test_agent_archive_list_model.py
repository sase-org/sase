"""Archive list model: banners, page windows, flattened items, and cursors."""

from __future__ import annotations

from datetime import date, datetime, UTC
from typing import Any

import pytest

from sase.ace.tui.models.agent_archive_controller import (
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_REBUILDING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_CORPUS_WARM,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ArchiveLoadedWindow,
    ArchivePageWindow,
)
from sase.ace.tui.models.agent_archive_view import (
    container_key_of,
    is_archive_container_key,
    is_archive_row_key,
)
from sase.ace.tui.models.agent_archive_list import (
    ARCHIVE_PAGE_SIZE,
    ITEM_BANNER,
    ITEM_CONTAINER,
    ITEM_LOADING,
    ITEM_MEMBER,
    ITEM_MESSAGE,
    ITEM_ROW,
    ITEM_TAIL,
    ArchiveListModel,
    archive_row_key,
    archive_timezone,
    assemble_archive_list,
    banner_key_for_row,
    build_archive_banners,
    default_open_banner_keys,
    edge_key,
    effective_open_banner_keys,
    fallback_cursor,
    neighbor_key,
    parent_banner_key,
    plan_archive_windows,
    windows_satisfy,
    with_banner_open,
)

TODAY = date(2026, 10, 10)


def _summary(*groups: tuple[str, int]) -> dict[str, Any]:
    return {
        "total": sum(count for _group, count in groups),
        "groups": [{"key": key, "count": count} for key, count in groups],
    }


def _row(run: str, *, day: str = "2026-10-10", **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "archive_key": {
            "source_username": "u",
            "source_machine": "m",
            "source_run_id": run,
        },
        "container_key": f"archive:u.m@{run}",
        "container": False,
        "member_count": 1,
        "agent_name": f"agent-{run}",
        "status": "DONE",
        "outcome": "done",
        "last_activity_at": f"{day}T15:00:00Z",
        "time_basis": "ended",
    }
    row.update(extra)
    return row


def _container(key: str, count: int, **extra: Any) -> dict[str, Any]:
    row = _row("newest", container_key=key, container=True, member_count=count)
    row["agent_name"] = key
    row.update(extra)
    return row


def _window(group: str, rows: list[dict[str, Any]], total: int | None = None):
    return ArchiveLoadedWindow(
        group_key=group,
        offset=0,
        limit=len(rows),
        rows=tuple(rows),
        total=len(rows) if total is None else total,
    )


def _assemble(
    banners,
    windows,
    *,
    open_keys=None,
    pages=None,
    expanded=(),
    applied=None,
    status=ARCHIVE_CORPUS_WARM,
    loading=False,
    summary_known=True,
    indexed_rows=0,
    error=None,
) -> ArchiveListModel:
    return assemble_archive_list(
        banners=banners,
        open_keys={b.key for b in banners} if open_keys is None else open_keys,
        windows=windows,
        pages=pages or {},
        desired_expanded=expanded,
        applied_expanded=expanded if applied is None else applied,
        status=status,
        error_message=error,
        indexed_rows=indexed_rows,
        summary_known=summary_known,
        loading=loading,
    )


# --- identity ---------------------------------------------------------------


def test_legacy_duplicate_names_get_unique_list_ids() -> None:
    banners = build_archive_banners(_summary(("2026-10-10", 2)), "day", today=TODAY)
    model = _assemble(
        banners,
        [_window("2026-10-10", [{"name": "legacy"}, {"name": "legacy"}])],
    )
    keys = [item.key for item in model.items if item.kind == ITEM_ROW]
    assert keys == ["legacy", "legacy#2"]
    assert len({item.key for item in model.items}) == len(model.items)


def test_project_banners_use_display_snapshot_labels() -> None:
    from sase.project_display_names import ProjectDisplaySnapshot

    summary = _summary(("gh_acme__widgets", 3), ("plain", 1))
    raw = build_archive_banners(summary, "project", today=TODAY)
    assert [(b.key, b.label) for b in raw] == [
        ("project:gh_acme__widgets", "gh_acme__widgets"),
        ("project:plain", "plain"),
    ]
    labeled = build_archive_banners(
        summary,
        "project",
        today=TODAY,
        display_snapshot=ProjectDisplaySnapshot(
            {"gh_acme__widgets": "widgets", "plain": "plain"}
        ),
    )
    assert [(b.key, b.label) for b in labeled] == [
        ("project:gh_acme__widgets", "widgets"),
        ("project:plain", "plain"),
    ]


def test_row_keys_distinguish_runs_containers_and_banners() -> None:
    assert archive_row_key(_row("r1")) == "u.m@r1"
    assert archive_row_key(_container("clan:x:1", 3)) == "container:clan:x:1"
    assert archive_row_key(
        {"name": "legacy", "archive_key": {"source_run_id": "1"}}
    ) == ("legacy")
    assert archive_row_key({"archive_key": {"source_run_id": "9"}}) == "9"
    assert archive_row_key({}) is None
    assert is_archive_row_key("u.m@r1")
    assert is_archive_container_key("container:clan:x:1")
    assert container_key_of("container:clan:x:1") == "clan:x:1"
    assert container_key_of("u.m@r1") is None
    assert not is_archive_row_key("banner:day:2026-10-10")
    assert not is_archive_row_key("tail:day:2026-10-10")
    assert not is_archive_row_key(None)


# --- banners ----------------------------------------------------------------


def test_day_banners_flatten_today_yesterday_days_weeks_then_months() -> None:
    summary = _summary(
        ("2026-10-10", 2),  # today
        ("2026-10-09", 3),  # yesterday
        ("2026-10-07", 1),  # last-week day
        ("2026-10-04", 4),  # last-week day
        ("2026-09-30", 2),  # weeks...
        ("2026-09-29", 1),
        ("2026-09-22", 5),
        ("2026-08-20", 6),  # age 51: still weekly
        ("2026-07-01", 7),  # older than two months: monthly
        ("2026-07-02", 1),
        ("", 2),
    )

    banners = build_archive_banners(summary, "day", today=TODAY)

    assert [(b.key, b.label, b.count) for b in banners] == [
        ("day:2026-10-10", "Today", 2),
        ("day:2026-10-09", "Yesterday", 3),
        ("day:2026-10-07", "Wed Oct 7", 1),
        ("day:2026-10-04", "Sun Oct 4", 4),
        ("week:2026-09-28", "Sep 28-Oct 4", 3),
        ("week:2026-09-21", "Sep 21-27", 5),
        ("week:2026-08-17", "Aug 17-23", 6),
        ("month:2026-07", "July 2026", 8),
        ("none", "(no timestamp)", 2),
    ]
    merged = banners[4]
    assert merged.group_keys == ("2026-09-30", "2026-09-29")
    assert merged.group_counts == (2, 1)


def test_future_activity_folds_into_today_and_core_counts_stay_authoritative() -> None:
    summary = _summary(("2026-10-12", 1), ("2026-10-10", 2))

    (banner,) = build_archive_banners(summary, "day", today=TODAY)

    assert banner.key == "day:2026-10-10"
    assert banner.count == 3
    assert banner.group_keys == ("2026-10-12", "2026-10-10")


def test_non_day_groupings_use_core_groups_as_banners() -> None:
    summary = _summary(("sase", 3), ("", 1))
    banners = build_archive_banners(summary, "project", today=TODAY)
    assert [(b.key, b.label) for b in banners] == [
        ("project:sase", "sase"),
        ("project:", "(no project)"),
    ]
    outcome = build_archive_banners(
        _summary(("interrupted", 1)), "outcome", today=TODAY
    )
    assert outcome[0].label == "Interrupted"
    model = build_archive_banners(_summary(("opus", 1), ("", 2)), "model", today=TODAY)
    assert [b.label for b in model] == ["opus", "(no model)"]
    assert build_archive_banners(None, "day", today=TODAY) == ()


@pytest.mark.parametrize(
    ("zone", "expected_key"),
    [
        ("UTC", "day:2026-10-11"),
        ("America/New_York", "day:2026-10-10"),
        ("UTC-0400", "day:2026-10-10"),
        ("UTC+0900", "day:2026-10-11"),
    ],
)
def test_row_banner_uses_the_corpus_timezone(zone: str, expected_key: str) -> None:
    row = _row("r1", last_activity_at="2026-10-11T02:30:00Z")
    tz = archive_timezone(zone)
    today = date(2026, 10, 11) if zone == "UTC" or zone == "UTC+0900" else TODAY

    assert banner_key_for_row(row, "day", tz, today) == expected_key


def test_row_banner_for_other_groupings_and_missing_time() -> None:
    row = _row("r1", project="sase", model="opus", outcome="failed")
    tz = archive_timezone("UTC")
    assert banner_key_for_row(row, "project", tz, TODAY) == "project:sase"
    assert banner_key_for_row(row, "model", tz, TODAY) == "model:opus"
    assert banner_key_for_row(row, "outcome", tz, TODAY) == "outcome:failed"
    assert banner_key_for_row(_row("r2", last_activity_at=None), "day", tz, TODAY) == (
        "none"
    )
    assert banner_key_for_row(row, "century", tz, TODAY) is None


def test_unknown_timezone_name_falls_back_to_local() -> None:
    assert archive_timezone("Not/AZone") is not None
    assert archive_timezone("") is not None
    assert archive_timezone(None).utcoffset(datetime.now(UTC)) is not None


# --- folds ------------------------------------------------------------------


def test_default_open_banners_today_yesterday_or_everything_when_small() -> None:
    summary = _summary(("2026-10-10", 30), ("2026-10-09", 30), ("2026-10-01", 40))
    banners = build_archive_banners(summary, "day", today=TODAY)

    opened = default_open_banner_keys(banners, grouping="day", total=100, today=TODAY)
    assert opened == {"day:2026-10-10", "day:2026-10-09"}

    small = default_open_banner_keys(banners, grouping="day", total=50, today=TODAY)
    assert small == {b.key for b in banners}

    rebuilding = default_open_banner_keys(
        banners, grouping="day", total=50, today=TODAY, complete=False
    )
    assert rebuilding == {"day:2026-10-10", "day:2026-10-09"}

    projects = build_archive_banners(
        _summary(("a", 60), ("b", 60)), "project", today=TODAY
    )
    assert default_open_banner_keys(
        projects, grouping="project", total=120, today=TODAY
    ) == {"project:a"}


def test_explicit_fold_changes_override_defaults_and_round_trip() -> None:
    default = frozenset({"day:a", "day:b"})
    assert effective_open_banner_keys(default, (), ()) == default

    expanded, folded = with_banner_open((), (), "day:a", open=False, default_open=True)
    assert (expanded, folded) == ((), ("day:a",))
    assert effective_open_banner_keys(default, expanded, folded) == {"day:b"}

    expanded, folded = with_banner_open(
        expanded, folded, "day:c", open=True, default_open=False
    )
    assert effective_open_banner_keys(default, expanded, folded) == {"day:b", "day:c"}

    expanded, folded = with_banner_open(
        expanded, folded, "day:a", open=True, default_open=True
    )
    expanded, folded = with_banner_open(
        expanded, folded, "day:c", open=False, default_open=False
    )
    assert (expanded, folded) == ((), ())


# --- window planning --------------------------------------------------------


def test_window_plan_spans_component_groups_in_order_with_cumulative_caps() -> None:
    summary = _summary(("2026-09-30", 60), ("2026-09-29", 70), ("2026-09-28", 80))
    (banner,) = build_archive_banners(summary, "day", today=TODAY)

    plan = plan_archive_windows([banner], {banner.key}, {})

    assert plan == (
        ArchivePageWindow("2026-09-30", 0, ARCHIVE_PAGE_SIZE),
        ArchivePageWindow("2026-09-29", 0, ARCHIVE_PAGE_SIZE - 60),
    )

    second_page = plan_archive_windows([banner], {banner.key}, {banner.key: 2})
    assert [w.limit for w in second_page] == [200, 140, 70]

    probed = plan_archive_windows([banner], {banner.key}, {}, probe_totals=True)
    assert probed[-1] == ArchivePageWindow("2026-09-28", 0, 0)


def test_window_plan_skips_folded_banners_and_satisfy_check() -> None:
    summary = _summary(("2026-10-10", 3), ("2026-10-09", 4))
    banners = build_archive_banners(summary, "day", today=TODAY)

    plan = plan_archive_windows(banners, {"day:2026-10-09"}, {})

    assert plan == (ArchivePageWindow("2026-10-09", 0, ARCHIVE_PAGE_SIZE),)
    # Every row of the group is already loaded: a bigger page needs no request.
    rows = tuple(_row(f"r{i}") for i in range(4))
    complete = ArchiveLoadedWindow("2026-10-09", 0, 50, rows, 4)
    assert windows_satisfy([complete], plan)
    assert windows_satisfy(
        [complete],
        plan_archive_windows(banners, {"day:2026-10-09"}, {"day:2026-10-09": 2}),
    )
    # A truncated window cannot serve a larger page.
    truncated = ArchiveLoadedWindow("2026-10-09", 0, 2, rows[:2], 4)
    assert not windows_satisfy([truncated], plan)
    assert not windows_satisfy([], plan)
    # Extra loaded windows (a folded banner's) are harmless.
    extra = ArchiveLoadedWindow("2026-10-10", 0, 100, (), 3)
    assert windows_satisfy([extra, complete], plan)
    assert windows_satisfy((), ())
    probe = (ArchivePageWindow("2026-10-09", 0, 0),)
    assert windows_satisfy([truncated], probe)


# --- assembly ---------------------------------------------------------------


def test_assemble_renders_banner_rows_with_ordered_unique_keys() -> None:
    summary = _summary(("2026-10-10", 2), ("2026-10-09", 1))
    banners = build_archive_banners(summary, "day", today=TODAY)
    windows = [
        _window("2026-10-10", [_row("a"), _row("b")]),
        _window("2026-10-09", [_row("c", day="2026-10-09")]),
    ]

    model = _assemble(banners, windows, open_keys={"day:2026-10-10"})

    assert [(i.kind, i.key) for i in model.items] == [
        (ITEM_BANNER, "banner:day:2026-10-10"),
        (ITEM_ROW, "u.m@a"),
        (ITEM_ROW, "u.m@b"),
        (ITEM_BANNER, "banner:day:2026-10-09"),
    ]
    assert model.items[0].open and model.items[0].count == 2
    assert not model.items[3].open
    assert len(set(model.index)) == len(model.items)  # type: ignore[arg-type]
    assert model.selectable_keys() == tuple(i.key for i in model.items)


def test_page_boundary_shows_exact_tail_and_next_page_removes_it() -> None:
    rows = [_row(f"r{index:03d}") for index in range(101)]
    summary = _summary(("2026-10-10", 101))
    banners = build_archive_banners(summary, "day", today=TODAY)
    first = _assemble(banners, [_window("2026-10-10", rows[:100], 101)])

    assert [i.kind for i in first.items].count(ITEM_ROW) == 100
    tail = first.items[-1]
    assert tail.kind == ITEM_TAIL and tail.remaining == 1
    assert tail.key == "tail:day:2026-10-10"

    second = _assemble(
        banners,
        [_window("2026-10-10", rows, 101)],
        pages={"day:2026-10-10": 2},
    )

    assert [i.kind for i in second.items].count(ITEM_ROW) == 101
    assert second.items[-1].kind == ITEM_ROW


def test_tail_counts_visible_rows_not_roots_when_a_container_is_expanded() -> None:
    summary = _summary(("2026-10-10", 2))  # two roots: the clan and a solo run
    banners = build_archive_banners(summary, "day", today=TODAY)
    container = _container("clan:x:1", 2)
    members = [
        _row("m1", container_key="clan:x:1"),
        _row("m2", container_key="clan:x:1"),
    ]
    rows = [container, *members, _row("solo")]

    collapsed = _assemble(banners, [_window("2026-10-10", [container, _row("solo")])])
    assert [i.kind for i in collapsed.items] == [
        ITEM_BANNER,
        ITEM_CONTAINER,
        ITEM_ROW,
    ]
    assert collapsed.items[1].count == 2 and not collapsed.items[1].expanded

    expanded = _assemble(
        banners,
        [_window("2026-10-10", rows, 4)],
        expanded=("clan:x:1",),
    )
    assert [i.kind for i in expanded.items] == [
        ITEM_BANNER,
        ITEM_CONTAINER,
        ITEM_MEMBER,
        ITEM_MEMBER,
        ITEM_ROW,
    ]
    assert expanded.items[2].member_of == "clan:x:1"
    assert expanded.items[1].expanded


def test_expanded_members_count_toward_the_page_and_the_remaining_tail() -> None:
    roots = 100
    summary = _summary(("2026-10-10", roots))
    banners = build_archive_banners(summary, "day", today=TODAY)
    container = _container("clan:x:1", 3)
    members = [_row(f"m{i}", container_key="clan:x:1") for i in range(3)]
    singles = [_row(f"s{i:03d}") for i in range(roots - 1)]
    # 100 roots flatten to 103 rows once the container is expanded.
    flattened = [container, *members, *singles]
    window = ArchiveLoadedWindow("2026-10-10", 0, 100, tuple(flattened[:100]), 103)

    model = _assemble(banners, [window], expanded=("clan:x:1",))

    visible = [
        i for i in model.items if i.kind in {ITEM_ROW, ITEM_MEMBER, ITEM_CONTAINER}
    ]
    assert len(visible) == 100
    assert model.items[-1].kind == ITEM_TAIL
    assert model.items[-1].remaining == 3


def test_expanded_container_without_loaded_members_shows_loading_row() -> None:
    summary = _summary(("2026-10-10", 1))
    banners = build_archive_banners(summary, "day", today=TODAY)

    model = _assemble(
        banners,
        [_window("2026-10-10", [_container("clan:x:1", 2)])],
        expanded=("clan:x:1",),
        applied=(),
    )

    assert [i.kind for i in model.items] == [ITEM_BANNER, ITEM_CONTAINER, ITEM_LOADING]
    assert not model.items[2].selectable

    # Collapsed again while stale member rows are still loaded: hide them.
    members = [_row("m1", container_key="clan:x:1")]
    hidden = _assemble(
        banners,
        [_window("2026-10-10", [_container("clan:x:1", 1), *members])],
        expanded=(),
        applied=("clan:x:1",),
    )
    assert [i.kind for i in hidden.items] == [ITEM_BANNER, ITEM_CONTAINER]


def test_open_banner_without_loaded_window_shows_loading_not_empty() -> None:
    summary = _summary(("2026-10-10", 4))
    banners = build_archive_banners(summary, "day", today=TODAY)

    model = _assemble(banners, [])

    assert [i.kind for i in model.items] == [ITEM_BANNER, ITEM_LOADING]
    assert model.selectable_keys() == ("banner:day:2026-10-10",)


def test_status_messages_never_claim_a_complete_empty_result() -> None:
    missing = _assemble(
        (),
        [],
        status=ARCHIVE_CORPUS_MISSING,
        summary_known=False,
        error=ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    )
    assert [i.label for i in missing.items] == [ARCHIVE_INDEX_UNAVAILABLE_MESSAGE]
    assert not missing.selectable_keys()

    unreadable = _assemble(
        (), [], status=ARCHIVE_CORPUS_UNREADABLE, summary_known=False
    )
    assert unreadable.items[0].label == ARCHIVE_INDEX_UNAVAILABLE_MESSAGE

    rebuilding = _assemble((), [], status=ARCHIVE_CORPUS_REBUILDING, indexed_rows=7)
    assert [i.label for i in rebuilding.items] == [
        "Archive index rebuilding — 7 runs indexed so far",
        "No matches yet — the index is still rebuilding.",
    ]

    complete_empty = _assemble((), [])
    assert [i.label for i in complete_empty.items] == [
        "No archived runs match this query."
    ]
    assert all(i.kind == ITEM_MESSAGE for i in complete_empty.items)

    loading = _assemble((), [], summary_known=False, loading=True)
    assert [i.label for i in loading.items] == ["Loading Archive…"]


def test_rebuilding_index_still_lists_indexed_rows_under_a_progress_note() -> None:
    summary = _summary(("2026-10-10", 1))
    banners = build_archive_banners(summary, "day", today=TODAY)

    model = _assemble(
        banners,
        [_window("2026-10-10", [_row("a")])],
        status=ARCHIVE_CORPUS_REBUILDING,
        indexed_rows=1,
    )

    assert [i.kind for i in model.items] == [ITEM_MESSAGE, ITEM_BANNER, ITEM_ROW]
    assert model.selectable_keys() == ("banner:day:2026-10-10", "u.m@a")


# --- cursor helpers ---------------------------------------------------------


def _small_model() -> ArchiveListModel:
    summary = _summary(("2026-10-10", 2), ("2026-10-09", 1))
    banners = build_archive_banners(summary, "day", today=TODAY)
    windows = [
        _window("2026-10-10", [_row("a"), _row("b")]),
        _window("2026-10-09", [_row("c", day="2026-10-09")]),
    ]
    return _assemble(banners, windows)


def test_neighbor_and_edge_keys_clamp_without_wrapping() -> None:
    model = _small_model()
    keys = model.selectable_keys()

    assert neighbor_key(model, keys[0], 1) == keys[1]
    assert neighbor_key(model, keys[-1], 1) == keys[-1]
    assert neighbor_key(model, keys[0], -1) == keys[0]
    assert neighbor_key(model, "gone", 1) == keys[0]
    assert neighbor_key(model, "gone", -1) == keys[-1]
    assert neighbor_key(model, None, 1) == keys[0]
    assert edge_key(model, last=False) == keys[0]
    assert edge_key(model, last=True) == keys[-1]
    assert neighbor_key(ArchiveListModel(), None, 1) is None
    assert edge_key(ArchiveListModel(), last=True) is None


def test_parent_banner_and_fallback_cursor_after_a_rebuild() -> None:
    model = _small_model()

    assert parent_banner_key(model, "u.m@b") == "banner:day:2026-10-10"
    assert parent_banner_key(model, "banner:day:2026-10-10") is None
    assert parent_banner_key(model, "missing") is None

    summary = _summary(("2026-10-10", 2), ("2026-10-09", 1))
    banners = build_archive_banners(summary, "day", today=TODAY)
    rebuilt = _assemble(
        banners,
        [
            _window("2026-10-10", [_row("a")]),
            _window("2026-10-09", [_row("c", day="2026-10-09")]),
        ],
    )

    assert fallback_cursor(model, "u.m@a", rebuilt) == "u.m@a"
    # b vanished: the next surviving neighbor wins, else the previous one.
    assert fallback_cursor(model, "u.m@b", rebuilt) == "banner:day:2026-10-09"
    assert fallback_cursor(model, "unknown", rebuilt) == "banner:day:2026-10-10"
    assert fallback_cursor(model, "u.m@a", ArchiveListModel()) is None


def test_failed_summary_never_paints_a_silent_blank_list() -> None:
    model = _assemble((), [], summary_known=False)
    assert [i.label for i in model.items] == ["Archive results unavailable"]
    assert not model.selectable_keys()
