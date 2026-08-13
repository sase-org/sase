"""Unit tests for ``sase.amd.inline_memory`` pure helpers."""

from __future__ import annotations

from sase.amd.inline_memory import (
    _extract_memory_title,
    inline_memory_section,
    validate_short_memory_structure,
)

# A fixture resembling ``sase/memory/build_and_run.md``: an H1 title, a fenced bash
# block whose comment lines start with ``#``, plus an H2 and a nested H3.
BUILD_AND_RUN_BODY = """# Build & Run Commands

```bash
just install       # Install in editable mode with dev deps
just check         # lint + test
```

## IMPORTANT: You MUST Run `just check` if you Made File Changes

Run it before replying.

### Exceptions

There is no point if only bead files changed.
"""


def test_extract_memory_title_returns_first_h1_text() -> None:
    assert _extract_memory_title(BUILD_AND_RUN_BODY) == "Build & Run Commands"
    assert _extract_memory_title("# Title Only\n") == "Title Only"


def test_extract_memory_title_returns_none_without_h1() -> None:
    assert _extract_memory_title("Just prose, no heading.\n") is None
    assert _extract_memory_title("## Starts At H2\n") is None


def test_extract_memory_title_ignores_hash_inside_fence() -> None:
    body = "```\n# not a heading\n```\n\n# Real Title\n"
    assert _extract_memory_title(body) == "Real Title"


def test_validate_passes_for_h1_only() -> None:
    assert validate_short_memory_structure("# Only A Title\n") is None


def test_validate_passes_for_h1_h2_h3() -> None:
    body = "# Title\n\n## Section\n\nText.\n\n### Subsection\n\nMore.\n"
    assert validate_short_memory_structure(body) is None


def test_validate_passes_for_realistic_build_and_run_fixture() -> None:
    assert validate_short_memory_structure(BUILD_AND_RUN_BODY) is None


def test_validate_ignores_hash_inside_fence() -> None:
    # The fenced ``# comment`` must not count as a second H1.
    body = "# Title\n\n```sh\n# a comment\necho hi\n```\n"
    assert validate_short_memory_structure(body) is None


def test_validate_fails_when_h1_missing() -> None:
    error = validate_short_memory_structure("Some prose without any heading.\n")
    assert error is not None
    assert "H1" in error


def test_validate_fails_when_first_heading_is_not_h1() -> None:
    error = validate_short_memory_structure("## Section first\n\n# Title later\n")
    assert error is not None
    assert "H1" in error


def test_validate_fails_for_multiple_h1() -> None:
    error = validate_short_memory_structure("# First\n\n# Second\n")
    assert error is not None
    assert "found 2" in error


def test_validate_fails_for_h4_or_deeper() -> None:
    body = "# Title\n\n## Section\n\n#### Too Deep\n"
    error = validate_short_memory_structure(body)
    assert error is not None
    assert "deeper than H3" in error
    assert "Too Deep" in error


def test_inline_shifts_headings_down_two_levels() -> None:
    body = "# Title\n\n## Section\n\n### Subsection\n"
    expected = "### Title (x)\n\n#### Section\n\n##### Subsection\n"
    section = inline_memory_section("sase/memory/x.md", body)
    assert section == expected
    assert "#### 1." not in section


def test_inline_leaves_sections_unnumbered() -> None:
    body = "# Title\n\n## First\n\nText.\n\n## Second\n"
    expected = "### Title (x)\n\n#### First\n\nText.\n\n#### Second\n"
    assert inline_memory_section("sase/memory/x.md", body) == expected


def test_inline_leaves_subsections_unnumbered() -> None:
    body = "# Title\n\n## First\n\n### One\n\n### Two\n\n## Second\n\n### One\n"
    expected = (
        "### Title (x)\n\n"
        "#### First\n\n"
        "##### One\n\n"
        "##### Two\n\n"
        "#### Second\n\n"
        "##### One\n"
    )
    assert inline_memory_section("sase/memory/x.md", body) == expected


def test_inline_strips_h1_and_emits_header() -> None:
    body = "# Just A Title\n"
    assert inline_memory_section("sase/memory/x.md", body) == "### Just A Title (x)\n"


def test_inline_keeps_title_parentheses_before_basename() -> None:
    body = "# Foo (bar)\n"
    assert inline_memory_section("sase/memory/build_and_run.md", body) == (
        "### Foo (bar) (build_and_run)\n"
    )


def test_inline_copies_code_fences_verbatim() -> None:
    expected = (
        "### Build & Run Commands (build_and_run)\n"
        "\n"
        "```bash\n"
        "just install       # Install in editable mode with dev deps\n"
        "just check         # lint + test\n"
        "```\n"
        "\n"
        "#### IMPORTANT: You MUST Run `just check` if you Made File Changes\n"
        "\n"
        "Run it before replying.\n"
        "\n"
        "##### Exceptions\n"
        "\n"
        "There is no point if only bead files changed.\n"
    )
    assert (
        inline_memory_section("sase/memory/build_and_run.md", BUILD_AND_RUN_BODY)
        == expected
    )


def test_inline_realistic_fixture_headings_are_only_shifted() -> None:
    expected = (
        "### Build & Run Commands (build_and_run)\n"
        "\n"
        "```bash\n"
        "just install       # Install in editable mode with dev deps\n"
        "just check         # lint + test\n"
        "```\n"
        "\n"
        "#### IMPORTANT: You MUST Run `just check` if you Made File Changes\n"
        "\n"
        "Run it before replying.\n"
        "\n"
        "##### Exceptions\n"
        "\n"
        "There is no point if only bead files changed.\n"
    )
    assert (
        inline_memory_section(
            "sase/memory/build_and_run.md",
            BUILD_AND_RUN_BODY,
        )
        == expected
    )


def test_inline_keeps_fenced_hash_lines_untouched() -> None:
    # A ``#`` at column zero inside a fence must be neither stripped nor shifted.
    body = "# Title\n\n```sh\n# shell comment\necho hi\n```\n"
    section = inline_memory_section("sase/memory/x.md", body)
    assert "# shell comment" in section
    assert "## shell comment" not in section
    assert section == "### Title (x)\n\n```sh\n# shell comment\necho hi\n```\n"


def test_inline_keeps_fenced_hash_lines_untouched_with_headings() -> None:
    body = "# Title\n\n```sh\n# shell comment\necho hi\n```\n\n## Section\n"
    section = inline_memory_section("sase/memory/x.md", body)
    assert "# shell comment" in section
    assert "## shell comment" not in section
    assert "#### Section" in section


def test_inline_shifts_h3_before_h2_without_numbering() -> None:
    body = "# Title\n\n### Orphan\n"
    expected = "### Title (x)\n\n##### Orphan\n"
    assert inline_memory_section("sase/memory/x.md", body) == expected


def test_inline_shifts_empty_heading_without_trailing_space() -> None:
    body = "# T\n\n##\n"
    assert inline_memory_section("sase/memory/x.md", body) == "### T (x)\n\n####\n"


def test_inline_without_title_omits_parenthetical() -> None:
    body = "no heading here\n"
    assert (
        inline_memory_section("sase/memory/x.md", body) == "### x\n\nno heading here\n"
    )
