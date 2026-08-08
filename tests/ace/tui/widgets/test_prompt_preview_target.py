"""Tests for prompt preview token detection and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewError,
    PreviewToken,
    detect_preview_target_at_cursor,
    resolve_preview_target,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _detect(text: str, needle: str) -> PreviewToken | None:
    return detect_preview_target_at_cursor(text, text.index(needle))


def test_detects_xprompt_reference_name_and_arg_region() -> None:
    text = "run #foo:bar now"

    token = _detect(text, "#foo")
    assert token == PreviewToken("xprompt", "#foo:bar", "foo", 4, 12)

    token = _detect(text, "bar")
    assert token == PreviewToken("xprompt", "#foo:bar", "foo", 4, 12)


def test_detects_project_xprompt_reference() -> None:
    token = _detect("run #proj/foo now", "foo")
    assert token == PreviewToken("xprompt", "#proj/foo", "proj/foo", 4, 13)


def test_detects_at_prefixed_and_bare_file_paths() -> None:
    at_token = _detect("open @src/main.py please", "@")
    assert at_token == PreviewToken("file", "@src/main.py", "src/main.py", 5, 17)

    bare_token = _detect("open docs/readme.md please", "docs")
    assert bare_token == PreviewToken(
        "file",
        "docs/readme.md",
        "docs/readme.md",
        5,
        19,
    )


def test_detects_home_and_dot_relative_file_paths() -> None:
    home_token = _detect("open ~/notes/today.md", "~")
    assert home_token and home_token.kind == "file"
    assert home_token.target == "~/notes/today.md"

    dot_token = _detect("open .sase/xcmds/fix.diff", ".sase")
    assert dot_token and dot_token.kind == "file"
    assert dot_token.target == ".sase/xcmds/fix.diff"


def test_detect_boundaries_are_start_inclusive_end_exclusive() -> None:
    text = "run #foo"
    start = text.index("#")
    end = start + len("#foo")

    assert detect_preview_target_at_cursor(text, start) is not None
    assert detect_preview_target_at_cursor(text, end) is None


def test_detect_returns_none_for_plain_prose() -> None:
    assert detect_preview_target_at_cursor("nothing previewable here", 4) is None


def test_xprompt_detection_takes_precedence_over_file_like_overlap() -> None:
    text = "run #foo/bar.md now"
    token = _detect(text, "foo")
    assert token and token.kind == "xprompt"
    assert token.target == "foo/bar"


def test_detects_known_slash_skill_before_absolute_file() -> None:
    text = "use /sase_plan now"
    known = frozenset({"sase_plan"})
    start = text.index("/")
    end = start + len("/sase_plan")

    token = detect_preview_target_at_cursor(
        text,
        start,
        known_skills=known,
    )

    assert token == PreviewToken(
        "xprompt",
        "/sase_plan",
        "sase_plan",
        start,
        end,
        "/",
    )
    assert (
        detect_preview_target_at_cursor(
            text,
            end - 1,
            known_skills=known,
        )
        == token
    )
    assert detect_preview_target_at_cursor(text, end, known_skills=known) is None


def test_slash_skill_detection_rejects_unknown_path_like_and_protected_text() -> None:
    known = frozenset({"sase_plan"})

    unknown = _detect("open /unknown", "/")
    assert unknown is not None and unknown.kind == "file"

    path_like = "open /sase_plan/child"
    token = detect_preview_target_at_cursor(
        path_like,
        path_like.index("sase_plan"),
        known_skills=known,
    )
    assert token is not None and token.kind == "file"

    for text in (
        "`/sase_plan`",
        "```text\n/sase_plan\n```",
        "%xprompts_enabled:false\n/sase_plan\n%xprompts_enabled:true",
    ):
        assert (
            detect_preview_target_at_cursor(
                text,
                text.index("sase_plan"),
                known_skills=known,
            )
            is None
        )


def test_resolves_xprompt_from_source_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("---\ndescription: Review\n---\nBody\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="fallback",
            source_path=str(source),
        ),
    )

    payload = resolve_preview_target(
        PreviewToken("xprompt", "#review", "review", 0, 7),
        project=None,
        base_dir=str(tmp_path),
    )

    assert payload.kind_label == "xprompt"
    assert payload.title == "#review"
    assert payload.source_path == str(source)
    assert payload.content.startswith("---\ndescription")
    assert payload.lexer == "markdown"


def test_resolves_skill_label_from_xprompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="Skill body",
            source_path="config",
            skill=True,
        ),
    )

    payload = resolve_preview_target(
        PreviewToken("xprompt", "#skill", "skill", 0, 6),
        project=None,
        base_dir=".",
    )

    assert payload.kind_label == "skill"
    assert payload.content == "Skill body"
    assert payload.lexer == "markdown"


def test_resolves_slash_skill_with_slash_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(
            name=name,
            content="Skill body",
            source_path="config",
            skill=True,
        ),
    )

    payload = resolve_preview_target(
        PreviewToken("xprompt", "/sase_plan", "sase_plan", 0, 10, "/"),
        project="sase",
        base_dir=".",
    )

    assert payload.kind_label == "skill"
    assert payload.icon == "/"
    assert payload.title == "/sase_plan"


def test_slash_skill_resolution_looks_up_the_skill_reference_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/foo`` resolves through the canonical ``skill/foo`` reference."""
    looked_up: list[str] = []

    def _lookup(name: str, project: str | None = None) -> XPrompt:
        looked_up.append(name)
        return XPrompt(
            name=name,
            content="Skill body",
            source_path="config",
            skill=True,
            skill_name="sase_plan",
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        _lookup,
    )

    resolve_preview_target(
        PreviewToken("xprompt", "/sase_plan", "sase_plan", 0, 10, "/"),
        project=None,
        base_dir=".",
    )

    assert looked_up == ["skill/sase_plan"]


