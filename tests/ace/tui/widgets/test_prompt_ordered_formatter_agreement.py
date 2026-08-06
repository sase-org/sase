"""The live ordered-list numbering must agree with the prompt formatter.

`gf` in the prompt pane runs ``format_agent_prompt_markdown`` (Prettier), which
renumbers ordered lists itself. If our live numbering disagreed, formatting
would silently contradict what the editor just did. These tests pin the
agreement in both directions over short, prose-wrap-free fixtures.
"""

from __future__ import annotations

import os
import shutil

import pytest

from sase.ace.tui.widgets._prompt_ordered_editing import _renumber_ordered_runs
from sase.file_references import format_agent_prompt_markdown

pytestmark = pytest.mark.skipif(
    bool(os.environ.get("SASE_DISABLE_PRETTIER")) or shutil.which("prettier") is None,
    reason="prettier is unavailable or disabled",
)


def _renumbered(text: str, anchor_row: int = 0) -> str:
    lines = text.split("\n")
    return "\n".join(_renumber_ordered_runs(lines, (anchor_row,)).lines)


@pytest.mark.parametrize(
    "text",
    [
        "1. one\n2. two\n3. three",
        "1. one\n1. two\n1. three",
        "9. one\n1. two\n1. three",
        "5. one\n6. two\n7. three",
        "9. nine\n10. ten\n11. eleven",
        "1. one\n\n2. two\n\n3. three",
        "1. one\n   1. nested\n   2. nested\n2. two",
        "- bullet\n  1. one\n  2. two",
        "1. one\n\nprose\n\n1. restart\n2. two",
    ],
    ids=[
        "sequential",
        "repeat-style",
        "repeat-style-keeps-first-number",
        "start-preserved",
        "width-change",
        "loose",
        "nested",
        "under-hyphen-parent",
        "prose-split-restart",
    ],
)
def test_our_numbering_is_a_formatter_fixed_point(text: str) -> None:
    """Text the engine considers correct survives formatting unchanged."""
    assert _renumbered(text) == text
    assert format_agent_prompt_markdown(f"{text}\n") == f"{text}\n"


@pytest.mark.parametrize(
    ("text", "anchor_row"),
    [
        ("1. one\n3. two\n7. three", 0),
        ("1. one\n1. two\n5. three", 0),
        ("5. one\n9. two", 0),
        ("9. nine\n2. ten\n5. eleven", 0),
        ("9. nine\n1. ten\n5. eleven", 0),
        ("1. one\n\n4. two\n\n9. three", 0),
        ("1. one\n   1. nested\n   9. nested\n2. two", 1),
    ],
    ids=[
        "sequential-gaps",
        "repeat-style-wins",
        "start-preserved",
        "width-change",
        "repeat-style-keeps-first-number",
        "loose",
        "nested-run",
    ],
)
def test_renumbering_reproduces_the_formatter(text: str, anchor_row: int) -> None:
    """Renumbering a mis-numbered run lands on exactly the formatter's output."""
    formatted = format_agent_prompt_markdown(f"{text}\n")

    assert f"{_renumbered(text, anchor_row)}\n" == formatted
