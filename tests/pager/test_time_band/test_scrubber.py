"""Scrubber and moment views for the pager time band."""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len

from sase.pager import _time_band as time_band
from sase.pager.history.moment import VersionMoment
from tests.pager.test_time_band._fixtures import NOW, make_timeline, make_version


def _scrub_versions(
    count: int,
    *,
    hidden: set[int] | None = None,
    deleted: set[int] | None = None,
    start_time: int = 1_789_905_600,
    step: int = 86400,
) -> dict[str, Any]:
    hidden = hidden or set()
    deleted = deleted or set()
    versions = [
        make_version(
            ordinal,
            class_name="deleted" if ordinal in deleted else "authored",
            hidden=ordinal in hidden,
            volume=(ordinal % 7) + 1,
            committer_time=start_time + ordinal * step,
        )
        for ordinal in range(1, count + 1)
    ]
    return make_timeline(*versions)


def _scrub_lists(data: Any) -> dict[str, list[Any]]:
    return {
        "ordinals": [version.ordinal for version in data.versions],
        "volumes": [version.volume for version in data.versions],
        "hidden": [bool(version.hidden) for version in data.versions],
        "deleted": [version.class_name == "deleted" for version in data.versions],
    }


def test_scrubber_slot_counts_for_every_size() -> None:
    for count in (1, 2, 12, 13, 25, 260):
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=_scrub_versions(count),
            current_ordinal=count // 2 or 1,
            now_epoch=NOW,
            total_visible=count,
        )
        assert data is not None
        scrubber = time_band.render_scrubber(
            **_scrub_lists(data),
            shown_ordinal=data.current.ordinal if data.current else None,
        )
        plain = scrubber.plain
        assert plain.startswith("v1 ")
        assert plain.endswith("● now")
        track = plain.removeprefix("v1 ").removesuffix(" ● now")
        if count <= 12:
            # Two cells per slot: one bar plus one gap.
            assert cell_len(track) == count * 2 - 1
        elif count <= 60:
            assert cell_len(track) == count
        else:
            # Longer histories bucket into the 60-cell track.
            assert cell_len(track) == 60


def test_scrubber_progress_styles_for_every_kind() -> None:
    past = time_band.render_scrubber(
        ordinals=[1, 2, 3],
        volumes=[2, 2, 2],
        hidden=[False, False, False],
        deleted=[False, False, False],
        shown_ordinal=2,
    )
    by_span = {(s.start, s.end): str(s.style) for s in past.spans}
    assert "reverse" in by_span[(5, 6)]
    assert "reverse" not in by_span[(3, 4)]
    assert by_span[(9, 14)] == "dim"

    now = time_band.render_scrubber(
        ordinals=[1, 2],
        volumes=[2, 2],
        hidden=[False, False],
        deleted=[False, False],
        shown_ordinal=None,
    )
    assert "● now" in now.plain
    assert any("reverse" in str(s.style) for s in now.spans)

    dirty = time_band.render_scrubber(
        ordinals=[1, 2],
        volumes=[2, 2],
        hidden=[False, False],
        deleted=[False, False],
        shown_ordinal=None,
        dirty=True,
    )
    assert "◌ now" in dirty.plain

    tombstone = time_band.render_scrubber(
        ordinals=[1, 2, 3],
        volumes=[2, 2, 2],
        hidden=[False, False, False],
        deleted=[False, False, True],
        shown_ordinal=3,
        tombstone=True,
    )
    assert "✖ deleted" in tombstone.plain
    track = tombstone.plain.removeprefix("v1 ").removesuffix(" ✖ deleted")
    assert "✖" in track

    hidden_rendered = time_band.render_scrubber(
        ordinals=[1, 2, 3],
        volumes=[2, 2, 2],
        hidden=[True, False, False],
        deleted=[False, False, False],
        shown_ordinal=3,
    )
    track = hidden_rendered.plain.removeprefix("v1 ").removesuffix(" ● now")
    assert track.split(" ")[0] == "·"


def test_scrubber_diff_ranges_adjacent_and_split() -> None:
    adjacent = time_band.render_scrubber(
        ordinals=[1, 2, 3],
        volumes=[2, 2, 2],
        hidden=[False, False, False],
        deleted=[False, False, False],
        shown_ordinal=None,
        view="diff",
        diff_base=2,
        diff_target=3,
    )
    spans = {(s.start, s.end): str(s.style) for s in adjacent.spans}
    assert "bold red" in spans.values()
    assert any("reverse" in style for style in spans.values())

    split = time_band.render_scrubber(
        ordinals=[1, 2, 3, 4, 5],
        volumes=[2, 2, 2, 2, 2],
        hidden=[False] * 5,
        deleted=[False] * 5,
        shown_ordinal=None,
        view="diff",
        diff_base=2,
        diff_target=4,
    )
    assert split.plain.startswith("v1 ")
    assert "● now" in split.plain

    against_now = time_band.render_scrubber(
        ordinals=[1, 2, 3],
        volumes=[2, 2, 2],
        hidden=[False, False, False],
        deleted=[False, False, False],
        shown_ordinal=None,
        view="diff",
        diff_base=3,
        diff_target=0,
        dirty=True,
    )
    assert "◌ now" in against_now.plain


