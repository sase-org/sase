"""Identity-phase tests: one VersionMoment every surface reads.

Pure unit tests over timeline wire dicts: every moment kind, now ≡ vN
true/false/missing-OID cases, hidden newest versions, a single-version
subject, a tombstone, dirty work with staged edits, step tables for
every intent from every position, diff endpoints including explicit
(non-parent) bases, canonicalization, boundary notices, and the
once-per-state moment cache.
"""

from __future__ import annotations

from sase.pager._chrome import subject_line
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import (
    SectionTimeState,
    committed_pin_for_ordinal,
    live_pin_for_subject,
)
from sase.pager.history.moment import (
    build_moment,
    boundary_notice,
    canonical_ordinal,
    moment_for_state,
    step_target,
)

SUBJECT = "note:project:demo/note"
PATH = "sase/memory/note.md"
NOW = 1790000000


def _committed(
    ordinal: int,
    *,
    blob: str | None = None,
    class_name: str = "authored",
    hidden: bool = False,
    path: str = PATH,
    subject: str | None = None,
    time: int = NOW - 30 * 86400,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "blob_oid": blob if blob is not None else f"blob-{ordinal:036d}",
        "committer_time": time,
        "class": class_name,
        "path": path,
        "provenance": {
            "subject": subject if subject is not None else f"change {ordinal}"
        },
    }
    if hidden:
        row["hidden_by_default"] = True
    return row


def _pseudo(class_name: str) -> dict[str, object]:
    return {"ordinal": 0, "class": class_name}


def _meta(
    *,
    worktree: str | None = "WT",
    head: str | None = "HD",
    path: str = PATH,
) -> dict[str, object]:
    return {"worktree_oid": worktree, "head_oid": head, "path": path}


def _three_clean() -> tuple[list[dict[str, object]], dict[str, object]]:
    rows = [_committed(1), _committed(2), _committed(3)]
    return rows, _meta(worktree="WT", head="WT2")


def _three_d3() -> tuple[list[dict[str, object]], dict[str, object]]:
    newest_blob = "blob-newest"
    rows = [_committed(1), _committed(2), _committed(3, blob=newest_blob)]
    return rows, _meta(worktree=newest_blob, head=newest_blob)


def test_loading_without_rows() -> None:
    moment = build_moment(rows=(), meta=_meta(), visible_ordinals=())
    assert moment.kind == "loading"
    assert moment.newest == 0
    assert moment.ordinal == 0
    assert moment.diff is None
    assert moment.older is moment.newer is moment.first is moment.to_now is None
    assert step_target(moment, "older") is None
    assert step_target(moment, "now") is None


def test_clean_now_is_newest_version() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows, meta=meta, visible_ordinals=(1, 2, 3), pin=None, status="live"
    )
    assert moment.kind == "now"
    assert moment.ordinal == 3
    assert moment.newest == 3
    assert moment.now_matches_newest is True
    assert moment.newer_count == 0
    # The first `(` skips the byte-identical newest copy.
    assert moment.older == 2
    assert moment.newer is None
    assert moment.first == 1
    assert moment.to_now is None
    assert step_target(moment, "older") == 2
    assert step_target(moment, "newer") is None
    assert boundary_notice(moment, "newer") == "Already at now (≡ v3)."


def test_clean_now_detached_without_matching_oids() -> None:
    rows, meta = _three_clean()
    moment = build_moment(
        rows=rows, meta=meta, visible_ordinals=(1, 2, 3), pin=None, status="live"
    )
    assert moment.kind == "now"
    assert moment.now_matches_newest is False
    assert moment.ordinal == 0
    # Now and vN are separate stops: `(` lands on vN itself.
    assert step_target(moment, "older") == 3
    assert boundary_notice(moment, "newer") == "Already at now."


