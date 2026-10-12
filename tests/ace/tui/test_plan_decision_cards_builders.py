"""Focused builder tests for Plan Review decision-card styling and wrap."""

from __future__ import annotations

from rich.cells import cell_len
from rich.color import Color
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui.modals.plan_decision_cards import (
    CHANGED_COLOR,
    FOCUS_COLOR,
    _header_line,
    collapsed_card,
    expanded_card,
    render_lines,
)
from sase.sdd._plan_display_decisions import (
    DECISION_DEFAULT_MARK,
    DECISION_SELECTED_MARK,
)

__all__ = [
    "test_mark_is_its_own_segment",
    "test_memory_edits_wrap_instead_of_clipping",
    "test_memory_header_styling_changed",
    "test_memory_header_styling_default",
    "test_non_memory_header_styling_default",
    "test_two_column_default_star_is_dim",
    "test_two_column_why_hanging_indent",
]


def _style_at(text: Text, needle: str) -> Style:
    """Return the combined span style covering the first character of *needle*."""
    idx = text.plain.find(needle)
    assert idx >= 0, (needle, text.plain)
    combined = Style()
    for span in text.spans:
        if span.start <= idx < span.end:
            span_style = span.style
            if not isinstance(span_style, Style):
                span_style = Style.parse(str(span_style))
            combined += span_style
    return combined


def _is_gold(style: Style) -> bool:
    return style.color == Color.parse(CHANGED_COLOR)


def _memory_toggle_row(*, value: bool, changed: bool) -> dict[str, object]:
    return {
        "id": "human_only_record",
        "kind": "toggle",
        "value": value,
        "default": False,
        "changed": changed,
        "ask": "Add a decisions record that remote repository creation is human-only?",
        "memory": {
            "selectors": ["decisions:project-create-human-only"],
            "resolved": [{"type": "strand", "exists": True}],
            "provenance": "not_asked",
        },
    }


def _choice_row(
    *,
    decision_id: str = "dotfiles",
    value: str = "repoint",
    default: str = "repoint",
    changed: bool = False,
) -> dict[str, object]:
    return {
        "id": decision_id,
        "kind": "choice",
        "value": value,
        "default": default,
        "changed": changed,
        "ask": "Should the ~70 stow-style dotfile symlinks into the tree become real files?",
        "why": "a pure rename fixes everything with one verifiable substitution",
        "choices": [
            {
                "key": "repoint",
                "label": "No: keep them as symlinks retargeted into the tree",
            },
            {
                "key": "materialize",
                "label": "Yes: move each linked file into ~ and rewrite its references",
            },
        ],
    }


def _syncthing_root_row() -> dict[str, object]:
    return {
        "id": "root",
        "kind": "choice",
        "value": "db",
        "default": "db",
        "changed": False,
        "ask": "Where should the relocated legacy tree (formerly ~/Sync) live?",
        "why": (
            "~/.profile already calls this root $DB, and a ~/ sibling makes "
            "link retargets one-component swaps"
        ),
        "choices": [
            {
                "key": "db",
                "label": (
                    "~/db: matches the existing $DB/$DBB/$DBH variables in ~/.profile"
                ),
            },
            {
                "key": "legacy",
                "label": (
                    "~/legacy: names it as the pre-chezmoi legacy tree; "
                    "$DB is repointed at it"
                ),
            },
        ],
    }


def test_memory_header_styling_changed() -> None:
    row = _memory_toggle_row(value=True, changed=True)
    header = _header_line(row, 74, current=True, focused=True, read_only=False)
    id_style = _style_at(header, "🧠 human_only_record")
    assert id_style.bold
    assert id_style.color == Color.parse(FOCUS_COLOR)
    left = _style_at(header, "‹")
    assert left.dim
    assert not _is_gold(left)
    yes = _style_at(header, "☑ yes")
    assert not yes.dim
    assert _is_gold(yes)
    check = _style_at(header, "☑")
    assert not check.dim
    assert _is_gold(_style_at(header, "●"))
    right = _style_at(header, "›")
    assert right.dim
    assert not _is_gold(right)


