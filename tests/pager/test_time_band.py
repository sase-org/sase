"""Pure renderer tests for the pager time band (phase `time-band`)."""

from __future__ import annotations

import datetime
from typing import Any

from rich.cells import cell_len

from sase.memory.history import vocabulary as shared_vocabulary
from sase.memory.history import render_text as shared_render_text
from sase.pager import _time_band as time_band
from sase.pager._chrome import subject_line
from sase.pager._labels import build_label_layer, prefix_free_hint_sequence
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.moment import VersionMoment


def _version(
    ordinal: int,
    *,
    class_name: str = "authored",
    volume: int = 4,
    hidden: bool = False,
    commit: str = "",
    bead: str | None = None,
    agent: str | None = None,
    words: tuple[int, int] = (3, 1),
    sections: tuple[str, ...] = (),
    phrase: str | None = None,
    sources: tuple[tuple[str, str], ...] = (),
    config_paths: tuple[str, ...] = (),
    regen_only: bool = False,
    diverged: bool = False,
    aliased: tuple[str, ...] = (),
    committer_time: int = 1_790_510_400,
    path: str = "sase/memory/note.md",
) -> dict[str, Any]:
    sha = commit or (f"{ordinal:040d}".replace("0", "ab")[0:40])
    return {
        "ordinal": ordinal,
        "commit": sha,
        "committer_time": committer_time,
        "class": class_name,
        "hidden": hidden,
        "summary": {
            "section_paths": list(sections),
            "words_added": words[0],
            "words_removed": words[1],
            "frontmatter_phrase": phrase,
            "created_words": 8 if class_name == "created" else None,
            "volume": volume,
        },
        "provenance": {"agent": agent, "bead": bead},
        "cause": {
            "sources": [{"subject_id": subject_id} for subject_id, _ in sources],
            "config_paths": list(config_paths),
            "renderer_paths": [],
            "regen_only": regen_only,
        },
        "diverged": diverged,
        "aliased_paths": list(aliased),
        "path": path,
        "source_path": path,
    }


def _timeline(
    *versions: dict[str, Any],
    state: str = "tracked",
    upstream_ahead: int | None = None,
    health: dict[str, Any] | None = None,
    error: str | None = None,
    is_template: bool = False,
    managed: bool = True,
) -> dict[str, Any]:
    timeline: dict[str, Any] = {
        "subject_id": "note:project:demo/note",
        "state": state,
        "versions": list(versions),
        "managed": managed,
    }
    if upstream_ahead is not None:
        timeline["upstream_ahead"] = upstream_ahead
    if health is not None:
        timeline["health"] = health
    if error is not None:
        timeline["error"] = error
    if is_template:
        timeline["is_template"] = True
    return timeline


_NOW = 1_791_000_000


def _past_data(**overrides: Any) -> time_band.TimeBandData:
    timeline = _timeline(
        _version(
            1,
            class_name="created",
            volume=8,
            committer_time=1_789_905_600,
        ),
        _version(
            2,
            class_name="promoted",
            volume=4,
            phrase="promoted reference → core",
            sections=("Default Keymap Config",),
            bead="sase-1au.5",
            agent="athena",
            commit="1a2b3c4" + "0" * 33,
            committer_time=_NOW - 8 * 86400,
        ),
    )
    data = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=timeline,
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
        **overrides,
    )
    assert data is not None
    return data


def test_glyph_and_hidden_tables_match_shared_vocabulary() -> None:
    assert time_band.CLASS_GLYPHS == shared_vocabulary.CLASS_GLYPHS
    assert set(time_band.HIDDEN_CLASSES) == set(shared_vocabulary.HIDDEN_CLASSES)
    # Every shared class paints its shared glyph in a meaning row, so the
    # pager mirror cannot drift from the CLI vocabulary.
    for class_name, glyph in shared_vocabulary.CLASS_GLYPHS.items():
        timeline = _timeline(
            _version(1, class_name="created", volume=8),
            _version(
                2,
                class_name=class_name,
                volume=4,
                bead="sase-1au.5",
                agent="athena",
                sections=("Section",),
            ),
        )
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=timeline,
            current_ordinal=2,
            now_epoch=_NOW,
            total_visible=2,
        )
        assert data is not None
        row = time_band.render_time_band(data, width=200, rows=1).plain
        assert glyph in row, class_name