def test_missing_oids_fall_back_to_separate_stops() -> None:
    rows = [_committed(1), _committed(2)]
    for meta in (
        _meta(worktree=None, head=None),
        _meta(worktree="same", head=None),
        _meta(worktree="same", head="same"),
    ):
        # The last meta lacks the newest row's blob match only when the
        # row blob differs; here worktree == head but neither equals the
        # row blob, so now stays detached.
        moment = build_moment(
            rows=rows, meta=meta, visible_ordinals=(1, 2), pin=None, status="live"
        )
        assert moment.now_matches_newest is False
        assert step_target(moment, "older") == 2


def test_differing_oids_fall_back_to_separate_stops() -> None:
    rows, meta = _three_clean()
    moment = build_moment(
        rows=rows, meta=meta, visible_ordinals=(1, 2, 3), pin=None, status="live"
    )
    assert moment.now_matches_newest is False
    assert canonical_ordinal(3, moment) == 3


def test_hidden_newest_versions_skip_but_count() -> None:
    newest_blob = "blob-hidden-newest"
    rows = [
        _committed(1),
        _committed(2),
        _committed(3),
        _committed(4, blob=newest_blob, class_name="reflow", hidden=True),
    ]
    meta = _meta(worktree=newest_blob, head=newest_blob)
    moment = build_moment(
        rows=rows, meta=meta, visible_ordinals=(1, 2, 3), pin=None, status="live"
    )
    assert moment.kind == "now"
    assert moment.newest == 4
    assert moment.ordinal == 4
    assert moment.now_matches_newest is True
    assert step_target(moment, "older") == 3
    assert moment.first == 1


def test_single_version_subject() -> None:
    rows = [_committed(1, blob="only")]
    meta = _meta(worktree="only", head="only")
    moment = build_moment(
        rows=rows, meta=meta, visible_ordinals=(1,), pin=None, status="live"
    )
    assert moment.kind == "now"
    assert moment.ordinal == 1
    assert step_target(moment, "older") is None
    assert step_target(moment, "first") is None
    assert boundary_notice(moment, "older") == "now ≡ v1 is the only version."


def test_tombstone_subject() -> None:
    rows = [_committed(1), _committed(2, class_name="deleted")]
    moment = build_moment(
        rows=rows,
        meta=_meta(),
        visible_ordinals=(1, 2),
        pin=committed_pin_for_ordinal(SUBJECT, 2),
        status="tombstone",
    )
    assert moment.kind == "deleted"
    assert moment.ordinal == 2
    assert moment.to_now == 2
    assert moment.newer is None
    assert moment.older == 1
    assert step_target(moment, "older") == 1
    assert step_target(moment, "now") is None
    assert boundary_notice(moment, "now") == "Already at v2, the deletion."


def test_tombstone_detected_from_row_class() -> None:
    rows = [_committed(1), _committed(2, class_name="deleted")]
    moment = build_moment(
        rows=rows,
        meta=_meta(),
        visible_ordinals=(1, 2),
        pin=committed_pin_for_ordinal(SUBJECT, 2),
        status="live",
    )
    assert moment.kind == "deleted"


def test_now_dirty_from_status() -> None:
    rows, meta = _three_clean()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=live_pin_for_subject(SUBJECT),
        status="dirty-now",
    )
    assert moment.kind == "now_dirty"
    assert moment.ordinal == 0
    # `(` lands on HEAD, the newest visible version.
    assert step_target(moment, "older") == 3
    assert step_target(moment, "newer") is None


def test_now_dirty_from_uncommitted_row() -> None:
    rows = [_pseudo("uncommitted"), _committed(1), _committed(2)]
    moment = build_moment(
        rows=rows,
        meta=_meta(worktree="dirty", head="blob-2"),
        visible_ordinals=(1, 2),
        pin=None,
        status="live",
    )
    assert moment.kind == "now_dirty"
    assert step_target(moment, "older") == 2


def test_now_dirty_with_staged_edits() -> None:
    rows = [_pseudo("staged"), _committed(1)]
    moment = build_moment(
        rows=rows,
        meta=_meta(worktree="staged-wt", head="blob-1"),
        visible_ordinals=(1,),
        pin=None,
        status="live",
    )
    assert moment.kind == "now_dirty"


