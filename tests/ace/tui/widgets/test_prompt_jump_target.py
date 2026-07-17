"""Tests for prompt jump-to-definition detection and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets._prompt_jump_target import (
    JumpError,
    JumpToken,
    build_jump_editor_argv,
    detect_jump_target_at_cursor,
    resolve_jump_target,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _detect(text: str, needle: str) -> JumpToken | None:
    return detect_jump_target_at_cursor(text, text.index(needle))


def test_detects_xprompt_reference_and_file_line_suffix() -> None:
    assert _detect("run #foo:bar now", "bar") == JumpToken(
        "xprompt",
        "#foo:bar",
        "foo",
        None,
        None,
        4,
        12,
    )

    assert _detect("open @src/main.py:12:3", "src") == JumpToken(
        "file",
        "@src/main.py:12:3",
        "src/main.py",
        12,
        3,
        5,
        22,
    )


def test_detects_cursor_on_file_line_suffix() -> None:
    token = _detect("open docs/readme.md:42 now", "42")
    assert token == JumpToken(
        "file",
        "docs/readme.md:42",
        "docs/readme.md",
        42,
        None,
        5,
        22,
    )


def test_detects_known_slash_skill_through_shared_preview_detection() -> None:
    text = "use /sase_plan now"
    start = text.index("/")

    token = detect_jump_target_at_cursor(
        text,
        text.index("plan"),
        known_skills=frozenset({"sase_plan"}),
    )

    assert token == JumpToken(
        "xprompt",
        "/sase_plan",
        "sase_plan",
        None,
        None,
        start,
        start + len("/sase_plan"),
        "/",
    )


def test_detect_returns_none_for_plain_prose() -> None:
    assert detect_jump_target_at_cursor("nothing jumpable here", 4) is None


def test_resolves_loadable_markdown_xprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("---\ndescription: Review\n---\nBody\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="fallback",
            source_path=str(source),
        ),
    )

    target = resolve_jump_target(
        JumpToken("xprompt", "#review", "review", None, None, 0, 7),
        project=None,
        base_dir=str(tmp_path),
    )

    assert target.kind_label == "xprompt"
    assert target.title == "#review"
    assert target.source_path == str(source)
    assert target.line == 4
    assert target.col == 1
    assert target.loadable_markdown == source.read_text(encoding="utf-8")


def test_resolves_skill_label_from_xprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "skill.md"
    source.write_text("Skill body\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="Skill body",
            source_path=str(source),
            skill=True,
        ),
    )

    target = resolve_jump_target(
        JumpToken("xprompt", "#skill", "skill", None, None, 0, 6),
        project=None,
        base_dir=str(tmp_path),
    )

    assert target.kind_label == "skill"
    assert target.loadable_markdown == "Skill body\n"


def test_resolves_slash_skill_to_same_definition_with_slash_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "skill.md"
    source.write_text("---\ndescription: Plan\n---\nSkill body\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="Skill body",
            source_path=str(source),
            skill=True,
        ),
    )

    target = resolve_jump_target(
        JumpToken(
            "xprompt",
            "/sase_plan",
            "sase_plan",
            None,
            None,
            0,
            10,
            "/",
        ),
        project="sase",
        base_dir=str(tmp_path),
    )

    assert target.kind_label == "skill"
    assert target.icon == "/"
    assert target.title == "/sase_plan"
    assert target.source_path == str(source)
    assert target.line == 4
    assert target.col == 1
    assert target.loadable_markdown == source.read_text(encoding="utf-8")
    assert target.is_editable is True


def test_slash_jump_rejects_stale_non_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(name=name, content="Not a skill"),
    )

    with pytest.raises(JumpError, match="No skill named '/sase_plan' found"):
        resolve_jump_target(
            JumpToken(
                "xprompt",
                "/sase_plan",
                "sase_plan",
                None,
                None,
                0,
                10,
                "/",
            ),
            project=None,
            base_dir=".",
        )


def test_resolves_yaml_workflow_definition_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "flows.yml"
    source.write_text(
        "xprompts:\n  helper: ignored\nworkflows:\n  ship:\n    steps: []\n",
        encoding="utf-8",
    )
    workflow = Workflow(
        name="ship",
        steps=[WorkflowStep(name="run", agent="Ship it")],
        source_path=str(source),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: workflow,
    )

    target = resolve_jump_target(
        JumpToken("xprompt", "#ship", "ship", None, None, 0, 5),
        project="demo",
        base_dir=str(tmp_path),
    )

    assert target.kind_label == "workflow"
    assert target.source_path == str(source)
    assert target.loadable_markdown is None
    assert target.line == 4
    assert target.col == 3


def test_resolves_config_source_to_real_yaml_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sase.yml"
    source.write_text("xprompts:\n  review:\n    content: Body\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="Body",
            source_path="config",
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_helpers.resolve_source_to_file_path",
        lambda source_path: str(source) if source_path == "config" else None,
    )

    target = resolve_jump_target(
        JumpToken("xprompt", "#review", "review", None, None, 0, 7),
        project=None,
        base_dir=str(tmp_path),
    )

    assert target.source_path == str(source)
    assert target.loadable_markdown == "Body\n"
    assert target.line == 1


def test_missing_xprompt_and_definition_file_raise_distinct_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: None,
    )

    with pytest.raises(JumpError, match="No xprompt or skill named '#missing'"):
        resolve_jump_target(
            JumpToken("xprompt", "#missing", "missing", None, None, 0, 8),
            project=None,
            base_dir=".",
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(name=name, content="", source_path=None),
    )
    with pytest.raises(JumpError, match="No definition file found for #builtin"):
        resolve_jump_target(
            JumpToken("xprompt", "#builtin", "builtin", None, None, 0, 8),
            project=None,
            base_dir=".",
        )


def test_resolves_file_target_and_missing_directory_errors(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")

    target = resolve_jump_target(
        JumpToken("file", "src/main.py:9:2", "src/main.py", 9, 2, 0, 16),
        project=None,
        base_dir=str(tmp_path),
    )

    assert target.kind_label == "file"
    assert target.source_path == str(source)
    assert target.line == 9
    assert target.col == 2
    assert target.loadable_markdown is None

    with pytest.raises(JumpError, match="File not found: src/missing.py"):
        resolve_jump_target(
            JumpToken("file", "src/missing.py", "src/missing.py", None, None, 0, 14),
            project=None,
            base_dir=str(tmp_path),
        )

    with pytest.raises(JumpError, match="is a directory, not a file"):
        resolve_jump_target(
            JumpToken("file", "src", "src", None, None, 0, 3),
            project=None,
            base_dir=str(tmp_path),
        )


def test_build_jump_editor_argv_positions_vim_family_only() -> None:
    assert build_jump_editor_argv("nvim", "/tmp/a.md", 5, 7) == [
        "nvim",
        "-c",
        "call cursor(5, 7)",
        "/tmp/a.md",
    ]
    assert build_jump_editor_argv("/usr/bin/vim", "/tmp/a.md", 5, None) == [
        "/usr/bin/vim",
        "-c",
        "call cursor(5, 1)",
        "/tmp/a.md",
    ]
    assert build_jump_editor_argv("code", "/tmp/a.md", 5, 7) == [
        "code",
        "/tmp/a.md",
    ]
    assert build_jump_editor_argv("code --wait", "/tmp/a.md", 5, 7) == [
        "code",
        "--wait",
        "/tmp/a.md",
    ]
    assert build_jump_editor_argv("nvim --clean", "/tmp/a.md", 5, 7) == [
        "nvim",
        "--clean",
        "-c",
        "call cursor(5, 7)",
        "/tmp/a.md",
    ]
    assert build_jump_editor_argv("nvim", "/tmp/a.md", None, 7) == [
        "nvim",
        "/tmp/a.md",
    ]
