"""Tests for dynamic memory generation."""

from pathlib import Path
from unittest.mock import patch

from sase.memory.dynamic import (
    DynamicMemoryResult,
    MatchedMemory,
    generate_dynamic_memory,
)
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
            "content": "$(cat memory/long/foo.md)",
        }
    }
    result = parse_xprompt_entries(entries, "test")
    xp = result["memory/foo"]
    assert xp.keywords == ["chezmoi", "plugin"]
    assert xp.has_tag(XPromptTag.memory)
    assert xp.content == "$(cat memory/long/foo.md)"


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
            "content": "$(cat memory/long/external_repos.md)",
        },
        "memory/generated_skills": {
            "tags": "memory",
            "keywords": ["skill", "SKILL.md", "commit workflow"],
            "content": "$(cat memory/long/generated_skills.md)",
        },
        "regular_xprompt": "Just a regular xprompt with no memory tag",
    }
    xprompts = parse_xprompt_entries(entries, "test")
    return {name: xprompt_to_workflow(xp) for name, xp in xprompts.items()}


def test_matching_keywords_writes_temp_file(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch("sase.memory.dynamic.get_sase_tmpdir", return_value=str(tmp_path)),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s.replace(
                "$(cat memory/long/external_repos.md)", "# External Repos\nresolved"
            ),
        ),
    ):
        result = generate_dynamic_memory("I need to update the chezmoi config", None)

    assert len(result.matched) == 1
    assert result.matched[0].name == "memory/external_repos"
    assert "chezmoi" in result.matched[0].keywords_matched
    assert result.path is not None

    content = Path(result.path).read_text()
    assert "---\n## memory/external_repos\n" in content
    assert "# External Repos" in content
    assert "$(" not in content


def test_no_matches_returns_no_path() -> None:
    workflows = _make_memory_workflows()
    with patch("sase.xprompt.loader.get_all_prompts", return_value=workflows):
        result = generate_dynamic_memory("nothing relevant here", None)

    assert result.matched == []
    assert result.path is None


def test_multiple_matches_concatenated(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch("sase.memory.dynamic.get_sase_tmpdir", return_value=str(tmp_path)),
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
    assert "memory/external_repos" in names
    assert "memory/generated_skills" in names

    assert result.path is not None
    content = Path(result.path).read_text()
    assert "---\n## memory/external_repos\n" in content
    assert "---\n## memory/generated_skills\n" in content
    assert "# External Repos" in content
    assert "# Generated Skills" in content


def test_case_insensitive_matching(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch("sase.memory.dynamic.get_sase_tmpdir", return_value=str(tmp_path)),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("CHEZMOI stuff", None)

    assert len(result.matched) == 1
    assert result.matched[0].name == "memory/external_repos"


def test_returns_structured_result(tmp_path: Path) -> None:
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch("sase.memory.dynamic.get_sase_tmpdir", return_value=str(tmp_path)),
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
    assert m.name == "memory/external_repos"
    assert "chezmoi" in m.keywords_matched
    assert "plugin" in m.keywords_matched
    assert m.content == "$(cat memory/long/external_repos.md)"
    assert result.path is not None


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
    assert result.path is None


def test_temp_file_uses_sase_tmpdir(tmp_path: Path) -> None:
    """Temp file is written under $SASE_TMPDIR when set."""
    sase_tmp = tmp_path / "sase_tmp"
    sase_tmp.mkdir()
    workflows = _make_memory_workflows()
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflows),
        patch("sase.memory.dynamic.get_sase_tmpdir", return_value=str(sase_tmp)),
        patch(
            "sase.gemini_wrapper.file_references.process_command_substitution",
            side_effect=lambda s: s,
        ),
    ):
        result = generate_dynamic_memory("chezmoi stuff", None)

    assert result.path is not None
    assert str(sase_tmp) in result.path
