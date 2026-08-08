"""Tests for xprompt.loader config and file loading functions."""

import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch

from sase.xprompt.loader import (
    load_xprompt_from_file,
    load_xprompts_from_plugins,
    load_xprompts_from_default_files,
    load_skills_from_package,
    load_xprompts_from_internal,
    get_all_prompts,
    get_all_workflows,
    get_all_xprompts,
)
from sase.xprompt.loader_parsing import LocalXPromptNameError, parse_yaml_front_matter
from sase.xprompt.models import InputType, XPrompt

# Tests for load_xprompt_from_file


def testload_xprompt_from_file_without_front_matter() -> None:
    """Test loading xprompt file without front matter."""
    content = "Just some content without front matter"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = load_xprompt_from_file(temp_path)

        assert xprompt is not None
        # Name should be filename stem
        assert xprompt.name == temp_path.stem
        assert xprompt.inputs == []
        assert xprompt.content == content
    finally:
        temp_path.unlink()


def testload_xprompt_from_file_nonexistent() -> None:
    """Test loading nonexistent file returns None."""
    xprompt = load_xprompt_from_file(Path("/nonexistent/path.md"))
    assert xprompt is None


def testload_xprompt_from_file_with_skill_and_description() -> None:
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
        xprompt = load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.name == "my_skill"
        assert xprompt.description == "A useful skill"
        assert xprompt.skill is True
        assert xprompt.content == "Skill body content"
    finally:
        temp_path.unlink()


def testload_xprompt_from_file_with_skill_provider_list() -> None:
    """Test loading xprompt file with skill as provider list."""
    content = """---
name: hg_commit
skill: [gemini]
---
Commit with a VCS provider"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.skill == ["gemini"]
        assert xprompt.description is None
    finally:
        temp_path.unlink()


def testload_xprompt_from_file_log_skill_use_false() -> None:
    """Markdown frontmatter can disable the generated audit directive."""
    content = """---
name: quiet_skill
skill: true
log_skill_use: false
---
Skill body content"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.log_skill_use is False
    finally:
        temp_path.unlink()


