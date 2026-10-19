"""Pure tests for the Markdown anchor index."""

from __future__ import annotations

from sase.pager.markdown_anchors import build_markdown_anchor_index


def test_atx_levels_and_closing_hashes() -> None:
    text = "# One\n## Two ##\n### Three ###\n# C#\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("one") == 1
    assert index.line_for("two") == 2
    assert index.line_for("three") == 3
    assert index.line_for("c") == 4


def test_four_space_indentation_is_not_a_heading() -> None:
    index = build_markdown_anchor_index("    # Not heading\n# Real\n")

    assert index.line_for("not-heading") is None
    assert index.line_for("real") == 2


def test_blockquote_heading_counts() -> None:
    index = build_markdown_anchor_index("> ## Quoted\n")

    assert index.line_for("quoted") == 1


def test_setext_headings_and_thematic_break() -> None:
    text = "Title\n=====\nSub\n---\n\n---\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("title") == 1
    assert index.line_for("sub") == 3


def test_frontmatter_delimiters_are_not_headings() -> None:
    text = "---\ntitle: x\n---\n# Real\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("real") == 4
    assert index.line_for("title") is None


def test_fenced_code_hides_headings() -> None:
    text = "# A\n```md\n### Page 11\n```\n# B\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("a") == 1
    assert index.line_for("page-11") is None
    assert index.line_for("b") == 5


def test_tilde_fence_and_longer_closing_fence() -> None:
    text = "# A\n~~~\n## Hidden\n~~~~\n# B\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("hidden") is None
    assert index.line_for("b") == 5


def test_unclosed_fence_runs_to_end() -> None:
    index = build_markdown_anchor_index("# A\n```\n## Hidden\n")

    assert index.line_for("a") == 1
    assert index.line_for("hidden") is None


def test_github_slug_exact_and_loose() -> None:
    text = "# Continuation highlights in `bob ref`: the `<` marker\n"
    index = build_markdown_anchor_index(text)

    assert index.line_for("continuation-highlights-in-bob-ref-the--marker") == 1
    assert index.line_for("continuation-highlights-in-bob-ref-the-marker") == 1


def test_link_text_inline_code_and_emphasis() -> None:
    assert (
        build_markdown_anchor_index("# Hello [Link](http://x)\n").line_for("hello-link")
        == 1
    )
    assert (
        build_markdown_anchor_index("# Use `code` here\n").line_for("use-code-here")
        == 1
    )
    assert build_markdown_anchor_index("# **bold**\n").line_for("bold") == 1


def test_unicode_fragment_percent_decoded() -> None:
    index = build_markdown_anchor_index("## Café\n")

    assert index.line_for("caf%C3%A9") == 1


def test_duplicates_get_suffixes() -> None:
    index = build_markdown_anchor_index("# Foo\n# Foo\n# Foo\n")

    assert index.line_for("foo") == 1
    assert index.line_for("foo-1") == 2
    assert index.line_for("foo-2") == 3


def test_obsidian_loose_match_is_case_insensitive() -> None:
    index = build_markdown_anchor_index("## Requirement adjustments\n")

    assert index.line_for("Requirement%20adjustments") == 1
    assert index.line_for("REQUIREMENT-ADJUSTMENTS") == 1


def test_explicit_ids() -> None:
    assert build_markdown_anchor_index("# Head {#custom}\n").line_for("custom") == 1
    assert build_markdown_anchor_index("# Head {#custom}\n").line_for("head") == 1
    assert build_markdown_anchor_index('<a id="myid"></a>\n').line_for("myid") == 1
    assert (
        build_markdown_anchor_index('<a name="anchor1"></a>\n').line_for("anchor1") == 1
    )
    assert (
        build_markdown_anchor_index('<div id="sec1">hi</div>\n').line_for("sec1") == 1
    )


def test_block_ids() -> None:
    assert build_markdown_anchor_index("para ^my-block\n").line_for("^my-block") == 1
    assert build_markdown_anchor_index("^solo\n").line_for("^solo") == 1


def test_empty_and_top_resolve_to_line_one() -> None:
    index = build_markdown_anchor_index("# Hello\n")

    assert index.line_for("") == 1
    assert index.line_for("top") == 1
    assert index.line_for("missing") is None


def test_crlf_and_special_chars_do_not_shift_lines() -> None:
    crlf = build_markdown_anchor_index("# A\r\nbody\r\n## B\r\n")
    assert crlf.line_for("a") == 1
    assert crlf.line_for("b") == 3

    # U+2028 and form-feed stay inside their logical line.
    u2028 = build_markdown_anchor_index("# A body\n## B\n")
    assert u2028.line_for("b") == 2
    formfeed = build_markdown_anchor_index("# A\x0cbody\n## B\n")
    assert formfeed.line_for("b") == 2
