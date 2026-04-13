"""Tests for dynamic memory generation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.memory.dynamic import (
    DynamicMemoryResult,
    MatchedMemory,
    _memory_filename,
    format_dynamic_memory_section,
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


# ── _load_memory_long_xprompts ────────────────────────────────────────────


def test_load_memory_long_discovers_frontmatter(tmp_path: Path) -> None:
    """Files with keywords frontmatter are discovered as memory xprompts."""
    from sase.xprompt.loader import _load_memory_long_xprompts

    mem_dir = tmp_path / "memory" / "long"
    mem_dir.mkdir(parents=True)
    (mem_dir / "foo.md").write_text(
        "---\nkeywords: [alpha, beta]\n---\n# Foo content\n"
    )

    with (
        patch(
            "sase.xprompt.loader._get_memory_long_search_dirs",
            return_value=[(mem_dir, True)],
        ),
        patch("sase.xprompt.loader.Path.cwd", return_value=tmp_path),
    ):
        result = _load_memory_long_xprompts()

    assert "memory/long/foo" in result
    xp = result["memory/long/foo"]
    assert xp.keywords == ["alpha", "beta"]
    assert xp.has_tag(XPromptTag.memory)
    assert "$(cat " in xp.content


def test_load_memory_long_skips_no_keywords(tmp_path: Path) -> None:
    """Files without keywords frontmatter are ignored."""
    from sase.xprompt.loader import _load_memory_long_xprompts

    mem_dir = tmp_path / "memory" / "long"
    mem_dir.mkdir(parents=True)
    (mem_dir / "no_keywords.md").write_text("# Just a file\nNo frontmatter.\n")

    with patch(
        "sase.xprompt.loader._get_memory_long_search_dirs",
        return_value=[(mem_dir, True)],
    ):
        result = _load_memory_long_xprompts()

    assert result == {}


def test_load_memory_long_uses_absolute_path_for_home(tmp_path: Path) -> None:
    """Home-based files use absolute paths in $(cat ...)."""
    from sase.xprompt.loader import _load_memory_long_xprompts

    mem_dir = tmp_path / ".claude" / "memory" / "long"
    mem_dir.mkdir(parents=True)
    md_file = mem_dir / "bar.md"
    md_file.write_text("---\nkeywords: [gamma]\n---\n# Bar\n")

    with patch(
        "sase.xprompt.loader._get_memory_long_search_dirs",
        return_value=[(mem_dir, False)],
    ):
        result = _load_memory_long_xprompts()

    assert "memory/long/bar" in result
    assert result["memory/long/bar"].content == f"$(cat {md_file})"


def test_load_memory_long_first_dir_wins(tmp_path: Path) -> None:
    """Higher-priority directory wins on name collision."""
    from sase.xprompt.loader import _load_memory_long_xprompts

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    for d in (dir_a, dir_b):
        d.mkdir(parents=True)
        (d / "dup.md").write_text(f"---\nkeywords: [from_{d.name}]\n---\n# {d.name}\n")

    with (
        patch(
            "sase.xprompt.loader._get_memory_long_search_dirs",
            return_value=[(dir_a, True), (dir_b, True)],
        ),
        patch("sase.xprompt.loader.Path.cwd", return_value=tmp_path),
    ):
        result = _load_memory_long_xprompts()

    assert result["memory/long/dup"].keywords == ["from_a"]


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


# ── _memory_filename ─────────────────────────────────────────────────────


def test_memory_filename_long_prefix() -> None:
    assert _memory_filename("memory/long/external_repos") == "long-external-repos.md"


def test_memory_filename_underscores_to_hyphens() -> None:
    assert (
        _memory_filename("memory/long/generated_skills") == "long-generated-skills.md"
    )


# ── format_dynamic_memory_section ────────────────────────────────────────


def test_format_dynamic_memory_section_single() -> None:
    result = format_dynamic_memory_section([".sase/memory/long-external-repos.md"])
    assert result == ("### DYNAMIC MEMORY\n- @.sase/memory/long-external-repos.md")


def test_format_dynamic_memory_section_multiple() -> None:
    result = format_dynamic_memory_section(
        [".sase/memory/long-external-repos.md", ".sase/memory/long-generated-skills.md"]
    )
    assert result == (
        "### DYNAMIC MEMORY\n"
        "- @.sase/memory/long-external-repos.md\n"
        "- @.sase/memory/long-generated-skills.md"
    )
