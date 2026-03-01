"""Tests for xprompt.loader config and file loading functions."""

import tempfile
from pathlib import Path
from unittest.mock import patch


from sase.xprompt.loader import (
    _load_xprompt_from_file,
    _load_xprompts_from_directory_config,
    get_all_xprompts,
)
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.models import XPrompt

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


# Tests for _load_xprompts_from_directory_config


def test_directory_config_simple_entries() -> None:
    """Test loading simple string entries from xprompts.yml."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yml"
        config_path.write_text('foo: "Hello from foo"\nbar: "Hello from bar"\n')

        result = _load_xprompts_from_directory_config(Path(tmp_dir))

        assert len(result) == 2
        assert result["foo"].content == "Hello from foo"
        assert result["bar"].content == "Hello from bar"
        assert result["foo"].source_path == str(config_path)


def test_directory_config_structured_entries() -> None:
    """Test loading structured entries with input and content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yml"
        config_path.write_text(
            'greet:\n  input: {name: word}\n  content: "Hello {{ name }}"\n'
        )

        result = _load_xprompts_from_directory_config(Path(tmp_dir))

        assert len(result) == 1
        assert result["greet"].content == "Hello {{ name }}"
        assert len(result["greet"].inputs) == 1
        assert result["greet"].inputs[0].name == "name"


def test_directory_config_yaml_extension() -> None:
    """Test that .yaml extension is also recognized."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yaml"
        config_path.write_text('baz: "Content from yaml"\n')

        result = _load_xprompts_from_directory_config(Path(tmp_dir))

        assert len(result) == 1
        assert result["baz"].content == "Content from yaml"


def test_directory_config_yml_preferred_over_yaml() -> None:
    """Test that .yml is preferred when both exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        (Path(tmp_dir) / "xprompts.yml").write_text('from_yml: "yml content"\n')
        (Path(tmp_dir) / "xprompts.yaml").write_text('from_yaml: "yaml content"\n')

        result = _load_xprompts_from_directory_config(Path(tmp_dir))

        assert "from_yml" in result
        assert "from_yaml" not in result


def test_directory_config_missing_file() -> None:
    """Test that missing config file returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = _load_xprompts_from_directory_config(Path(tmp_dir))
        assert result == {}


def test_directory_config_invalid_yaml() -> None:
    """Test that invalid YAML returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yml"
        config_path.write_text("invalid: yaml: [not closed\n")

        result = _load_xprompts_from_directory_config(Path(tmp_dir))
        assert result == {}


def test_directory_config_non_dict_yaml() -> None:
    """Test that non-dict YAML content returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yml"
        config_path.write_text("- item1\n- item2\n")

        result = _load_xprompts_from_directory_config(Path(tmp_dir))
        assert result == {}


def test_directory_config_source_path_correctness() -> None:
    """Test that source_path points to the config file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "xprompts.yml"
        config_path.write_text('test: "content"\n')

        result = _load_xprompts_from_directory_config(Path(tmp_dir))

        assert result["test"].source_path == str(config_path)


# Tests for priority: .md overrides config within same dir


def test_md_overrides_config_in_same_directory() -> None:
    """Test that .md files override xprompts.yml entries within the same dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()

        # Create config entry
        (search_dir / "xprompts.yml").write_text('foo: "From config"\n')

        # Create .md file with same name
        (search_dir / "foo.md").write_text("From md file")

        with patch(
            "sase.xprompt.loader.get_xprompt_search_paths",
            return_value=[search_dir],
        ):
            from sase.xprompt.loader import _load_xprompts_from_files

            result = _load_xprompts_from_files()

        assert result["foo"].content == "From md file"


def test_config_entries_coexist_with_md_files() -> None:
    """Test that config entries and .md files coexist when names differ."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()

        (search_dir / "xprompts.yml").write_text('from_config: "Config content"\n')
        (search_dir / "from_md.md").write_text("MD content")

        with patch(
            "sase.xprompt.loader.get_xprompt_search_paths",
            return_value=[search_dir],
        ):
            from sase.xprompt.loader import _load_xprompts_from_files

            result = _load_xprompts_from_files()

        assert result["from_config"].content == "Config content"
        assert result["from_md"].content == "MD content"


def test_higher_priority_dir_config_overrides_lower_dir_md() -> None:
    """Test that config from higher-priority dir overrides .md from lower dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        high_dir = Path(tmp_dir) / "high"
        low_dir = Path(tmp_dir) / "low"
        high_dir.mkdir()
        low_dir.mkdir()

        # Higher-priority dir has config entry
        (high_dir / "xprompts.yml").write_text('shared: "From high config"\n')

        # Lower-priority dir has .md file
        (low_dir / "shared.md").write_text("From low md")

        with patch(
            "sase.xprompt.loader.get_xprompt_search_paths",
            return_value=[high_dir, low_dir],
        ):
            from sase.xprompt.loader import _load_xprompts_from_files

            result = _load_xprompts_from_files()

        assert result["shared"].content == "From high config"


# Tests for get_all_xprompts integration


def test_get_all_xprompts_includes_directory_config_entries() -> None:
    """Test that get_all_xprompts includes entries from xprompts.yml."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()
        (search_dir / "xprompts.yml").write_text('cfg_entry: "From dir config"\n')

        with (
            patch(
                "sase.xprompt.loader.get_xprompt_search_paths",
                return_value=[search_dir],
            ),
            patch("sase.xprompt.loader.load_xprompts_by_source", return_value=[]),
            patch("sase.xprompt.loader._load_xprompts_from_internal", return_value={}),
        ):
            result = get_all_xprompts()

        assert "cfg_entry" in result
        assert result["cfg_entry"].content == "From dir config"


# Tests for _load_xprompts_from_config


# Tests for get_all_xprompts


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