def test_format_age_matches_shared_renderer() -> None:
    # The pill context still renders relative ages through the shared
    # vocabulary, so the pager mirror must never drift from the CLI.
    for delta in (3, 90, 7200, 3 * 86400, 60 * 86400, 400 * 86400):
        expected = shared_render_text.format_age(1_000_000 + delta, 1_000_000)
        assert time_band.format_age(1_000_000 + delta, 1_000_000) == expected


def test_short_display_matches_shared_renderer() -> None:
    subjects = [
        "note:project:sase/tui",
        "strand:project:sase/glossary/stitch",
        "instructions:project:sase/.",
        "instructions:project:sase/src/sase/ace",
        "web:project:sase/glossary",
        "asset:project:sase/logo.png",
    ]
    for subject in subjects:
        assert time_band.short_display_for_subject_id(subject) == (
            shared_render_text.short_display_for_subject_id(subject)
        )


def test_sparkline_scales_logarithmically_and_marks_current() -> None:
    rendered = time_band.render_sparkline([0, 100], ["authored", "authored"], None, 2)
    assert (
        rendered.plain == time_band.SPARKLINE_BLOCKS[0] + time_band.SPARKLINE_BLOCKS[-1]
    )
    current = time_band.render_sparkline([1, 100], ["authored", "authored"], 1, 2)
    assert len(current.spans) >= 1
    assert any("reverse" in str(span.style) for span in current.spans)
    hidden = time_band.render_sparkline([5], ["moved"], None, 1)
    assert hidden.plain == time_band.HIDDEN_CELL
    deleted = time_band.render_sparkline([5], ["deleted"], None, 1)
    assert any("red" in str(span.style) for span in deleted.spans)


def test_sparkline_buckets_more_versions_than_cells() -> None:
    rendered = time_band.render_sparkline([1, 2, 3, 4, 5, 6], ["authored"] * 6, 5, 3)
    assert cell_len(rendered.plain) == 3
    assert time_band.render_sparkline([], [], None, 10).plain == ""
    assert time_band.render_sparkline([1], ["authored"], None, 0).plain == ""


def test_chrome_row_budget_matrix() -> None:
    # Hidden time state never takes rows; the trail keeps its own rule.
    assert time_band.chrome_row_budget(40, True, "hidden") == (2, 0)
    assert time_band.chrome_row_budget(40, False, "hidden") == (0, 0)
    assert time_band.chrome_row_budget(40, False, None) == (0, 0)
    # Now is always one row once the band is tall enough to show.
    assert time_band.chrome_row_budget(40, False, "now") == (0, 1)
    assert time_band.chrome_row_budget(50, True, "now") == (2, 1)
    # Past is two rows at full height, one row when constrained.
    assert time_band.chrome_row_budget(50, False, "past") == (0, 2)
    assert time_band.chrome_row_budget(50, True, "past") == (2, 2)
    assert time_band.chrome_row_budget(29, False, "past") == (0, 1)
    assert time_band.chrome_row_budget(39, True, "past") == (2, 1)
    assert time_band.chrome_row_budget(40, True, "past") == (2, 2)
    assert time_band.chrome_row_budget(30, False, "past") == (0, 2)
    # At 12 rows or fewer the band folds into the subject chip.
    for height in (12, 10, 5):
        assert time_band.chrome_row_budget(height, True, "past") == (1, 0)
        assert time_band.chrome_row_budget(height, False, "now") == (0, 0)


def test_honest_states_cover_every_kind() -> None:
    indexing = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=None,
        current_ordinal=0,
        loading=True,
        now_epoch=_NOW,
    )
    assert indexing is not None and indexing.mode == "notice"
    cases = [
        ({"state": "untracked"}, "UNTRACKED"),
        ({"state": "ignored"}, "IGNORED"),
        ({"state": "NO_VCS"}, "NO VCS"),
        ({"state": "tracked", "error": "boom"}, "boom"),
    ]
    for wire, label in cases:
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=dict(wire),
            current_ordinal=0,
            now_epoch=_NOW,
        )
        assert data is not None and data.mode == "notice"
        assert label in time_band.render_time_band(data, width=120, rows=1).plain
    shallow = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(
            _version(1, volume=1),
            health={"shallow": True, "shallow_boundary_time": 0},
        ),
        current_ordinal=0,
        now_epoch=_NOW,
        total_visible=1,
    )
    assert shallow is not None and shallow.honest_kind == "shallow"
    template = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(_version(1, volume=1), is_template=True),
        current_ordinal=0,
        now_epoch=_NOW,
        total_visible=1,
    )
    assert template is not None and template.honest_kind == "template"
    clean = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(_version(1, volume=1)),
        current_ordinal=0,
        now_epoch=_NOW,
        total_visible=1,
    )
    assert clean is not None and clean.honest_kind == "ok"


