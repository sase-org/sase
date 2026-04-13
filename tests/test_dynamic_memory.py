"""Tests for dynamic memory generation."""

from pathlib import Path
from unittest.mock import patch

from sase.memory.dynamic import MatchedMemory, generate_dynamic_memory
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.models import XPrompt, xprompt_to_workflow
from sase.xprompt.tags import XPromptTag, parse_tags


# ── parse_tags: memory ────────────────────────────────────────────────────


def test_parse_tags_memory() -> None:
    assert parse_tags("memory") == frozenset({XPromptTag.memory})


def test_parse_tags_all_values() -> None:
    """All tag enum values can be parsed (updated to include memory)."""
    result = parse_tags(
        [
            "vcs",
            "crs",
            "fix_hook",
            "rollover",
            "mentor",
            "commit",
            "propose",
            "make_mentor_changes",
            "diff_file",
            "append_to_pr",
            "append_to_commit_and_propose",
            "memory",
        ]
    )
    assert result == frozenset(XPromptTag)


# ── keywords parsing: config entries ──────────────────────────────────────


def test_parse_xprompt_entries_with_keywords() -> None:
    entries = {
        "memory/foo": {
            "tags": "memory",
            "keywords": ["chezmoi", "plugin"],
            "content": "@memory/long/foo.md",
        }
    }
    result = parse_xprompt_entries(entries, "test")
    xp = result["memory/foo"]
    assert xp.keywords == ["chezmoi", "plugin"]
    assert xp.has_tag(XPromptTag.memory)
    assert xp.content == "@memory/long/foo.md"


def test_parse_xprompt_entries_simple_string_has_no_keywords() -> None:
    entries = {"simple": "Just a string"}
    result = parse_xprompt_entries(entries, "test")
    assert result["simple"].keywords == []


# ── keywords parsing: file frontmatter ────────────────────────────────────


def test_keywords_from_frontmatter(tmp_path: Path) -> None:
    from sase.xprompt.loader import _load_xprompt_from_file

    md = tmp_path / "test.md"
    md.write_text(
        "---\ntags: memory\nkeywords: [chezmoi, plugin]\n---\n@memory/long/foo.md\n"
    )
    xp = _load_xprompt_from_file(md)
    assert xp is not None
    assert xp.keywords == ["chezmoi", "plugin"]
    assert xp.has_tag(XPromptTag.memory)


# ── keywords propagation through xprompt_to_workflow ──────────────────────


def test_xprompt_to_workflow_copies_keywords() -> None:
    xp = XPrompt(
        name="memory/foo",
        content="@memory/long/foo.md",
        tags=frozenset({XPromptTag.memory}),
        keywords=["chezmoi", "plugin"],
    )
    wf = xprompt_to_workflow(xp)
    assert wf.keywords == ["chezmoi", "plugin"]


# ── generate_dynamic_memory ───────────────────────────────────────────────


def _make_memory_workflows() -> dict[str, object]:
    """Create a set of memory-tagged workflows for testing."""
    entries = {
        "memory/external_repos": {
            "tags": "memory",
            "keywords": ["chezmoi", "plugin", "cross-repo"],
            "content": "@memory/long/external_repos.md",
        },
        "memory/generated_skills": {
            "tags": "memory",
            "keywords": ["skill", "SKILL.md", "commit workflow"],
            "content": "@memory/long/generated_skills.md",
        },
        "regular_xprompt": "Just a regular xprompt with no memory tag",
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


def test_matching_keywords_writes_file(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory(
            "I need to update the chezmoi config", str(tmp_path), None
        )

    assert len(result) == 1
    assert result[0].name == "memory/external_repos"
    assert "chezmoi" in result[0].keywords_matched

    dynamic_path = tmp_path / "memory" / "dynamic.md"
    assert dynamic_path.exists()
    content = dynamic_path.read_text()
    assert "@memory/long/external_repos.md" in content


def test_no_matches_removes_existing_file(tmp_path: Path) -> None:
    # Pre-create the file
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    dynamic_path = mem_dir / "dynamic.md"
    dynamic_path.write_text("old content")

    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("nothing relevant here", str(tmp_path), None)

    assert result == []
    assert not dynamic_path.exists()


def test_multiple_matches_concatenated(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory(
            "update the chezmoi plugin and the commit skill",
            str(tmp_path),
            None,
        )

    assert len(result) == 2
    names = {m.name for m in result}
    assert "memory/external_repos" in names
    assert "memory/generated_skills" in names

    dynamic_path = tmp_path / "memory" / "dynamic.md"
    content = dynamic_path.read_text()
    assert "@memory/long/external_repos.md" in content
    assert "@memory/long/generated_skills.md" in content


def test_case_insensitive_matching(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("CHEZMOI stuff", str(tmp_path), None)

    assert len(result) == 1
    assert result[0].name == "memory/external_repos"


def test_returns_structured_matched_memory(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("chezmoi and plugin work", str(tmp_path), None)

    assert len(result) == 1
    m = result[0]
    assert isinstance(m, MatchedMemory)
    assert m.name == "memory/external_repos"
    assert "chezmoi" in m.keywords_matched
    assert "plugin" in m.keywords_matched
    assert m.content == "@memory/long/external_repos.md"


def test_no_matches_when_no_memory_tag(tmp_path: Path) -> None:
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
        result = generate_dynamic_memory("chezmoi", str(tmp_path), None)

    assert result == []
