"""Unit tests for generated agent-document section numbering."""

from __future__ import annotations

from sase.amd._section_numbers import number_agent_document_sections


def test_numbers_managed_document_shape() -> None:
    text = (
        "# Structured Agentic Software Engineering (SASE) - Agent Instructions\n"
        "\n"
        "## Core Memory\n"
        "\n"
        "### Build & Run Commands (build_and_run)\n"
        "\n"
        "#### IMPORTANT: Two-Speed Verification\n"
        "\n"
        "## Reference Memory\n"
        "\n"
        "## Memory Webs\n"
        "\n"
        "### Decisions (decisions)\n"
    )

    assert number_agent_document_sections(text) == (
        "# Structured Agentic Software Engineering (SASE) - Agent Instructions\n"
        "\n"
        "## 1. Core Memory\n"
        "\n"
        "### 1.1 Build & Run Commands (build_and_run)\n"
        "\n"
        "#### 1.1.1 IMPORTANT: Two-Speed Verification\n"
        "\n"
        "## 2. Reference Memory\n"
        "\n"
        "## 3. Memory Webs\n"
        "\n"
        "### 3.1 Decisions (decisions)\n"
    )


def test_counters_reset_under_new_parent() -> None:
    text = "# Title\n\n## First\n### One\n### Two\n## Second\n### One\n"

    assert number_agent_document_sections(text) == (
        "# Title\n\n## 1. First\n### 1.1 One\n### 1.2 Two\n## 2. Second\n### 2.1 One\n"
    )


def test_h1_is_never_numbered() -> None:
    text = "# First Title\n\n# Second Title\n\n## Section\n"

    assert number_agent_document_sections(text) == (
        "# First Title\n\n# Second Title\n\n## 1. Section\n"
    )


def test_base_level_is_shallowest_heading_below_title() -> None:
    text = "# Agent Instructions\n\n### SASE (sase)\n\n### Other (other)\n"

    assert number_agent_document_sections(text) == (
        "# Agent Instructions\n\n### 1. SASE (sase)\n\n### 2. Other (other)\n"
    )


def test_fenced_hashes_survive() -> None:
    text = (
        "# Title\n"
        "\n"
        "```bash\n"
        "# not a heading\n"
        "```\n"
        "\n"
        "## Section\n"
        "\n"
        "~~~\n"
        "### not a heading\n"
        "~~~\n"
    )

    assert number_agent_document_sections(text) == (
        "# Title\n"
        "\n"
        "```bash\n"
        "# not a heading\n"
        "```\n"
        "\n"
        "## 1. Section\n"
        "\n"
        "~~~\n"
        "### not a heading\n"
        "~~~\n"
    )


def test_absent_parent_reads_zero() -> None:
    text = "# Title\n\n### Orphan\n\n## Parent\n"

    assert number_agent_document_sections(text) == (
        "# Title\n\n### 0.1 Orphan\n\n## 1. Parent\n"
    )


def test_empty_heading_text_has_no_trailing_whitespace() -> None:
    assert number_agent_document_sections("# Title\n\n##\n") == "# Title\n\n## 1.\n"


def test_no_headings_below_title_returns_text_unchanged() -> None:
    assert number_agent_document_sections("# Title\n\nText.\n") == "# Title\n\nText.\n"
    assert number_agent_document_sections("Just text.\n") == "Just text.\n"


def test_already_numbered_input_is_double_prefixed() -> None:
    assert number_agent_document_sections("# Title\n\n## 1. Section\n") == (
        "# Title\n\n## 1. 1. Section\n"
    )