def test_notice_modes_for_states_without_history() -> None:
    for state, label in (
        ("untracked", "UNTRACKED"),
        ("ignored", "IGNORED"),
        ("NO_VCS", "NO VCS"),
    ):
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=_timeline(state=state),
            current_ordinal=0,
            now_epoch=_NOW,
        )
        assert data is not None and data.mode == "notice"
        rendered = time_band.render_time_band(data, width=120, rows=1)
        assert label in rendered.plain
    indexing = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=None,
        current_ordinal=0,
        loading=True,
        now_epoch=_NOW,
    )
    assert indexing is not None and indexing.mode == "notice"
    assert "indexing" in time_band.render_time_band(indexing, width=120, rows=1).plain


def test_life_strip_shows_scrubber_date_owner_and_dirty() -> None:
    data = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(
            _version(1, volume=8, committer_time=_NOW - 3 * 86400),
            _version(
                2,
                volume=2,
                bead="sase-1bc.12",
                agent="athena",
                committer_time=_NOW - 3 * 86400,
            ),
        ),
        current_ordinal=0,
        dirty=True,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert data is not None and data.mode == "now"
    rendered = time_band.render_time_band(data, width=120, rows=1)
    expected_day = datetime.datetime.fromtimestamp(_NOW - 3 * 86400).strftime(
        "%a %b %d %Y"
    )
    assert "v1" in rendered.plain and "◌ now" in rendered.plain
    assert f"last changed {expected_day}" in rendered.plain
    assert "athena.sase-1bc.12" in rendered.plain
    assert "edits not durable until committed" in rendered.plain
    clean = time_band.render_time_band(
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=_timeline(_version(1, volume=8)),
            current_ordinal=0,
            now_epoch=_NOW,
            total_visible=1,
        ),
        width=120,
        rows=1,
    )
    assert "edits not durable" not in clean.plain
    assert "● now" in clean.plain
    assert "last changed" in clean.plain


def test_past_meaning_row_carries_provenance_targets() -> None:
    data = _past_data()
    assert data.mode == "past"
    targets = time_band.time_band_targets(data)
    assert [target.kind for target in targets] == ["bead", "agent", "commit"]
    assert targets[0].ref == "bead:sase-1au.5"
    assert targets[1].ref == "agent:athena"
    assert targets[2].ref == "commit:1a2b3c4000000000000000000000000000000000"
    rendered = time_band.render_time_band(
        data, width=200, rows=2, hints={0: "a", 1: "b", 2: "c"}
    )
    # Two rows: the timeline row (where and when) first, then the meaning
    # row (what and who) directly above the body it describes.
    first, second = rendered.plain.split("\n")
    assert "v1" in first and "now" in first
    assert "promoted reference → core" in second
    assert "Default Keymap Config" in second
    assert "+3w" in second and "-1w" in second
    assert "sase-1au.5" in second and "athena" in second and "1a2b3c4" in second
    assert "[a]" in second and "[b]" in second and "[c]" in second


def test_two_row_band_keeps_timeline_first_and_meaning_second() -> None:
    data = _past_data()
    rendered = time_band.render_time_band(data, width=200, rows=2)
    first, second = rendered.plain.split("\n")
    # The timeline row carries the scrubber endpoints and the absolute date.
    assert "v1" in first and "● now" in first
    assert "2026" in first
    # The meaning row carries the class summary and provenance.
    assert "sase-1au.5" in second
    # With one row only the meaning row is kept: the pill already carries
    # the identity.
    folded = time_band.render_time_band(data, width=200, rows=1)
    assert "\n" not in folded.plain
    assert "sase-1au.5" in folded.plain