def test_memory_header_styling_default() -> None:
    row = _memory_toggle_row(value=False, changed=False)
    header = _header_line(row, 74, current=True, focused=True, read_only=False)
    star = _style_at(header, DECISION_DEFAULT_MARK)
    assert star.dim
    assert not _is_gold(star)
    value = _style_at(header, "☐ no")
    assert not value.dim
    assert not _is_gold(value)


def test_non_memory_header_styling_default() -> None:
    row = _choice_row()
    header = _header_line(row, 74, current=True, focused=True, read_only=False)
    assert "🧠" not in header.plain
    id_style = _style_at(header, "dotfiles")
    assert id_style.bold
    assert id_style.color == Color.parse(FOCUS_COLOR)
    star = _style_at(header, DECISION_DEFAULT_MARK)
    assert star.dim
    value = _style_at(header, "repoint")
    assert not value.dim
    assert not _is_gold(value)


def test_mark_is_its_own_segment() -> None:
    card = collapsed_card(_choice_row(), None, 76)
    header = card.renderable.renderables[0]
    assert isinstance(header, Text)
    console = Console(color_system="truecolor", force_terminal=True, width=120)
    segments = [seg.text for seg in header.render(console) if seg.text]
    assert not any("repoint" in seg and "★" in seg for seg in segments)
    assert any(seg.strip() == "★" or seg == " ★" for seg in segments)
    padding_runs = [seg for seg in segments if seg.strip() == ""]
    assert padding_runs
    assert all("★" not in seg for seg in padding_runs)


def test_memory_edits_wrap_instead_of_clipping() -> None:
    selectors = [
        "decisions:project-create-human-only",
        "glossary:another-long-strand-name-for-wrapping",
    ]
    row = _memory_toggle_row(value=False, changed=False)
    memory_obj = row["memory"]
    assert isinstance(memory_obj, dict)
    memory = dict(memory_obj)
    memory["selectors"] = selectors
    row["memory"] = memory
    for width in (46, 76, 100):
        card = expanded_card(row, None, width)
        lines = render_lines(card.renderable, width)
        assert lines
        for line in lines:
            assert cell_len(line) <= width, (width, line)
        flat = "".join("".join(line.replace("▌", "").split()) for line in lines)
        for selector in selectors:
            compact = "".join(selector.split())
            assert compact in flat, (width, selector, flat)
            assert flat.count(compact) == 1, (width, selector)


def test_two_column_default_star_is_dim() -> None:
    row = _syncthing_root_row()
    card = expanded_card(row, None, 100, current=True, focused=True)
    option_line = None
    for renderable in card.renderable.renderables:
        if not isinstance(renderable, Text):
            continue
        if (
            DECISION_SELECTED_MARK in renderable.plain
            and DECISION_DEFAULT_MARK in renderable.plain
            and "why" not in renderable.plain
        ):
            option_line = renderable
            break
    assert option_line is not None, "missing two-column default option line"
    star = _style_at(option_line, DECISION_DEFAULT_MARK)
    assert star.dim


def test_two_column_why_hanging_indent() -> None:
    row = _syncthing_root_row()
    why = str(row["why"])
    card = expanded_card(row, None, 100, current=True, focused=True)
    lines = render_lines(card.renderable, 100)
    assert lines
    for line in lines:
        assert cell_len(line) <= 100, line

    def _col(needle: str) -> int:
        match = next((line for line in lines if needle in line), None)
        assert match is not None, (needle, lines)
        return cell_len(match[: match.find(needle)])

    label_col = _col("~/db:")
    assert _col("~/legacy:") == label_col
    why_line = next(
        line for line in lines if "why" in line and "★" in line and "already" in line
    )
    why_text = "~/.profile already"
    assert why_text in why_line
    assert cell_len(why_line[: why_line.find(why_text)]) == label_col
    assert why_line.find("why") < why_line.find(why_text)
    flat = "".join("".join(line.replace("▌", "").split()) for line in lines)
    for word in why.split():
        assert "".join(word.split()) in flat, word