def testload_xprompt_from_file_log_skill_use_defaults_true() -> None:
    """Markdown frontmatter defaults log_skill_use to True when absent."""
    content = """---
name: loud_skill
skill: true
---
Skill body content"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        temp_path = Path(f.name)

    try:
        xprompt = load_xprompt_from_file(temp_path)

        assert xprompt is not None
        assert xprompt.log_skill_use is True
    finally:
        temp_path.unlink()


def testload_xprompt_from_file_with_local_xprompts(tmp_path: Path) -> None:
    """Markdown xprompt frontmatter can define file-local helper xprompts."""
    path = tmp_path / "outer.md"
    path.write_text(
        "---\n"
        "input: {topic: text}\n"
        "xprompts:\n"
        "  _helper:\n"
        "    input: {audience: word}\n"
        '    content: "Explain {{ topic }} for {{ audience }}."\n'
        "---\n"
        "#_helper(devs)\n",
        encoding="utf-8",
    )

    xprompt = load_xprompt_from_file(path)

    assert xprompt is not None
    assert xprompt.name == "outer"
    assert xprompt.content == "#_helper(devs)\n"
    assert set(xprompt.local_xprompts) == {"_helper"}
    helper = xprompt.local_xprompts["_helper"]
    assert helper.content == "Explain {{ topic }} for {{ audience }}."
    assert helper.inputs[0].name == "audience"
    assert helper.source_path == str(path)


def testload_xprompt_from_file_rejects_bad_local_xprompt_name(
    tmp_path: Path,
) -> None:
    """Markdown-local helpers use the same underscore-name rule as prompts."""
    path = tmp_path / "outer.md"
    path.write_text(
        '---\nxprompts:\n  helper: "not local-scoped"\n---\nbody\n',
        encoding="utf-8",
    )

    try:
        load_xprompt_from_file(path)
    except LocalXPromptNameError as exc:
        assert "helper" in str(exc)
    else:
        raise AssertionError("Expected LocalXPromptNameError")


def testload_xprompts_from_plugins_with_local_xprompts(
    tmp_path: Path, monkeypatch
) -> None:
    """Plugin markdown xprompts preserve frontmatter-local helpers too."""
    package_dir = tmp_path / "plugin_pkg"
    xprompts_dir = package_dir / "xprompts"
    xprompts_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (xprompts_dir / "outer.md").write_text(
        '---\nxprompts:\n  _helper: "Plugin-local helper"\n---\n#_helper\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("plugin_pkg")

    with (
        patch(
            "sase.xprompt.loader_sources.discover_plugin_resources",
            return_value=[module],
        ),
        patch("sase.xprompt.loader_sources.is_plugin_disabled", return_value=False),
    ):
        result = load_xprompts_from_plugins()

    assert result["outer"].content == "#_helper\n"
    assert result["outer"].local_xprompts["_helper"].content == "Plugin-local helper"


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
            "sase.xprompt.loader_sources.get_xprompt_search_paths",
            return_value=[high_dir, low_dir],
        ):
            from sase.xprompt.loader import load_xprompts_from_files

            result = load_xprompts_from_files()

        assert result["shared"].content == "From high dir"


def test_canonical_project_xprompt_overrides_legacy_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    canonical = tmp_path / "sase" / "xprompts"
    hidden = tmp_path / ".xprompts"
    visible = tmp_path / "xprompts"
    for directory, content in (
        (canonical, "canonical"),
        (hidden, "hidden legacy"),
        (visible, "visible legacy"),
    ):
        directory.mkdir(parents=True)
        (directory / "shared.md").write_text(content, encoding="utf-8")
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    from sase.xprompt.loader import load_xprompts_from_files

    result = load_xprompts_from_files(project="demo")

    assert result["demo/shared"].content == "canonical"
    assert result["demo/shared"].source_path == str(canonical / "shared.md")


# Tests for get_all_xprompts integration


def test_get_all_xprompts_includes_md_files() -> None:
    """Test that get_all_xprompts includes .md files from search dirs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        search_dir = Path(tmp_dir) / ".xprompts"
        search_dir.mkdir()
        (search_dir / "hello.md").write_text("Hello from md")

        with (
            patch(
                "sase.xprompt.loader_sources.get_xprompt_search_paths",
                return_value=[search_dir],
            ),
            patch(
                "sase.xprompt.loader_sources.load_xprompts_by_source", return_value=[]
            ),
            patch("sase.xprompt.loader.load_xprompts_from_internal", return_value={}),
        ):
            result = get_all_xprompts()

        assert "hello" in result
        assert result["hello"].content == "Hello from md"


def testload_xprompts_from_default_files_loads_fixture(tmp_path: Path) -> None:
    """Package default_xprompts markdown files are built-in xprompts."""
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    fixture = default_dir / "fixture_default.md"
    fixture.write_text(
        "---\n"
        "description: Fixture default xprompt.\n"
        "input:\n"
        "  - name: prompt\n"
        "    type: text\n"
        "    description: Prompt body.\n"
        "---\n"
        "Fixture default body for {{ prompt }}.\n",
        encoding="utf-8",
    )

    with patch(
        "sase.xprompt.loader_sources.get_sase_package_default_xprompts_dir",
        return_value=default_dir,
    ):
        result = load_xprompts_from_default_files()

    xprompt = result["fixture_default"]
    assert xprompt.name == "fixture_default"
    assert xprompt.source_path == str(fixture)
    assert xprompt.description == "Fixture default xprompt."
    assert xprompt.content == "Fixture default body for {{ prompt }}.\n"
    assert len(xprompt.inputs) == 1
    assert xprompt.inputs[0].name == "prompt"
    assert xprompt.inputs[0].type is InputType.TEXT