def test_meaning_row_sheds_sha_agent_bead_then_sections() -> None:
    data = _past_data()
    full = time_band.render_time_band(data, width=200, rows=1).plain
    assert "1a2b3c4" in full and "athena" in full and "sase-1au.5" in full
    widths = list(range(200, 39, -10))
    seen: list[str] = []
    for width in widths:
        row = time_band.render_time_band(data, width=width, rows=1).plain
        assert cell_len(row) <= width
        seen.append(row)
    # Shedding drops the SHA before the agent, the agent before the bead,
    # and the bead before the section path as width shrinks.
    pairs = list(zip(widths, seen, strict=True))
    drop_sha = next(w for w, row in pairs if "1a2b3c4" not in row)
    drop_agent = next(w for w, row in pairs if "athena" not in row)
    drop_bead = next(w for w, row in pairs if "sase-1au.5" not in row)
    drop_section = next(w for w, row in pairs if "Default Keymap Config" not in row)
    assert drop_sha > drop_agent > drop_bead > drop_section
    # Shedding the section path keeps the phrase and word delta with no
    # dangling separator.
    section_shed = time_band.render_time_band(data, width=40, rows=1).plain
    assert "Default Keymap Config" not in section_shed
    assert "+3w" in section_shed
    assert not section_shed.rstrip().endswith("·")


def test_timeline_row_markers_and_shedding() -> None:
    versions = [
        _version(
            number,
            volume=(number % 5) + 1,
            committer_time=_NOW - (25 - number) * 86400,
        )
        for number in range(1, 26)
    ]
    timeline = _timeline(*versions, upstream_ahead=2)
    timeline["upstream_branch"] = "origin/master"
    marked = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=timeline,
        current_ordinal=24,
        dirty=True,
        now_epoch=_NOW,
        total_visible=25,
    )
    assert marked is not None
    full_day = datetime.datetime.fromtimestamp(_NOW - 86400).strftime("%a %b %d %Y")
    short_day = datetime.datetime.fromtimestamp(_NOW - 86400).strftime("%b %d %Y")
    wide = time_band.render_time_band(marked, width=200, rows=2).plain.split("\n")[0]
    assert "◌ now" in wide and "⇡2 on origin/master" in wide
    assert "+ uncommitted" in wide
    assert full_day in wide
    # Shedding order at shrinking widths: the ⇡N marker, then ``N newer``,
    # then the weekday and time (the date stays). Every width fits.
    widths = list(range(200, 39, -5))
    rows = [
        time_band.render_time_band(marked, width=width, rows=2).plain.split("\n")[0]
        for width in widths
    ]
    for width, row in zip(widths, rows, strict=True):
        assert cell_len(row) <= width, (width, row)
    pairs = list(zip(widths, rows, strict=True))
    drop_upstream = next(w for w, row in pairs if "⇡2" not in row)
    drop_newer = next(w for w, row in pairs if "uncommitted" not in row)
    drop_weekday = next(
        w for w, row in pairs if full_day not in row and short_day in row
    )
    assert drop_upstream > drop_newer > drop_weekday
    # The date itself stays down to narrow widths.
    narrow = time_band.render_time_band(marked, width=40, rows=2).plain.split("\n")[0]
    assert "2026" in narrow
    assert cell_len(narrow) <= 40


