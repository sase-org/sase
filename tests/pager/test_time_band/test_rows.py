"""Past/timeline rows for the pager time band: meaning, shedding, causes, folding."""

from __future__ import annotations

import datetime
from typing import Any

from rich.cells import cell_len

from sase.pager import _time_band as time_band
from sase.pager._chrome import subject_line
from sase.pager._labels import build_label_layer, prefix_free_hint_sequence
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from tests.pager.test_time_band._fixtures import NOW, make_timeline, make_version


def _past_data(**overrides: Any) -> time_band.TimeBandData:
    timeline = make_timeline(
        make_version(
            1,
            class_name="created",
            volume=8,
            committer_time=1_789_905_600,
        ),
        make_version(
            2,
            class_name="promoted",
            volume=4,
            phrase="promoted reference → core",
            sections=("Default Keymap Config",),
            bead="sase-1au.5",
            agent="athena",
            commit="1a2b3c4" + "0" * 33,
            committer_time=NOW - 8 * 86400,
        ),
    )
    data = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=timeline,
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
        **overrides,
    )
    assert data is not None
    return data


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
        make_version(
            number,
            volume=(number % 5) + 1,
            committer_time=NOW - (25 - number) * 86400,
        )
        for number in range(1, 26)
    ]
    timeline = make_timeline(*versions, upstream_ahead=2)
    timeline["upstream_branch"] = "origin/master"
    marked = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=timeline,
        current_ordinal=24,
        dirty=True,
        now_epoch=NOW,
        total_visible=25,
    )
    assert marked is not None
    full_day = datetime.datetime.fromtimestamp(NOW - 86400).strftime("%a %b %d %Y")
    short_day = datetime.datetime.fromtimestamp(NOW - 86400).strftime("%b %d %Y")
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
    timeline = make_timeline(
        make_version(1, volume=2),
        make_version(
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
        now_epoch=NOW,
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
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(2, class_name="config", config_paths=["sase/sase.yml"]),
        ),
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
    )
    assert config is not None
    assert (
        "config change" in time_band.render_time_band(config, width=200, rows=1).plain
    )

    regen = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(2, class_name="regen_only", regen_only=True),
        ),
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
    )
    assert regen is not None
    assert "regenerated" in time_band.render_time_band(regen, width=200, rows=1).plain

    hand = time_band.build_time_band_data(
        subject_id="instructions:project:demo/sub",
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(2, class_name="authored"),
            managed=False,
        ),
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
    )
    assert hand is not None
    assert "hand-edited" in time_band.render_time_band(hand, width=200, rows=1).plain

    diverged = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(2, class_name="authored", diverged=True),
        ),
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
    )
    assert diverged is not None
    assert (
        time_band.DIVERGED_CHIP
        in time_band.render_time_band(diverged, width=200, rows=1).plain
    )

    aliased = time_band.build_time_band_data(
        subject_id="instructions:project:demo/.",
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(
                2, class_name="authored", aliased=("CLAUDE.md",), path="AGENTS.md"
            ),
        ),
        current_ordinal=2,
        now_epoch=NOW,
        total_visible=2,
    )
    assert aliased is not None
    row = time_band.render_time_band(aliased, width=200, rows=1).plain
    assert "CLAUDE.md ≡ AGENTS.md" in row


def test_shallow_and_template_annotate_history_rows() -> None:
    shallow = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(
            make_version(1, volume=1),
            make_version(2, volume=2),
            health={"shallow": True, "shallow_boundary_time": 1_700_000_000},
        ),
        current_ordinal=0,
        now_epoch=NOW,
        total_visible=2,
    )
    assert shallow is not None and shallow.mode == "now"
    assert "SHALLOW" in time_band.render_time_band(shallow, width=200, rows=1).plain
    template = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=make_timeline(make_version(1, volume=1), is_template=True),
        current_ordinal=0,
        now_epoch=NOW,
        total_visible=1,
    )
    assert template is not None
    assert "TEMPLATE" in time_band.render_time_band(template, width=200, rows=1).plain


def test_unknown_ordinal_and_empty_rows_hide() -> None:
    timeline = make_timeline(make_version(1, volume=1))
    assert (
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=timeline,
            current_ordinal=9,
            now_epoch=NOW,
        )
        is None
    )
    assert (
        time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=make_timeline(),
            current_ordinal=0,
            now_epoch=NOW,
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
