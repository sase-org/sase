"""Unit tests for the pager history word-diff builder."""

from __future__ import annotations

from sase.pager.document import PagerSection
from sase.pager.history.diff import (
    FOLD_TARGET_KIND,
    FOLD_TOKEN,
    build_diff_body,
    diff_endpoints,
    _fold_label_text,
    _frontmatter_block,
    read_view_change_lines,
    _render_word_line,
    unified_diff_for_comparison,
)


def _comparison(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "frontmatter": {"entries": [], "type_change": None},
        "word_ops": [],
        "hunks": [],
        "removal_anchors": [],
        "stats": {},
        "unified_diff": "",
    }
    base.update(overrides)
    return base


def _changed_line_ops() -> list[dict[str, object]]:
    return [
        {"kind": "equal", "text": "agents ", "start": 0, "end": 7},
        {"kind": "delete", "text": "shells", "start": 7, "end": 7},
        {"kind": "insert", "text": "processes", "start": 7, "end": 16},
    ]


def _body(total: int = 30, changed: int = 16, new_word: str = "processes") -> str:
    lines = [f"unchanged filler line {index}" for index in range(1, total + 1)]
    lines[changed - 1] = f"agents {new_word}"
    return "\n".join(lines) + "\n"


def _changed_comparison() -> dict[str, object]:
    return _comparison(
        word_ops=[{"target_line": 16, "ops": _changed_line_ops()}],
        hunks=[{"target_start": 16, "target_end": 17}],
        stats={"words_added": 1, "words_removed": 1},
        unified_diff="@@ -16 +16 @@\n-agents shells\n+agents processes\n",
    )


def test_word_line_keeps_spacing_and_styles_inserts_deletes() -> None:
    rendered = _render_word_line(_changed_line_ops(), "agents processes")
    assert rendered.plain == "agents shellsprocesses"
    insert_spans = [
        (start, end)
        for start, end, style in _spans(rendered)
        if style is not None and "green" in str(style)
    ]
    delete_spans = [
        (start, end)
        for start, end, style in _spans(rendered)
        if style is not None and "red" in str(style)
    ]
    assert insert_spans, "inserted word keeps the success style"
    assert delete_spans, "deleted word keeps the struck error style"


def _spans(rendered):  # type: ignore[no-untyped-def]
    spans = []
    for span in rendered.spans:
        spans.append((span.start, span.end, span.style))
    return spans


def test_frontmatter_semantic_block() -> None:
    promoted = _frontmatter_block(
        _comparison(frontmatter={"type_change": "promoted", "entries": []})
    )
    assert "⇧ type: reference → core" in promoted.plain
    assert "loaded by every agent" in promoted.plain
    demoted = _frontmatter_block(
        _comparison(frontmatter={"type_change": "demoted", "entries": []})
    )
    assert "⇩ type: core → reference" in demoted.plain
    entries = _frontmatter_block(
        _comparison(
            frontmatter={
                "type_change": None,
                "entries": [{"key": "type", "before": "short", "after": "core"}],
            }
        )
    )
    assert "▣ type: short → core" in entries.plain
    assert _frontmatter_block(_comparison()).plain == ""
    assert _frontmatter_block(None).plain == ""


def test_long_unchanged_runs_fold_with_jump_targets() -> None:
    rendered = build_diff_body(_changed_comparison(), _body())
    assert not rendered.empty
    assert "unchanged line" in rendered.text.plain
    assert FOLD_TOKEN in rendered.text.plain
    assert len(rendered.folds) == 2
    assert rendered.folds[0].hidden_count > 3
    assert len(rendered.fold_targets) == 2
    plain = rendered.text.plain
    for target in rendered.fold_targets:
        assert target.kind == FOLD_TARGET_KIND
        assert plain[target.start : target.end] == FOLD_TOKEN
    # Targets validate inside a real section (offsets sorted, in range).
    section = PagerSection(
        identity="history:note:v2",
        title="note.md",
        kind="file",
        body=rendered.text,
        targets=rendered.fold_targets,
    )
    assert section.plain_text == plain
    # Context lines stay visible around the change.
    assert "agents " in plain
    body_lines = plain.splitlines()
    assert "unchanged filler line 1" not in body_lines
    assert "unchanged filler line 13" in body_lines


