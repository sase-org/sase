"""Tests for dynamic memory formatting helpers: filename, section format, strip."""

from sase.memory.dynamic import (
    DynamicMemoryResult,
    MatchedMemory,
    _memory_filename,
    _strip_dynamic_memory_section,
    format_dynamic_memory_section,
)


# ── _memory_filename ─────────────────────────────────────────────────────


def test_memory_filename_long_prefix() -> None:
    assert _memory_filename("memory/long/external_repos") == "long-external-repos.md"


def test_memory_filename_underscores_to_hyphens() -> None:
    assert (
        _memory_filename("memory/long/generated_skills") == "long-generated-skills.md"
    )


# ── format_dynamic_memory_section ────────────────────────────────────────


def test_format_dynamic_memory_section_single() -> None:
    dr = DynamicMemoryResult(
        matched=[
            MatchedMemory(
                name="memory/long/external_repos",
                keywords_matched=["chezmoi"],
                content="",
            )
        ],
        paths=["/workspace/.sase/memory/long-external-repos.md"],
    )
    result = format_dynamic_memory_section(dr)
    assert result == (
        "### DYNAMIC MEMORY\n"
        "- @/workspace/.sase/memory/long-external-repos.md (matched: `chezmoi`)"
    )


def test_format_dynamic_memory_section_multiple() -> None:
    dr = DynamicMemoryResult(
        matched=[
            MatchedMemory(
                name="memory/long/external_repos",
                keywords_matched=["chezmoi", "plugin"],
                content="",
            ),
            MatchedMemory(
                name="memory/long/generated_skills",
                keywords_matched=["skill", "commit workflow"],
                content="",
            ),
        ],
        paths=[
            "/workspace/.sase/memory/long-external-repos.md",
            "/workspace/.sase/memory/long-generated-skills.md",
        ],
    )
    result = format_dynamic_memory_section(dr)
    assert result == (
        "### DYNAMIC MEMORY\n"
        "- @/workspace/.sase/memory/long-external-repos.md "
        "(matched: `chezmoi`, `plugin`)\n"
        "- @/workspace/.sase/memory/long-generated-skills.md "
        "(matched: `skill`, `commit workflow`)"
    )


# ── _strip_dynamic_memory_section ─────────────────────────────────────────


def test__strip_dynamic_memory_section_at_end() -> None:
    prompt = (
        "Some prompt text\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-foo.md (matched: `bar`)"
    )
    assert _strip_dynamic_memory_section(prompt) == "Some prompt text"


def test__strip_dynamic_memory_section_in_middle() -> None:
    prompt = (
        "Before\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-foo.md (matched: `bar`)\n\n"
        "After"
    )
    assert _strip_dynamic_memory_section(prompt) == "Before"


def test__strip_dynamic_memory_section_not_present() -> None:
    prompt = "Just a normal prompt with no dynamic memory"
    assert _strip_dynamic_memory_section(prompt) == prompt