def testload_xprompts_from_internal_excludes_packaged_skills() -> None:
    """Packaged skills are their own source, not part of the xprompt scan."""
    result = load_xprompts_from_internal()

    assert "sase_plan" not in result
    assert "skills/sase_plan" not in result
    assert "split_file" in result


def test_load_skills_from_package_namespaces_the_xprompt_reference() -> None:
    """Packaged skills keep ``foo`` as the skill name under ``skill/foo``."""
    result = load_skills_from_package()

    assert "skill/sase_plan" in result
    assert "skill/sase_questions" in result
    # The Jinja frame ships beside the sources but is a template, not a skill.
    assert "skill/SKILL.frame.template" not in result

    plan = result["skill/sase_plan"]
    assert plan.name == "skill/sase_plan"
    assert plan.skill_name == "sase_plan"
    assert plan.skill is True
    assert plan.description is not None
    assert plan.source_path.endswith("sase/xprompts/skills/sase_plan.md")


def testload_xprompts_from_internal_includes_split_file() -> None:
    """Package xprompts include the built-in split_file markdown prompt."""
    result = load_xprompts_from_internal()

    assert "split_file" in result
    xprompt = result["split_file"]
    assert xprompt.name == "split_file"
    assert (
        xprompt.description
        == "Split a large Python source file into smaller import-safe files."
    )
    assert "xprompts/split_file.md" in xprompt.source_path
    assert [arg.name for arg in xprompt.inputs] == ["file_path"]
    assert xprompt.inputs[0].type == InputType.PATH


def testload_xprompts_from_internal_includes_tribe() -> None:
    result = load_xprompts_from_internal()

    assert "tribe" in result
    xprompt = result["tribe"]
    assert xprompt.name == "tribe"
    assert [arg.name for arg in xprompt.inputs] == ["tribe"]
    assert xprompt.content.strip() == "%id(tribe={{ tribe }})"


def test_internal_fork_workflow_name_uses_agent_type() -> None:
    """The built-in fork xprompt advertises agent-name completion."""
    workflow = get_all_workflows()["fork"]
    inputs = [arg for arg in workflow.inputs if not arg.is_step_input]

    assert [arg.name for arg in inputs] == ["name"]
    assert inputs[0].type == InputType.AGENT
    assert inputs[0].default is None


def test_default_file_xprompt_not_project_namespaced(
    tmp_path: Path, monkeypatch
) -> None:
    """Default file-backed xprompts stay global even when a project is set."""
    monkeypatch.chdir(tmp_path)
    default_dir = tmp_path / "default_xprompts"
    default_dir.mkdir()
    fixture = default_dir / "fixture_default.md"
    fixture.write_text("Fixture default body.\n", encoding="utf-8")

    with (
        patch("sase.xprompt.loader_sources.load_xprompts_by_source", return_value=[]),
        patch("sase.xprompt.loader.load_xprompts_from_internal", return_value={}),
        patch("sase.xprompt.loader.load_xprompts_from_plugins", return_value={}),
        patch("sase.xprompt.loader.load_xprompts_from_project", return_value={}),
        patch(
            "sase.xprompt.loader_sources.get_xprompt_search_paths",
            return_value=[tmp_path / ".xprompts", tmp_path / "xprompts"],
        ),
        patch(
            "sase.xprompt.loader_sources.get_sase_package_default_xprompts_dir",
            return_value=default_dir,
        ),
    ):
        result = get_all_xprompts(project="sase")

    assert not (tmp_path / "xprompts" / "fixture_default.md").exists()
    assert "fixture_default" in result
    assert "sase/fixture_default" not in result
    assert result["fixture_default"].source_path == str(fixture)


