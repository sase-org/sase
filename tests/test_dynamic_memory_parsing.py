"""Tests for dynamic memory tag/keyword parsing and memory/long loader."""

from pathlib import Path
from unittest.mock import patch

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
            "create_epic_bead",
            "work_phase_bead",
            "land_epic",
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