def test_past_version_details() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=committed_pin_for_ordinal(SUBJECT, 2),
        status="live",
    )
    assert moment.kind == "past"
    assert moment.ordinal == 2
    assert moment.newer_count == 1
    assert moment.commit == f"{2:040d}"
    assert moment.commit_subject == "change 2"
    assert moment.committed_time == NOW - 30 * 86400
    assert moment.path_at_version is None
    assert step_target(moment, "older") == 1
    # The newest stop is now itself on a now ≡ vN subject.
    assert step_target(moment, "newer") == 0
    assert step_target(moment, "now") == 0
    assert step_target(moment, "first") == 1


def test_past_newest_without_match_returns_newest() -> None:
    rows, meta = _three_clean()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2),
        pin=committed_pin_for_ordinal(SUBJECT, 2),
        status="live",
    )
    # v3 exists but is hidden: `)` still names it as the next stop.
    assert step_target(moment, "newer") == 3


def test_past_oldest_is_a_boundary() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=committed_pin_for_ordinal(SUBJECT, 1),
        status="live",
    )
    assert step_target(moment, "older") is None
    assert step_target(moment, "first") is None
    assert step_target(moment, "newer") == 2
    assert boundary_notice(moment, "older") == "Already at v1, the oldest version."


def test_hidden_middle_versions_are_skipped() -> None:
    rows = [
        _committed(1),
        _committed(2),
        _committed(3, class_name="moved", hidden=True),
        _committed(4),
    ]
    moment = build_moment(
        rows=rows,
        meta=_meta(worktree="else", head="else2"),
        visible_ordinals=(1, 2, 4),
        pin=committed_pin_for_ordinal(SUBJECT, 4),
        status="live",
    )
    assert step_target(moment, "older") == 2
    assert step_target(moment, "newer") == 0


def test_step_table_from_every_position() -> None:
    rows, meta = _three_d3()
    visible = (1, 2, 3)
    table = {
        # position: {intent: destination}
        0: {"older": 2, "newer": None, "first": 1, "now": None},
        2: {"older": 1, "newer": 0, "first": 1, "now": 0},
        1: {"older": None, "newer": 2, "first": None, "now": 0},
    }
    for position, intents in table.items():
        pin = (
            live_pin_for_subject(SUBJECT)
            if position == 0
            else committed_pin_for_ordinal(SUBJECT, position)
        )
        moment = build_moment(
            rows=rows,
            meta=meta,
            visible_ordinals=visible,
            pin=pin,
            status="live",
        )
        for intent, expected in intents.items():
            assert step_target(moment, intent) == expected, (position, intent)


def test_pin_to_newest_canonicalizes_to_now() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=committed_pin_for_ordinal(SUBJECT, 3),
        status="live",
    )
    # The model itself reads a stale vN pin as now on a D3 subject.
    assert moment.kind == "now"
    assert canonical_ordinal(3, moment) == 0
    assert canonical_ordinal(2, moment) == 2


def test_diff_endpoints_for_versions() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=committed_pin_for_ordinal(SUBJECT, 2, view="diff"),
        status="live",
    )
    assert moment.view == "diff"
    assert moment.diff == (1, 2)


def test_diff_endpoints_for_oldest_use_empty_base() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=committed_pin_for_ordinal(SUBJECT, 1, view="diff"),
        status="live",
    )
    assert moment.diff == (0, 1)


def test_diff_endpoints_for_clean_now_show_latest_change() -> None:
    rows, meta = _three_d3()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=live_pin_for_subject(SUBJECT),
        status="live",
    )
    assert moment.diff is None
    now_diff = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=_live_diff_pin(),
        status="live",
    )
    assert now_diff.diff == (2, 3)


def _live_diff_pin():  # type: ignore[no-untyped-def]
    from dataclasses import replace

    return replace(live_pin_for_subject(SUBJECT), view="diff")


def test_diff_endpoints_for_dirty_now_target_worktree() -> None:
    rows, meta = _three_clean()
    moment = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=_live_diff_pin(),
        status="dirty-now",
    )
    assert moment.diff == (3, 0)