def test_config_xprompt_overrides_default_file_xprompt(tmp_path: Path) -> None:
    """Config-defined xprompts keep overriding package default markdown files."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.get_local_config_path", return_value=None),
        patch(
            "sase.xprompt.loader_sources.load_xprompts_by_source",
            return_value=[("config", {"research_swarm": "From config"})],
        ),
        patch("sase.xprompt.loader.load_xprompts_from_internal", return_value={}),
        patch("sase.xprompt.loader.load_xprompts_from_plugins", return_value={}),
        patch("sase.xprompt.loader.detect_project", return_value=None),
        patch("sase.xprompt.loader_sources.get_xprompt_search_paths", return_value=[]),
    ):
        result = get_all_xprompts(project=None)

    assert result["research_swarm"].content == "From config"
    assert result["research_swarm"].source_path == "config"


def test_review_xprompts_load_from_default_config(tmp_path: Path) -> None:
    """Default config xprompts load as built-ins with parsed inputs."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.get_local_config_path", return_value=None),
        patch("sase.main.plugin_discovery.is_plugin_disabled", return_value=True),
        patch("sase.xprompt.loader.detect_project", return_value=None),
        patch("sase.xprompt.loader_sources.get_xprompt_search_paths", return_value=[]),
        patch("sase.xprompt.loader.load_xprompts_from_internal", return_value={}),
        patch("sase.xprompt.loader.load_xprompts_from_plugins", return_value={}),
        patch("sase.xprompt.workflow_loader.get_all_workflows", return_value={}),
    ):
        prompts = get_all_prompts(project=None)

    assert "review" in prompts
    assert "prompt/review" in prompts
    assert prompts["review"].source_path == "default_config"
    assert prompts["prompt/review"].source_path == "default_config"

    review_prompt = prompts["prompt/review"]
    assert len(review_prompt.inputs) == 1
    prompt_input = review_prompt.inputs[0]
    assert prompt_input.name == "prompt"
    assert prompt_input.type is InputType.TEXT

    review_body = prompts["review"].steps[0].prompt_part or ""
    assert "fix any bugs" in review_body

    body = review_prompt.steps[0].prompt_part or ""
    assert "## THE PROMPT" in body
    assert "{{ prompt }}" in body


# Tests for load_xprompts_from_project


def load_xprompts_from_project_with_base(
    project: str, base_config_dir: Path
) -> dict[str, XPrompt]:
    """Helper to test project loading with a custom base directory.

    This replicates the logic of load_xprompts_from_project but allows
    specifying a custom base directory for testing.
    """
    project_dir = base_config_dir / ".config" / "sase" / "xprompts" / project
    if not project_dir.is_dir():
        return {}

    xprompts: dict[str, XPrompt] = {}
    for md_file in project_dir.glob("*.md"):
        if md_file.is_file():
            xprompt = load_xprompt_from_file(md_file)
            if xprompt:
                namespaced_name = f"{project}/{xprompt.name}"
                xprompts[namespaced_name] = XPrompt(
                    name=namespaced_name,
                    content=xprompt.content,
                    inputs=xprompt.inputs,
                    source_path=xprompt.source_path,
                )
    return xprompts


def testload_xprompts_from_project_nonexistent_dir() -> None:
    """Test that nonexistent project directory returns empty dict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        xprompts = load_xprompts_from_project_with_base(
            "nonexistent_project", Path(tmp_dir)
        )
        assert xprompts == {}


def test_get_all_xprompts_file_overrides_project() -> None:
    """Test that file-based xprompts override project xprompts."""
    project_xprompt = XPrompt(name="test", content="From project")
    file_xprompt = XPrompt(name="test", content="From file")

    with (
        patch("sase.xprompt.loader_sources.load_xprompts_by_source", return_value=[]),
        patch(
            "sase.xprompt.loader.load_xprompts_from_files",
            return_value={"test": file_xprompt},
        ),
        patch("sase.xprompt.loader.load_xprompts_from_internal", return_value={}),
        patch(
            "sase.xprompt.loader.load_xprompts_from_project",
            return_value={"test": project_xprompt},
        ),
    ):
        xprompts = get_all_xprompts(project="testproj")

    # File-based should win
    assert xprompts["test"].content == "From file"
