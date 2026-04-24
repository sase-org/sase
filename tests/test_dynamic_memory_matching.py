"""Tests for generate_dynamic_memory: matching, word boundaries, file output, cleanup."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.dynamic import (
    DynamicMemoryResult,
    MatchedMemory,
    generate_dynamic_memory,
)
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import xprompt_to_workflow


def _make_memory_workflows() -> dict[str, object]:
    """Create a set of memory-tagged workflows for testing."""
    entries = {
        "memory/long/external_repos": {
            "tags": "memory",
            "keywords": ["chezmoi", "plugin", "cross-repo"],
            "content": "$(cat memory/long/external_repos.md)",
        },
        "memory/long/generated_skills": {
            "tags": "memory",
            "keywords": ["skill", "SKILL.md", "commit workflow"],
            "content": "$(cat memory/long/generated_skills.md)",
        },
        "regular_xprompt": "Just a regular xprompt with no memory tag",
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


# ── generate_dynamic_memory ───────────────────────────────────────────────


def test_matching_keywords_writes_individual_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s.replace(
                "$(cat memory/long/external_repos.md)", "# External Repos\nresolved"
            ),
        ),
    ):
        result = generate_dynamic_memory("I need to update the chezmoi config", None)

    assert len(result.matched) == 1
    assert result.matched[0].name == "memory/long/external_repos"
    assert "chezmoi" in result.matched[0].keywords_matched
    assert len(result.paths) == 1
    assert result.paths[0] == ".sase/memory/long-external-repos.md"

    content = Path(result.paths[0]).read_text()
    assert "# External Repos" in content
    assert "$(" not in content


def test_no_matches_returns_empty_paths() -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("nothing relevant here", None)

    assert result.matched == []
    assert result.paths == []


def test_multiple_matches_write_separate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s.replace(
                "$(cat memory/long/external_repos.md)", "# External Repos"
            ).replace("$(cat memory/long/generated_skills.md)", "# Generated Skills"),
        ),
    ):
        result = generate_dynamic_memory(
            "update the chezmoi plugin and the commit skill",
            None,
        )

    assert len(result.matched) == 2
    names = {m.name for m in result.matched}
    assert "memory/long/external_repos" in names
    assert "memory/long/generated_skills" in names

    assert len(result.paths) == 2
    all_content = "".join(Path(p).read_text() for p in result.paths)
    assert "# External Repos" in all_content
    assert "# Generated Skills" in all_content


def test_case_insensitive_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("CHEZMOI stuff", None)

    assert len(result.matched) == 1
    assert result.matched[0].name == "memory/long/external_repos"


def test_returns_structured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("chezmoi and plugin work", None)

    assert isinstance(result, DynamicMemoryResult)
    assert len(result.matched) == 1
    m = result.matched[0]
    assert isinstance(m, MatchedMemory)
    assert m.name == "memory/long/external_repos"
    assert "chezmoi" in m.keywords_matched
    assert "plugin" in m.keywords_matched
    assert m.content == "$(cat memory/long/external_repos.md)"
    assert len(result.paths) == 1


def test_no_matches_when_no_memory_tag() -> None:
    """Regular xprompts (without memory tag) are never matched."""
    entries = {
        "no_tag": {
            "keywords": ["chezmoi"],
            "content": "should not match",
        }
    }
    xprompts = parse_xprompt_entries(entries, "test")
    workflows = {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}

    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("chezmoi", None)

    assert result.matched == []
    assert result.paths == []


# ── word-boundary matching ────────────────────────────────────────────────


def test_substring_no_longer_matches_mid_word() -> None:
    """Keyword 'skill' should NOT match 'unskilled'."""
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("she is unskilled at this", None)

    assert result.matched == []


def test_whole_word_still_matches() -> None:
    """Keyword 'skill' should match the standalone word 'skill'."""
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("update the skill definitions", None)

    assert len(result.matched) == 1
    assert result.matched[0].name == "memory/long/generated_skills"
    assert "skill" in result.matched[0].keywords_matched


def test_hyphenated_keyword_matches_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyword 'cross-repo' matches 'cross-repo' but not 'across-repository'."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        hit = generate_dynamic_memory("do cross-repo sync", None)
        miss = generate_dynamic_memory("across-repository changes", None)

    assert len(hit.matched) == 1
    assert "cross-repo" in hit.matched[0].keywords_matched
    assert miss.matched == []


def test_special_char_keyword_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keyword 'SKILL.md' matches 'SKILL.md' in prompt."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("edit the SKILL.md file", None)

    assert len(result.matched) == 1
    assert "SKILL.md" in result.matched[0].keywords_matched


# ── file output location ──────────────────────────────────────────────────


def test_files_written_under_sase_memory_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Matched memory files are written under .sase/memory/ in CWD."""
    monkeypatch.chdir(tmp_path)
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("chezmoi stuff", None)

    assert len(result.paths) == 1
    assert result.paths[0].startswith(".sase/memory/")
    assert (tmp_path / result.paths[0]).exists()


# ── stale file cleanup ───────────────────────────────────────────────────


def test_stale_memory_file_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale long-*.md files are deleted when their source xprompt no longer exists."""
    monkeypatch.chdir(tmp_path)
    memory_dir = tmp_path / ".sase" / "memory"
    memory_dir.mkdir(parents=True)

    # Pre-create a stale file that has no corresponding xprompt
    stale = memory_dir / "long-tui-development.md"
    stale.write_text("# Stale content")

    # Also create a valid file that DOES correspond to an xprompt
    valid = memory_dir / "long-external-repos.md"
    valid.write_text("# Valid content")

    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        generate_dynamic_memory("nothing relevant here", None)

    assert not stale.exists(), "Stale file should have been deleted"
    assert valid.exists(), "Valid file should be preserved"


def test_prompt_with_existing_dynamic_memory_section_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing ### DYNAMIC MEMORY section is stripped before keyword matching."""
    monkeypatch.chdir(tmp_path)

    # Create workflows where "stale_keyword" only appears in the DYNAMIC MEMORY
    # section — it should NOT trigger a match after stripping.
    entries = {
        "memory/long/stale_test": {
            "tags": "memory",
            "keywords": ["stale_keyword"],
            "content": "# Stale test content",
        },
    }
    xprompts = parse_xprompt_entries(entries, "test")
    workflows = {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}

    prompt = (
        "A clean prompt with no keywords\n\n"
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-stale-test.md"
        " (memory/long/stale_test, matched: `stale_keyword`)"
    )
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory(prompt, None)

    assert result.matched == [], (
        "stale_keyword in DYNAMIC MEMORY section should not trigger a match"
    )