def test_slash_skill_resolution_rejects_stale_non_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: XPrompt(name=name, content="Not a skill"),
    )

    with pytest.raises(PreviewError, match="No skill named '/sase_plan' found"):
        resolve_preview_target(
            PreviewToken("xprompt", "/sase_plan", "sase_plan", 0, 10, "/"),
            project=None,
            base_dir=".",
        )


def test_resolves_workflow_fallback_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = Workflow(
        name="ship",
        description="Ship the thing",
        steps=[
            WorkflowStep(name="prep", bash="just test"),
            WorkflowStep(name="run", agent="Implement the fix"),
        ],
        source_path="local_config",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: workflow,
    )

    payload = resolve_preview_target(
        PreviewToken("xprompt", "#ship", "ship", 0, 5),
        project="demo",
        base_dir=".",
    )

    assert payload.kind_label == "workflow"
    assert "# Workflow: ship" in payload.content
    assert "1. [bash] prep: just test" in payload.content
    assert "2. [agent] run: Implement the fix" in payload.content


def test_missing_xprompt_raises_distinct_preview_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview_target.get_xprompt_or_workflow",
        lambda name, project=None: None,
    )

    with pytest.raises(PreviewError, match="No xprompt or skill named '#missing'"):
        resolve_preview_target(
            PreviewToken("xprompt", "#missing", "missing", 0, 8),
            project=None,
            base_dir=".",
        )


def test_resolves_file_preview(tmp_path: Path) -> None:
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")

    payload = resolve_preview_target(
        PreviewToken("file", "src/main.py", "src/main.py", 0, 11),
        project=None,
        base_dir=str(tmp_path),
    )

    assert payload.kind_label == "file"
    assert payload.source_path == str(source)
    assert payload.content == "print('hello')\n"
    assert payload.lexer == "python"


def test_missing_file_raises_distinct_preview_error(tmp_path: Path) -> None:
    with pytest.raises(PreviewError, match="File not found: src/missing.py"):
        resolve_preview_target(
            PreviewToken("file", "src/missing.py", "src/missing.py", 0, 14),
            project=None,
            base_dir=str(tmp_path),
        )


def test_directory_and_binary_files_raise_preview_errors(tmp_path: Path) -> None:
    directory = tmp_path / "src"
    directory.mkdir()
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"abc\x00def")

    with pytest.raises(PreviewError, match="is a directory, not a file"):
        resolve_preview_target(
            PreviewToken("file", "src", "src", 0, 3),
            project=None,
            base_dir=str(tmp_path),
        )

    with pytest.raises(PreviewError, match="Cannot preview binary file: blob.bin"):
        resolve_preview_target(
            PreviewToken("file", "blob.bin", "blob.bin", 0, 8),
            project=None,
            base_dir=str(tmp_path),
        )