def test_instruction_cause_rows_and_chips() -> None:
    timeline = _timeline(
        _version(1, volume=2),
        _version(
            2,
            class_name="rendered",
            volume=3,
            sources=(
                ("note:project:demo/gotchas", "gotchas"),
                ("note:project:demo/dispatch", "dispatch"),
            ),
            aliased=("CLAUDE.md",),
        ),
    )
    timeline["subject_id"] = "instructions:project:demo/."
    rendered_subject = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=timeline,
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert rendered_subject is not None
    row = time_band.render_time_band(rendered_subject, width=200, rows=1).plain
    assert "rendered" in row and "gotchas" in row and "dispatch" in row
    targets = time_band.time_band_targets(rendered_subject)
    assert [target.kind for target in targets if target.kind == "source"] == [
        "source",
        "source",
    ]
    assert targets[-1].ref == "dispatch"

    config = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=_timeline(
            _version(1, volume=1),
            _version(2, class_name="config", config_paths=["sase/sase.yml"]),
        ),
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert config is not None
    assert (
        "config change" in time_band.render_time_band(config, width=200, rows=1).plain
    )

    regen = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=_timeline(
            _version(1, volume=1),
            _version(2, class_name="regen_only", regen_only=True),
        ),
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert regen is not None
    assert "regenerated" in time_band.render_time_band(regen, width=200, rows=1).plain

    hand = time_band.build_time_band_data(
        subject_id="instructions:project:demo/sub",
        timeline=_timeline(
            _version(1, volume=1), _version(2, class_name="authored"), managed=False
        ),
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert hand is not None
    assert "hand-edited" in time_band.render_time_band(hand, width=200, rows=1).plain

    diverged = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=_timeline(
            _version(1, volume=1), _version(2, class_name="authored", diverged=True)
        ),
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert diverged is not None
    assert (
        time_band.DIVERGED_CHIP
        in time_band.render_time_band(diverged, width=200, rows=1).plain
    )

    aliased = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=_timeline(
            _version(1, volume=1),
            _version(
                2, class_name="authored", aliased=("CLAUDE.md",), path="AGENTS.md"
            ),
        ),
        current_ordinal=2,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert aliased is not None
    row = time_band.render_time_band(aliased, width=200, rows=1).plain
    assert "CLAUDE.md ≡ AGENTS.md" in row


def test_shallow_and_template_annotate_history_rows() -> None:
    shallow = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(
            _version(1, volume=1),
            _version(2, volume=2),
            health={"shallow": True, "shallow_boundary_time": 1_700_000_000},
        ),
        current_ordinal=0,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert shallow is not None and shallow.mode == "now"
    assert "SHALLOW" in time_band.render_time_band(shallow, width=200, rows=1).plain
    template = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=_timeline(_version(1, volume=1), is_template=True),
        current_ordinal=0,
        now_epoch=_NOW,
        total_visible=1,
    )
    assert template is not None
    assert "TEMPLATE" in time_band.render_time_band(template, width=200, rows=1).plain


def test_unknown_ordinal_and_empty_rows_hide() -> None:
    timeline = _timeline(_version(1, volume=1))
    assert (
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=timeline,
            current_ordinal=9,
            now_epoch=_NOW,
        )
        is None
    )
    assert (
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=_timeline(),
            current_ordinal=0,
            now_epoch=_NOW,
        )
        is None
    )


def test_band_hints_lead_the_shared_sequence() -> None:
    section = PagerSection(
        identity="s",
        title="s",
        kind="file",
        body="bead:sase-1dr.7 and bead:sase-1dr.8",
    )
    document = PagerDocument(sections=(section,), title="d", origin=PagerOrigin.BEAD)
    plain = build_label_layer(document, width=80)
    offset = build_label_layer(document, width=80, hint_offset=3)
    sequence = prefix_free_hint_sequence(len(plain.labels) + 3)
    assert sequence[:3] == tuple(
        hint for hint in sequence[:3] if hint not in offset.hint_to_label_index
    )
    assert sorted(offset.hint_to_label_index) == list(sequence[3:])
    assert sorted(plain.hint_to_label_index) == list(sequence[: len(plain.labels)])


def _subject_with_state(history_state: dict[str, object]) -> str:
    section = PagerSection(identity="s", title="s", kind="file", body="x\n")
    document = PagerDocument(sections=(section,), title="d", origin=PagerOrigin.FILE)
    return subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        history_state=history_state,
    ).plain


def test_folded_honest_state_reaches_the_subject_chip() -> None:
    assert "UNTRACKED" in _subject_with_state(
        {"ordinal": 0, "total": 3, "folded_honest": ("untracked", None)}
    )
    assert "PAST" in _subject_with_state({"ordinal": 2, "total": 5, "age": "3d"})


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
        _version(
            ordinal,
            class_name="deleted" if ordinal in deleted else "authored",
            hidden=ordinal in hidden,
            volume=(ordinal % 7) + 1,
            committer_time=start_time + ordinal * step,
        )
        for ordinal in range(1, count + 1)
    ]
    return _timeline(*versions)


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
            now_epoch=_NOW,
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
        _version(
            number,
            class_name="deleted" if tombstone and number == count else "authored",
            volume=number + 1,
            committer_time=_NOW - (count - number) * 86400,
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
        committed_time=_NOW - 86400,
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
        timeline=_timeline(*versions),
        current_ordinal=ordinal,
        dirty=dirty,
        now_epoch=_NOW,
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