def test_expanded_folds_render_in_full() -> None:
    folded = build_diff_body(_changed_comparison(), _body())
    expanded = build_diff_body(
        _changed_comparison(), _body(), expanded=frozenset({0, 1})
    )
    assert not expanded.folds
    assert not expanded.fold_targets
    assert "filler line 1" in expanded.text.plain
    assert len(expanded.text.plain) > len(folded.text.plain)


def test_change_lines_are_sorted_diff_body_lines() -> None:
    rendered = build_diff_body(_changed_comparison(), _body())
    assert rendered.change_lines == tuple(sorted(rendered.change_lines))
    total = len(rendered.text.plain.splitlines())
    assert all(1 <= line <= total for line in rendered.change_lines)
    assert len(rendered.change_lines) >= 1


def test_removal_anchor_renders_marker_row() -> None:
    comparison = _comparison(
        word_ops=[{"target_line": 5, "ops": _changed_line_ops()}],
        hunks=[{"target_start": 5, "target_end": 6}],
        removal_anchors=[{"after_target_line": 5, "removed_count": 2}],
    )
    rendered = build_diff_body(comparison, _body(total=12, changed=5))
    assert "╴ 2 lines removed" in rendered.text.plain


def test_section_path_headers_render() -> None:
    comparison = _comparison(
        word_ops=[{"target_line": 2, "ops": _changed_line_ops()}],
        hunks=[
            {
                "target_start": 2,
                "target_end": 3,
                "section_path": ["Default Keymap Config"],
            }
        ],
    )
    rendered = build_diff_body(comparison, _body(total=8, changed=2))
    assert "§ Default Keymap Config" in rendered.text.plain


def test_unified_fallback_and_empty_states() -> None:
    unified = build_diff_body(
        _comparison(unified_diff="@@ -1 +1 @@\n-old\n+new\n"), "new\n"
    )
    assert unified.empty
    assert "-old" in unified.text.plain
    assert unified.unified_diff.startswith("@@")
    assert unified_diff_for_comparison({"unified_diff": "@@ -1 +1 @@\n"}).startswith(
        "@@"
    )
    assert unified_diff_for_comparison(None) == ""
    bare = build_diff_body(_comparison(), "same\n")
    assert bare.empty
    assert "(no changes)" in bare.text.plain


def test_read_view_change_lines_cover_marks_ops_and_anchors() -> None:
    comparison = _comparison(
        line_marks=[2],
        word_ops=[{"target_line": 3, "ops": [{"kind": "delete"}]}],
        removal_anchors=[{"after_target_line": 5, "removed_count": 1}],
    )
    assert read_view_change_lines(comparison) == (2, 3, 6)
    assert read_view_change_lines(None) == ()
    assert read_view_change_lines({}) == ()


def test_diff_endpoints_cover_bases_and_now() -> None:
    assert diff_endpoints(ordinal=5, visible_ordinals=(1, 2, 3, 4, 5)) == (4, 5)
    assert diff_endpoints(ordinal=1, visible_ordinals=(1,)) == (0, 1)
    assert diff_endpoints(ordinal=5, visible_ordinals=(1, 5), compare_base=2) == (2, 5)
    assert diff_endpoints(ordinal=0, visible_ordinals=(1, 2, 3), dirty=True) == (3, 0)
    assert diff_endpoints(ordinal=0, visible_ordinals=(1, 2, 3)) == (2, 3)
    assert diff_endpoints(ordinal=0, visible_ordinals=()) is None


def test_fold_label_singular() -> None:
    assert _fold_label_text(1) == f"┄┄ 1 unchanged line · {FOLD_TOKEN} ┄┄"
    assert "2 unchanged lines" in _fold_label_text(2)