def _moment_data(
    count: int = 3,
    *,
    kind: str = "past",
    ordinal: int = 2,
    view: str = "read",
    diff: tuple[int, int] | None = None,
    dirty: bool = False,
    tombstone: bool = False,
    subject: str | None = "feat(memory): tend the garden",
    path_at_version: str | None = None,
    agent: str | None = "athena",
) -> Any:
    versions = [
        make_version(
            number,
            class_name="deleted" if tombstone and number == count else "authored",
            volume=number + 1,
            committer_time=NOW - (count - number) * 86400,
            agent=agent,
            bead="sase-1au.5",
        )
        for number in range(1, count + 1)
    ]
    moment = VersionMoment(
        kind=kind,  # type: ignore[arg-type]
        ordinal=ordinal,
        newest=count,
        now_matches_newest=False,
        view=view,  # type: ignore[arg-type]
        diff=diff,
        committed_time=NOW - 86400,
        commit="abc123",
        commit_subject=subject,
        path_at_version=path_at_version,
        newer_count=count - ordinal if kind == "past" else 0,
        older=ordinal - 1 if ordinal > 1 else None,
        newer=ordinal + 1 if ordinal < count else 0,
        first=1,
        to_now=0,
        worktree_dirty=dirty,
    )
    data = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(*versions),
        current_ordinal=ordinal,
        dirty=dirty,
        now_epoch=NOW,
        total_visible=count,
        moment=moment,
    )
    assert data is not None
    return data


def test_model_reads_view_diff_newer_and_subject_from_moment() -> None:
    data = _moment_data(view="diff", diff=(1, 2))
    assert data.view == "diff"
    assert data.diff == (1, 2)
    assert data.newer_count == 1
    assert data.commit_subject == "feat(memory): tend the garden"
    assert data.tombstone is False
    assert data.dirty is False


def test_timeline_row_shows_compared_range_and_endpoints() -> None:
    data = _moment_data(view="diff", diff=(1, 2))
    row = time_band.render_time_band(data, width=200, rows=2).plain.split("\n")[0]
    assert "comparing " in row
    assert "v1" in row and "v2" in row
    assert "→" in row


def test_timeline_row_marks_dirty_diff_against_now() -> None:
    data = _moment_data(
        kind="now_dirty", ordinal=0, view="diff", diff=(3, 0), dirty=True
    )
    assert data.mode == "now"
    # A diff view always renders the timeline row with its comparing text,
    # whatever the kind — never the one-row now strip.
    strip = time_band.render_time_band(data, width=200, rows=1).plain
    assert "comparing" in strip
    assert "v3" in strip and "uncommitted edits" in strip


def test_tombstone_row_replaces_meaning_row() -> None:
    data = _moment_data(kind="deleted", ordinal=3, tombstone=True)
    assert data.tombstone is True
    assert data.mode == "past"
    rendered = time_band.render_time_band(data, width=200, rows=2)
    first, second = rendered.plain.split("\n")
    assert "v1" in first and "✖ deleted" in first
    assert second.startswith("✖ deleted ")
    assert "by athena" in second
    # The body shows the last content before the deletion (v2), not v3.
    assert "showing last content (v2)" in second
    assert "2026" in second
    folded = time_band.render_time_band(data, width=200, rows=1).plain
    assert "showing last content (v2)" in folded


def test_meaning_row_shows_renamed_path() -> None:
    data = _moment_data(path_at_version="sase/memory/old.md")
    assert data.path_at_version == "sase/memory/old.md"
    row = time_band.render_time_band(data, width=200, rows=1).plain
    assert "· as sase/memory/old.md" in row
    plain_data = _moment_data()
    assert (
        "· as " not in time_band.render_time_band(plain_data, width=200, rows=1).plain
    )


def test_band_tint_keeps_body_text_contrast() -> None:
    from sase.pager.history.styles import default_history_styles
    from sase.pager.syntax_theme import contrast_ratio

    styles = default_history_styles()
    assert contrast_ratio(styles.foreground, styles.band_past_tint) >= 4.5
    data = _moment_data()
    rendered = time_band.render_time_band(data, width=120, rows=2, styles=styles)
    assert "v1" in rendered.plain.split("\n")[0]
