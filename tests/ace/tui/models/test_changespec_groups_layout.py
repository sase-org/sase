"""Tree shape and key enumeration for ChangeSpec grouping modes."""

from __future__ import annotations

from sase.ace.changespec import TimestampEntry
from sase.ace.tui.models.changespec_groups import (
    ChangeSpecGroupingMode,
    build_changespec_tree,
    enumerate_changespec_group_keys,
)
from sase.ace.tui.models.group_fold import GroupFoldRegistry

from ._changespec_groups_helpers import _NOW, _cs, _group_keys, _kinds


def _ts(timestamp: str) -> TimestampEntry:
    return TimestampEntry(timestamp=timestamp, event_type="STATUS", detail="x")


# --- empty input ---


def test_empty_input_handled() -> None:
    assert build_changespec_tree([], ChangeSpecGroupingMode.BY_PROJECT, now=_NOW) == []


def test_enumerate_keys_empty_for_empty_input() -> None:
    assert enumerate_changespec_group_keys([], ChangeSpecGroupingMode.BY_PROJECT) == []


# --- BY_PROJECT ---


def test_by_project_emits_project_l1_and_sibling_l2_for_grouped_roots() -> None:
    cl = [
        _cs("foobar_1", project="proj"),
        _cs("foobar_2", project="proj"),
        _cs("standalone", project="proj"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_PROJECT, now=_NOW)
    # Project banner, then singleton standalone CS, then sibling-root
    # banner, then the two foobar siblings.
    assert _kinds(entries) == [
        ("group", 0),
        ("changespec", 2),  # standalone (singleton root) renders first
        ("group", 1),
        ("changespec", 0),
        ("changespec", 1),
    ]
    assert _group_keys(entries, 0) == [("proj",)]
    assert _group_keys(entries, 1) == [("proj", "foobar")]


def test_by_project_singleton_root_does_not_emit_l1_banner() -> None:
    cl = [_cs("foobar_1", project="proj"), _cs("baz", project="proj")]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_PROJECT, now=_NOW)
    # No L1 banner — singleton siblings render directly under their project.
    assert _group_keys(entries, 1) == []
    assert ("group", 1) not in _kinds(entries)


