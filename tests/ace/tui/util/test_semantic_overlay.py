"""Tests for fail-open glossary/repo Rich overlays."""

from __future__ import annotations

from pathlib import Path

from rich.style import Style
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
from sase.ace.tui.util.semantic_overlay import apply_semantic_overlays
from sase.ace.tui.util.semantic_styles import SemanticHighlightStyles
from sase.ace.tui.util.xprompt_syntax import (
    XPROMPT_TOKEN_STYLES,
    highlight_markdown_text,
    highlight_prompt_text,
)
from tests.ace.tui.widgets._prompt_glossary_helpers import (
    catalog_for_text,
    catalog_for_wrapped_text,
)
from tests.ace.tui.widgets._prompt_repo_mention_helpers import (
    catalog_for_text as repo_catalog_for_text,
)

_STYLES = SemanticHighlightStyles(
    glossary=Style(color="#ffaa00", bold=True, underline=True),
    repo=Style(color="#aa88ff", bold=True, underline=True),
)


def _styles_at(text: Text, needle: str, *, offset: int = 0) -> set[str]:
    position = text.plain.index(needle) + offset
    return {
        str(span.style)
        for span in text.spans
        if span.start <= position < span.end and span.style is not None
    }


def test_path_adjacent_repo_mentions_are_rejected(
    tmp_path: Path,
) -> None:
    source = "Open ../sase-core then sase-core"
    highlighted = Text(source)
    apply_semantic_overlays(
        highlighted,
        source,
        repo_catalog=repo_catalog_for_text(
            source,
            tmp_path,
            "sase-core",
            occurrence_count=2,
        ),
        styles=_STYLES,
    )

    adjacent = _styles_at(highlighted, "../sase-core", offset=3)
    standalone = _styles_at(highlighted, "then sase-core", offset=5)
    assert not any("#aa88ff" in style for style in adjacent)
    assert any("#aa88ff" in style for style in standalone)


def test_overlay_marks_glossary_and_repo_roles(
    tmp_path: Path,
) -> None:
    source = "Ask Agent Clan to inspect sase-core"
    highlighted = Text(source)
    apply_semantic_overlays(
        highlighted,
        source,
        glossary_catalog=catalog_for_text(source, tmp_path, "Agent Clan"),
        repo_catalog=repo_catalog_for_text(source, tmp_path, "sase-core"),
        styles=_STYLES,
    )

    glossary = _styles_at(highlighted, "Agent Clan")
    repo = _styles_at(highlighted, "sase-core")
    assert any("underline" in style and "#ffaa00" in style for style in glossary)
    assert any("underline" in style and "#aa88ff" in style for style in repo)
    assert glossary != repo


def test_overlay_skips_code_literals_and_xprompt_tokens(
    tmp_path: Path,
) -> None:
    source = "#git:sase Run `Agent Clan` then Agent Clan"
    glossary = catalog_for_text(
        source,
        tmp_path,
        "Agent Clan",
        occurrence_count=2,
    )
    highlighted = highlight_prompt_text(
        source,
        glossary_catalog=glossary,
        semantic_styles=_STYLES,
    )

    assert XPROMPT_TOKEN_STYLES["invocation"] in _styles_at(highlighted, "#git")
    inline_styles = _styles_at(highlighted, "`Agent Clan`", offset=1)
    assert not any("#ffaa00" in style for style in inline_styles)
    prose = _styles_at(highlighted, "then Agent Clan", offset=5)
    assert any("#ffaa00" in style and "underline" in style for style in prose)


def test_overlay_converts_non_bmp_and_wrapped_segments(
    tmp_path: Path,
) -> None:
    source = "Ask 😀 Agent\n  Clan to coordinate"
    glossary = catalog_for_wrapped_text(source, tmp_path, "Agent Clan")
    highlighted = Text(source)
    apply_semantic_overlays(
        highlighted,
        source,
        glossary_catalog=glossary,
        styles=_STYLES,
    )

    assert any("#ffaa00" in style for style in _styles_at(highlighted, "Agent"))
    assert any("#ffaa00" in style for style in _styles_at(highlighted, "Clan"))
    assert not any("#ffaa00" in style for style in _styles_at(highlighted, "😀"))


def test_malformed_and_oversized_input_leaves_existing_styles(
    tmp_path: Path,
) -> None:
    source = "Agent Clan"
    highlighted = Text(source, style="bold")
    original = list(highlighted.spans)
    glossary = catalog_for_text(source, tmp_path, "Agent Clan")
    glossary.compiled._spans = (  # type: ignore[attr-defined]
        {
            **glossary.compiled._spans[0],  # type: ignore[attr-defined]
            "segments": [{"range": {"start": "bad"}}],
        },
    )
    apply_semantic_overlays(
        highlighted,
        source,
        glossary_catalog=glossary,
        styles=_STYLES,
    )
    assert highlighted.spans == original

    oversized = "Agent Clan " + "x" * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
    oversized_text = Text(oversized, style="italic")
    oversized_spans = list(oversized_text.spans)
    apply_semantic_overlays(
        oversized_text,
        oversized,
        glossary_catalog=catalog_for_text(oversized, tmp_path, "Agent Clan"),
        styles=_STYLES,
    )
    assert oversized_text.spans == oversized_spans


def test_markdown_prompt_path_keeps_inline_code(
    tmp_path: Path,
) -> None:
    source = "Ask Agent Clan to keep `sase-core` literal and inspect sase-core"
    highlighted = highlight_markdown_text(
        source,
        glossary_catalog=catalog_for_text(source, tmp_path, "Agent Clan"),
        repo_catalog=repo_catalog_for_text(
            source,
            tmp_path,
            "sase-core",
            occurrence_count=2,
        ),
        semantic_styles=_STYLES,
    )

    assert any("#ffaa00" in style for style in _styles_at(highlighted, "Agent Clan"))
    assert any(
        "#aa88ff" in style
        for style in _styles_at(highlighted, "inspect sase-core", offset=8)
    )
    inline = _styles_at(highlighted, "`sase-core`", offset=1)
    assert not any("#aa88ff" in style and "underline" in style for style in inline)
