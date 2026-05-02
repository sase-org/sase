"""Tests for xprompt.loader config and file loading functions."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.loader import (
    _load_xprompt_from_file,
    get_all_prompts,
    get_all_xprompts,
)
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.models import InputType, XPrompt

# Tests for _load_xprompt_from_file


def test_load_xprompt_from_file_without_front_matter() -> None:
    """Test loading xprompt file without front matter."""
    content = "Just some content without front matter"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = _load_xprompt_from_file(temp_path)

        assert xprompt is not None
        # Name should be filename stem
        assert xprompt.name == temp_path.stem
        assert xprompt.inputs == []
        assert xprompt.content == content
    finally:
        temp_path.unlink()


def test_load_xprompt_from_file_nonexistent() -> None:
    """Test loading nonexistent file returns None."""
    xprompt = _load_xprompt_from_file(Path("/nonexistent/path.md"))
    assert xprompt is None


def test_load_xprompt_from_file_with_skill_and_description() -> None:
    """Test loading xprompt file with skill and description front matter."""
    content = """---
name: my_skill
description: A useful skill
skill: true
---
Skill body content"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = _load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.name == "my_skill"
        assert xprompt.description == "A useful skill"
        assert xprompt.skill is True
        assert xprompt.content == "Skill body content"
    finally:
        temp_path.unlink()


def test_load_xprompt_from_file_with_skill_provider_list() -> None:
    """Test loading xprompt file with skill as provider list."""
    content = """---
name: hg_commit
skill: [gemini]
---
Commit with hg"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = _load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.skill == ["gemini"]
        assert xprompt.description is None
    finally:
        temp_path.unlink()


# Tests for parse_yaml_front_matter


def testparse_yaml_front_matter_invalid_yaml() -> None:
    """Test that invalid YAML in front matter returns None and full content."""
    content = """---
invalid: yaml: content: [not closed
---
Body content"""
    front_matter, body = parse_yaml_front_matter(content)
    assert front_matter is None
    assert body == content


# Tests for priority


def test_higher_priority_dir_md_overrides_lower_dir_md() -> None:
    """Test that .md from higher-priority dir overrides .md from lower dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        high_dir = Path(tmp_dir) / "high"
        low_dir = Path(tmp_dir) / "low"
        high_dir.mkdir()
        low_dir.mkdir()

        (high_dir / "shared.md").write_text("From high dir")
        (low_dir / "shared.md").write_text("From low dir")

        with patch(
            "sase.xprompt.loader.get_xprompt_search_paths",
            return_value=[high_dir, low_dir],
        ):
            from sase.xprompt.loader import _load_xprompts_from_files

            result = _load_xprompts_from_files()

        assert result["shared"].content == "From high dir"


# Tests for get_all_xprompts integration


def test_get_all_xprompts_includes_md_files() -> None:
    """Test that get_all_xprompts includes .md files from search dirs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()
        (search_dir / "hello.md").write_text("Hello from md")

        with (
            patch(
                "sase.xprompt.loader.get_xprompt_search_paths",
                return_value=[search_dir],
            ),
            patch("sase.xprompt.loader.load_xprompts_by_source", return_value=[]),
            patch("sase.xprompt.loader._load_xprompts_from_internal", return_value={}),
        ):
            result = get_all_xprompts()

        assert "hello" in result
        assert result["hello"].content == "Hello from md"


def test_research_xprompts_load_from_default_config(tmp_path: Path) -> None:
    """Research xprompts are built-ins and compose via the built-in name."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core._get_local_config_path", return_value=None),
        patch("sase.main.plugin_discovery.is_plugin_disabled", return_value=True),
        patch("sase.xprompt.loader.detect_project", return_value=None),
        patch("sase.xprompt.loader.get_xprompt_search_paths", return_value=[]),
        patch("sase.xprompt.loader._load_xprompts_from_internal", return_value={}),
        patch("sase.xprompt.loader._load_xprompts_from_plugins", return_value={}),
        patch("sase.xprompt.loader._load_memory_long_xprompts", return_value={}),
        patch("sase.xprompt.workflow_loader.get_all_workflows", return_value={}),
    ):
        prompts = get_all_prompts(project=None)

    assert "research" in prompts
    assert "research/more" in prompts
    assert "research/prompt" in prompts
    assert prompts["research"].source_path == "default_config"
    assert prompts["research/more"].source_path == "default_config"
    assert prompts["research/prompt"].source_path == "default_config"

    research_prompt = prompts["research/prompt"]
    assert len(research_prompt.inputs) == 1
    prompt_input = research_prompt.inputs[0]
    assert prompt_input.name == "prompt"
    assert prompt_input.type is InputType.TEXT

    body = research_prompt.steps[0].prompt_part or ""
    assert "#research" in body
    assert "#sase/research" not in body


# Tests for _load_xprompts_from_project


def _load_xprompts_from_project_with_base(
    project: str, base_config_dir: Path
) -> dict[str, XPrompt]:
    """Helper to test project loading with a custom base directory.

    This replicates the logic of _load_xprompts_from_project but allows
    specifying a custom base directory for testing.
    """
    project_dir = base_config_dir / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    xprompts: dict[str, XPrompt] = {}
    for md_file in project_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = _load_xprompt_from_file(md_file)
            if xprompt:
                namespaced_name = f"{project}/{xprompt.name}"
                xprompts[namespaced_name] = XPrompt(
                    name=namespaced_name,
                    content=xprompt.content,
                    inputs=xprompt.inputs,
                    source_path=xprompt.source_path,
                )
    return xprompts


def test_load_xprompts_from_project_nonexistent_dir() -> None:
    """Test that nonexistent project directory returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        xprompts = _load_xprompts_from_project_with_base(
            "nonexistent_project", Path(tmp_dir)
        )
        assert xprompts == {}


def test_get_all_xprompts_file_overrides_project() -> None:
    """Test that file-based xprompts override project xprompts."""
    project_xprompt = XPrompt(name="test", content="From project")
    file_xprompt = XPrompt(name="test", content="From file")

    with (
        patch("sase.xprompt.loader.load_xprompts_by_source", return_value=[]),
        patch(
            "sase.xprompt.loader._load_xprompts_from_files",
            return_value={"test": file_xprompt},
        ),
        patch("sase.xprompt.loader._load_xprompts_from_internal", return_value={}),
        patch(
            "sase.xprompt.loader._load_xprompts_from_project",
            return_value={"test": project_xprompt},
        ),
    ):
        xprompts = get_all_xprompts(project="testproj")

    # File-based should win
    assert xprompts["test"].content == "From file"
