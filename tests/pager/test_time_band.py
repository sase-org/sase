"""Pure renderer tests for the pager time band (phase `time-band`)."""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len

from sase.memory.history import vocabulary as shared_vocabulary
from sase.memory.history import render_text as shared_render_text
from sase.pager import _time_band as time_band
from sase.pager._chrome import _history_chip
from sase.pager._labels import build_label_layer, prefix_free_hint_sequence
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


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
    for delta in (3, 90, 7200, 3 * 86400, 60 * 86400, 400 * 86400):
        expected = shared_render_text.format_age(1_000_000 + delta, 1_000_000)
        data = time_band.build_time_band_data(
            subject_id="note:project:demo/note",
            timeline=_timeline(
                _version(1, volume=8, committer_time=1_000_000),
            ),
            current_ordinal=0,
            now_epoch=1_000_000 + delta,
            total_visible=1,
        )
        assert data is not None
        strip = time_band.render_time_band(data, width=200, rows=1).plain
        assert f"last changed {expected} ago" in strip


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


def test_life_strip_shows_sparkline_age_owner_and_dirty() -> None:
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
    assert "last changed 3d ago" in rendered.plain
    assert "athena.sase-1bc.12" in rendered.plain
    assert "uncommitted" in rendered.plain
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
    assert "uncommitted" not in clean.plain


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
    first, second = rendered.plain.split("\n")
    assert "promoted reference → core" in first
    assert "Default Keymap Config" in first
    assert "+3w" in first and "-1w" in first
    assert "sase-1au.5" in first and "athena" in first and "1a2b3c4" in first
    assert "[a]" in first and "[b]" in first and "[c]" in first
    assert "→ now" in second


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


def test_time_row_markers_and_shedding() -> None:
    timeline = _timeline(
        _version(1, volume=1),
        _version(2, volume=9, committer_time=_NOW - 86400),
        upstream_ahead=2,
    )
    timeline["upstream_branch"] = "origin/master"
    marked = time_band.build_time_band_data(
        subject_id="note:project:demo/note",
        timeline=timeline,
        current_ordinal=2,
        dirty=True,
        now_epoch=_NOW,
        total_visible=2,
    )
    assert marked is not None
    wide = time_band.render_time_band(marked, width=200, rows=2).plain.split("\n")[1]
    assert "→ now" in wide and "◌" in wide and "⇡2 on origin/master" in wide
    assert "2026" in wide
    narrow = time_band.render_time_band(marked, width=44, rows=2).plain.split("\n")[1]
    # The absolute date sheds before the ⇡N marker.
    assert "2026" not in narrow
    assert "⇡2" in narrow and "→ now" in narrow
    assert cell_len(narrow) <= 44


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


def test_folded_honest_state_reaches_the_subject_chip() -> None:
    chip = _history_chip(
        {"ordinal": 0, "total": 3, "folded_honest": ("untracked", None)}
    )
    assert chip is not None and "UNTRACKED" in chip.plain
    plain = _history_chip({"ordinal": 2, "total": 5, "age": "3d"})
    assert plain is not None and "PAST" in plain.plain
