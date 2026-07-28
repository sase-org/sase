"""Tests for updating prompt Q&A sections."""

import tempfile
from pathlib import Path

from sase.sdd.artifact_links import parse_sdd_artifact_link
from sase.sdd.files import set_prompt_qa, update_prompt_with_qa, update_spec_with_qa


def test_update_prompt_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        update_prompt_with_qa(prompt_path, "## Q&A\nQ: Why?\nA: Because.")

        content = prompt_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_prompt_with_qa_preserves_artifact_bullet() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text(
            "- **PLAN:** [../202607/plan.md](../plan.md)\n\nOriginal prompt.\n",
            encoding="utf-8",
        )

        update_prompt_with_qa(
            prompt_path, "### Questions and Answers\n\n#### Q1: Why?\n"
        )

        content = prompt_path.read_text(encoding="utf-8")
        link = parse_sdd_artifact_link(content)
        assert link.reference == "../202607/plan.md"
        assert link.body.startswith("Original prompt.\n")
        assert link.body.count("### Questions and Answers") == 1


def test_update_prompt_with_qa_missing_file() -> None:
    """No-op if prompt file doesn't exist."""
    update_prompt_with_qa(Path("/nonexistent/prompt.md"), "qa content")
    # Should not raise


def test_update_spec_with_qa_legacy_wrapper() -> None:
    """Calling the legacy wrapper twice produces exactly one Q&A block
    (replace-not-append semantics)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        prompt_path.write_text("# Prompt\nOriginal content", encoding="utf-8")

        first = "### Questions and Answers\n\n#### Q1: one\n"
        second = "### Questions and Answers\n\n#### Q1: one\n\n#### Q2: two\n"

        update_spec_with_qa(prompt_path, first)
        update_spec_with_qa(prompt_path, second)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert "#### Q1: one" in content
        assert "#### Q2: two" in content
        assert "Original content" in content


def test_set_prompt_qa_replaces_wrapped_block() -> None:
    """A previously-written wrapped Q&A block is replaced cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        initial_qa = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: old\n"
            "%xprompts_enabled:true"
        )
        prompt_path.write_text(f"# Prompt\nBody\n\n{initial_qa}\n", encoding="utf-8")

        new_qa = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: new\n"
            "%xprompts_enabled:true"
        )
        set_prompt_qa(prompt_path, new_qa)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert content.count("%xprompts_enabled:false") == 1
        assert content.count("%xprompts_enabled:true") == 1
        assert "#### Q1: new" in content
        assert "#### Q1: old" not in content
        assert "# Prompt" in content
        assert "Body" in content


def test_set_prompt_qa_strips_legacy_duplicate_blocks() -> None:
    """A snapshot accidentally containing two appended Q&A blocks is
    consolidated to one on the next set_prompt_qa call."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompt_path = Path(tmpdir) / "prompt.md"
        duplicated = (
            "# Prompt\nBody\n\n"
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n#### Q1: round1\n"
            "%xprompts_enabled:true\n\n"
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n#### Q1: round2\n"
            "%xprompts_enabled:true\n"
        )
        prompt_path.write_text(duplicated, encoding="utf-8")

        merged = (
            "%xprompts_enabled:false\n"
            "### Questions and Answers\n\n"
            "#### Q1: round1\n\n#### Q2: round2\n"
            "%xprompts_enabled:true"
        )
        set_prompt_qa(prompt_path, merged)

        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("### Questions and Answers") == 1
        assert content.count("%xprompts_enabled:false") == 1
        assert "#### Q1: round1" in content
        assert "#### Q2: round2" in content


def test_set_prompt_qa_missing_file_is_noop() -> None:
    set_prompt_qa(Path("/nonexistent/prompt.md"), "ignored")