def test_by_project_sorts_projects_alphabetically() -> None:
    cl = [
        _cs("a", project="zeta"),
        _cs("b", project="alpha"),
        _cs("c", project="mu"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_PROJECT, now=_NOW)
    assert _group_keys(entries, 0) == [("alpha",), ("mu",), ("zeta",)]


def test_by_project_enumerate_keys_includes_only_grouped_roots_at_l1() -> None:
    cl = [
        _cs("foobar_1", project="proj"),
        _cs("foobar_2", project="proj"),
        _cs("solo", project="proj"),
    ]
    keys = enumerate_changespec_group_keys(cl, ChangeSpecGroupingMode.BY_PROJECT)
    assert ("proj",) in keys
    assert ("proj", "foobar") in keys
    # Singleton root is *not* an enumerable key — no banner is rendered.
    assert ("proj", "solo") not in keys


# --- BY_DATE ---


def test_by_date_emits_l0_banners_in_fixed_bucket_order() -> None:
    cl = [
        _cs("old", timestamps=[_ts("260418_120000")]),
        _cs("today_a", timestamps=[_ts("260426_080000")]),
        _cs("yesterday", timestamps=[_ts("260425_120000")]),
        _cs("today_b", timestamps=[_ts("260426_110000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 0) == [
        ("Today",),
        ("Yesterday",),
        ("Earlier",),
    ]
    assert _group_keys(entries, 1) == [
        ("Today", "11:00"),
        ("Today", "08:00"),
        ("Yesterday", "12:00"),
        ("Earlier", "Apr 13-19"),
    ]
    assert _group_keys(entries, 2) == []


def test_by_date_today_emits_hourly_groups_and_newest_first() -> None:
    cl = [
        _cs("today_early", timestamps=[_ts("260426_080000")]),
        _cs("today_late", timestamps=[_ts("260426_110000")]),
        _cs("today_mid", timestamps=[_ts("260426_100000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 0) == [("Today",)]
    assert _group_keys(entries, 1) == [
        ("Today", "11:00"),
        ("Today", "10:00"),
        ("Today", "08:00"),
    ]
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [1, 2, 0]


def test_by_date_sorts_within_bucket_by_latest_timestamp_desc() -> None:
    cl = [
        _cs("today_early", timestamps=[_ts("260426_080000")]),
        _cs("today_late", timestamps=[_ts("260426_110000")]),
        _cs("today_mid", timestamps=[_ts("260426_100000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [1, 2, 0]


def test_by_date_yesterday_emits_windows_newest_first() -> None:
    cl = [
        _cs("morning_late", timestamps=[_ts("260425_110000")]),
        _cs("evening", timestamps=[_ts("260425_170000")]),
        _cs("morning_early", timestamps=[_ts("260425_090000")]),
        _cs("night", timestamps=[_ts("260425_210000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [
        ("Yesterday", "21:00"),
        ("Yesterday", "17:00"),
        ("Yesterday", "11:00"),
        ("Yesterday", "09:00"),
    ]
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [3, 1, 0, 2]


def test_by_date_this_week_emits_days_newest_first() -> None:
    cl = [
        _cs("wed", timestamps=[_ts("260422_100000")]),
        _cs("fri_early", timestamps=[_ts("260424_090000")]),
        _cs("thu", timestamps=[_ts("260423_100000")]),
        _cs("fri_late", timestamps=[_ts("260424_150000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [
        ("This Week", "Fri Apr 24"),
        ("This Week", "Thu Apr 23"),
        ("This Week", "Wed Apr 22"),
    ]
    assert _group_keys(entries, 2) == []
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [3, 1, 2, 0]


def test_by_date_earlier_emits_weeks_newest_first_then_no_timestamp() -> None:
    cl = [
        _cs("undated", timestamps=None),
        _cs("older", timestamps=[_ts("260401_100000")]),
        _cs("newer_early", timestamps=[_ts("260415_090000")]),
        _cs("newer_late", timestamps=[_ts("260415_160000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [
        ("Earlier", "Apr 13-19"),
        ("Earlier", "Mar 30-Apr 5"),
        ("Earlier", "(no timestamp)"),
    ]
    assert _group_keys(entries, 2) == []
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [3, 2, 1, 0]


def test_by_date_missing_timestamps_lands_in_earlier_after_dated_cls() -> None:
    cl = [
        _cs("undated", timestamps=None),
        _cs("today", timestamps=[_ts("260426_080000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    keys = _group_keys(entries, 0)
    assert keys.index(("Today",)) < keys.index(("Earlier",))


def test_by_date_collapsed_subgroup_hides_only_that_subgroup() -> None:
    cl = [
        _cs("night", timestamps=[_ts("260425_210000")]),
        _cs("afternoon", timestamps=[_ts("260425_140000")]),
    ]
    registry = GroupFoldRegistry()
    registry.collapse(("Yesterday", "21:00"))
    entries = build_changespec_tree(
        cl, ChangeSpecGroupingMode.BY_DATE, fold_registry=registry, now=_NOW
    )
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 1),
        ("changespec", 1),
    ]


def test_by_date_enumerate_keys_includes_l1_subgroup_keys() -> None:
    cl = [
        _cs("today", timestamps=[_ts("260426_100000")]),
        _cs("night", timestamps=[_ts("260425_210000")]),
        _cs("older", timestamps=[_ts("260415_100000")]),
    ]
    keys = enumerate_changespec_group_keys(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert keys == [
        ("Today",),
        ("Today", "10:00"),
        ("Yesterday",),
        ("Yesterday", "21:00"),
        ("Earlier",),
        ("Earlier", "Apr 13-19"),
    ]


def test_by_date_singleton_today_emits_one_hour_subgroup() -> None:
    cl = [_cs("today", timestamps=[_ts("260426_100000")])]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)

    assert _group_keys(entries, 1) == [("Today", "10:00")]
    assert _group_keys(entries, 2) == []
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("changespec", 0),
    ]
    keys = enumerate_changespec_group_keys(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert keys == [("Today",), ("Today", "10:00")]


def test_by_date_two_cls_in_same_hour_share_l1_banner() -> None:
    cl = [
        _cs("morning_late", timestamps=[_ts("260426_113000")]),
        _cs("morning_early", timestamps=[_ts("260426_110500")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)

    assert _group_keys(entries, 1) == [("Today", "11:00")]
    keys = enumerate_changespec_group_keys(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)
    assert ("Today", "11:00") in keys


def test_by_date_two_cls_in_different_hours_emit_two_banners() -> None:
    cl = [
        _cs("afternoon", timestamps=[_ts("260426_140000")]),
        _cs("morning", timestamps=[_ts("260426_090000")]),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_DATE, now=_NOW)

    assert _group_keys(entries, 1) == [
        ("Today", "14:00"),
        ("Today", "09:00"),
    ]
    assert _group_keys(entries, 2) == []


# --- BY_STATUS ---


def test_by_status_l0_banners_in_display_order() -> None:
    cl = [
        _cs("a", status="Submitted"),
        _cs("b", status="WIP"),
        _cs("c", status="Ready"),
        _cs("d", status="Draft"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)
    assert _group_keys(entries, 0) == [
        ("Ready",),
        ("WIP",),
        ("Draft",),
        ("Submitted",),
    ]
    # All names are unique — no sibling-root grouping fires.
    assert _group_keys(entries, 1) == []


def test_by_status_emits_sibling_sub_banner_under_status_bucket() -> None:
    cl = [
        _cs("foobar_1", status="WIP"),
        _cs("foobar_2", status="WIP"),
        _cs("solo", status="WIP"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)
    # Status banner, then singleton ``solo`` first, then sibling-root
    # banner, then the two foobar siblings.
    assert _kinds(entries) == [
        ("group", 0),
        ("changespec", 2),
        ("group", 1),
        ("changespec", 0),
        ("changespec", 1),
    ]
    assert _group_keys(entries, 0) == [("WIP",)]
    assert _group_keys(entries, 1) == [("WIP", "foobar")]


def test_by_status_singleton_root_does_not_emit_l1_banner() -> None:
    cl = [_cs("foobar_1", status="WIP"), _cs("baz", status="WIP")]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)
    assert _group_keys(entries, 1) == []
    assert ("group", 1) not in _kinds(entries)


def test_by_status_sibling_sub_banner_scoped_to_its_bucket() -> None:
    cl = [
        _cs("foobar_1", status="WIP"),
        _cs("foobar_2", status="Mailed"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)
    # Each sibling is alone inside its own status bucket — no L1 banner.
    assert _group_keys(entries, 1) == []


def test_by_status_enumerate_keys_includes_only_grouped_roots_at_l1() -> None:
    cl = [
        _cs("foobar_1", status="WIP"),
        _cs("foobar_2", status="WIP"),
        _cs("solo", status="WIP"),
    ]
    keys = enumerate_changespec_group_keys(cl, ChangeSpecGroupingMode.BY_STATUS)
    assert ("WIP",) in keys
    assert ("WIP", "foobar") in keys
    assert ("WIP", "solo") not in keys


def test_by_status_collapsed_sibling_root_hides_only_its_members() -> None:
    cl = [
        _cs("foobar_1", status="WIP"),
        _cs("foobar_2", status="WIP"),
        _cs("solo", status="WIP"),
    ]
    registry = GroupFoldRegistry()
    registry.collapse(("WIP", "foobar"))
    entries = build_changespec_tree(
        cl, ChangeSpecGroupingMode.BY_STATUS, fold_registry=registry, now=_NOW
    )
    assert _kinds(entries) == [
        ("group", 0),
        ("changespec", 2),
        ("group", 1),
    ]


def test_by_status_keeps_input_order_within_bucket() -> None:
    cl = [
        _cs("first", status="WIP"),
        _cs("second", status="WIP"),
        _cs("third", status="WIP"),
    ]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)
    cs_indices = [e.changespec_idx for e in entries if e.kind == "changespec"]
    assert cs_indices == [0, 1, 2]


def test_by_status_uses_literal_status_for_heading_label() -> None:
    """Suffixed status values create their own bucket but stay in lifecycle slot."""
    cl = [
        _cs("a", status="Ready"),
        _cs("b", status="Ready - (!: REVIEWERS PENDING)"),
        _cs("c", status="Submitted"),
    ]
    keys = _group_keys(
        build_changespec_tree(cl, ChangeSpecGroupingMode.BY_STATUS, now=_NOW), 0
    )
    # Both ``Ready`` variants sort before ``Submitted``; ordering between
    # the two ``Ready*`` variants is deterministic via the alphabetic
    # tiebreak — exact ``Ready`` < ``Ready - ...``.
    assert keys == [
        ("Ready",),
        ("Ready - (!: REVIEWERS PENDING)",),
        ("Submitted",),
    ]


# --- Fold behavior ---


def test_collapsed_group_suppresses_descendants_and_leaves_siblings_alone() -> None:
    cl = [
        _cs("a", project="alpha"),
        _cs("b", project="beta"),
    ]
    registry = GroupFoldRegistry()
    registry.collapse(("alpha",))
    entries = build_changespec_tree(
        cl, ChangeSpecGroupingMode.BY_PROJECT, fold_registry=registry, now=_NOW
    )
    # Both project banners still render, but alpha's CL is hidden.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 0),
        ("changespec", 1),
    ]
    # Order also confirms beta still renders normally.
    keys = _group_keys(entries, 0)
    assert keys == [("alpha",), ("beta",)]


def test_collapsed_sibling_root_hides_only_its_members() -> None:
    cl = [
        _cs("foobar_1", project="proj"),
        _cs("foobar_2", project="proj"),
        _cs("solo", project="proj"),
    ]
    registry = GroupFoldRegistry()
    registry.collapse(("proj", "foobar"))
    entries = build_changespec_tree(
        cl, ChangeSpecGroupingMode.BY_PROJECT, fold_registry=registry, now=_NOW
    )
    # Project banner + singleton + collapsed L1 banner only — no foobar CSes.
    assert _kinds(entries) == [
        ("group", 0),
        ("changespec", 2),
        ("group", 1),
    ]


def test_default_fold_registry_renders_everything_expanded() -> None:
    cl = [_cs("a", project="proj")]
    entries = build_changespec_tree(cl, ChangeSpecGroupingMode.BY_PROJECT, now=_NOW)
    # Project banner + the lone CS visible.
    assert _kinds(entries) == [("group", 0), ("changespec", 0)]