def test_diff_endpoints_normalize_explicit_bases() -> None:
    rows, meta = _three_clean()
    forward = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=_explicit_diff_pin(ordinal=3, base=1),
        status="live",
    )
    assert forward.diff == (1, 3)
    # A vN pin on a now ≡ vN subject diffs the worktree, not a copy.
    d3_rows, d3_meta = _three_d3()
    d3_forward = build_moment(
        rows=d3_rows,
        meta=d3_meta,
        visible_ordinals=(1, 2, 3),
        pin=_explicit_diff_pin(ordinal=3, base=1),
        status="live",
    )
    assert d3_forward.kind == "now"
    assert d3_forward.diff == (1, 0)
    # A base newer than the target still reads older → newer.
    backward = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=_explicit_diff_pin(ordinal=2, base=3),
        status="live",
    )
    assert backward.diff == (2, 3)
    # A base equal to the target falls back to the parent endpoints.
    same = build_moment(
        rows=rows,
        meta=meta,
        visible_ordinals=(1, 2, 3),
        pin=_explicit_diff_pin(ordinal=2, base=2),
        status="live",
    )
    assert same.diff == (1, 2)


def _explicit_diff_pin(ordinal: int, base: int):  # type: ignore[no-untyped-def]
    from dataclasses import replace

    pin = committed_pin_for_ordinal(SUBJECT, ordinal, view="diff")
    return replace(pin, compare_base=base, explicit_base=True)


def test_path_at_version_set_only_on_rename() -> None:
    rows = [_committed(1), _committed(2, path="sase/memory/renamed.md")]
    moment = build_moment(
        rows=rows,
        meta=_meta(),
        visible_ordinals=(1, 2),
        pin=committed_pin_for_ordinal(SUBJECT, 2),
        status="live",
    )
    assert moment.path_at_version == "sase/memory/renamed.md"


def test_moment_cached_per_state() -> None:
    rows = [_committed(1)]
    state = SectionTimeState(provider_key="k", subject_id=SUBJECT, scope_key="")
    state.timeline = tuple(rows)  # type: ignore[assignment]
    state.timeline_meta = _meta(worktree="WT", head="WT")
    state.visible_ordinals = (1,)
    first = moment_for_state(state)
    second = moment_for_state(state)
    assert first is not None and first is second


def test_moment_rebuilt_when_pin_changes() -> None:
    import sase.pager.history.moment as moment_mod

    rows = [_committed(1, blob="b1"), _committed(2, blob="b2")]
    state = SectionTimeState(provider_key="k", subject_id=SUBJECT, scope_key="")
    state.timeline = tuple(rows)  # type: ignore[assignment]
    state.timeline_meta = _meta(worktree="other", head="other2")
    state.visible_ordinals = (1, 2)
    calls = 0
    real_build = moment_mod.build_moment

    def _counting(**kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_build(**kwargs)

    moment_mod.build_moment = _counting  # type: ignore[method-assign]
    try:
        before = moment_for_state(state)
        assert calls == 1
        assert moment_for_state(state) is before
        assert calls == 1
        state.current_pin = committed_pin_for_ordinal(SUBJECT, 1)
        after = moment_for_state(state)
        assert calls == 2
        assert after is not before
        assert after is not None and after.kind == "past"
    finally:
        moment_mod.build_moment = real_build  # type: ignore[method-assign]


def _document() -> PagerDocument:
    section = PagerSection(identity="a", title="a", kind="file", body="x\n")
    return PagerDocument(sections=(section,), title="doc", origin=PagerOrigin.FILE)


def test_chip_counts_absolute_versions_for_clean_now() -> None:
    line = subject_line(
        _document(),
        _document().sections[0],
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        history_state={"ordinal": 25, "total": 25, "kind": "now"},
    )
    assert "25 versions" in line.plain
    assert "PAST" not in line.plain


def test_chip_names_absolute_version_and_age_for_past() -> None:
    line = subject_line(
        _document(),
        _document().sections[0],
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        history_state={"ordinal": 24, "total": 25, "kind": "past", "age": "1mo"},
    )
    assert "PAST v24/25 · 1mo" in line.plain
