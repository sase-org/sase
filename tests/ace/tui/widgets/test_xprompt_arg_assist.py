"""Tests for pure TUI xprompt argument assist helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptInputHint,
    append_input_args,
    append_input_hints,
    build_xprompt_assist_entries,
    input_label,
    named_args_skeleton,
    required_inputs,
    visible_inputs,
)
from sase.xprompt.models import UNSET, InputArg, InputType, OutputSpec, XPrompt
from sase.xprompt.models import MemoryType


def _make_xprompt(
    name: str,
    *,
    source_path: str | None = "config",
    inputs: list[InputArg] | None = None,
    content: str = "body",
    skill: bool | list[str] | None = None,
    description: str | None = None,
    memory_type: MemoryType | None = None,
) -> XPrompt:
    return XPrompt(
        name=name,
        content=content,
        inputs=inputs or [],
        source_path=source_path,
        skill=skill,
        description=description,
        memory_type=memory_type,
    )


def test_assist_adapter_preserves_structured_catalog_fields(tmp_path: Path) -> None:
    xp = _make_xprompt(
        "typed",
        skill=True,
        description="Run typed inputs.",
        inputs=[
            InputArg(name="required_word", type=InputType.WORD, default=UNSET),
            InputArg(name="string_default", type=InputType.LINE, default="secret"),
            InputArg(name="null_default", type=InputType.TEXT, default=None),
            InputArg(name="count", type=InputType.INT, default=3),
            InputArg(
                name="enabled",
                type=InputType.BOOL,
                default=False,
                description="Whether to enable the operation.",
            ),
            InputArg(
                name="step_output",
                type=InputType.LINE,
                default=UNSET,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            ),
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"typed": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        entries = build_xprompt_assist_entries()

    entry = entries[0]
    assert entry.name == "typed"
    assert entry.description == "Run typed inputs."
    assert entry.insertion == "#typed"
    assert entry.reference_prefix == "#"
    assert entry.kind == "xprompt"
    assert entry.memory_type is None
    assert entry.input_signature == (
        "(required_word: word, string_default?: line, null_default?: text, "
        "count?: int, enabled?: bool)"
    )
    assert entry.content_preview == "body"
    assert entry.is_skill is True
    assert [
        (inp.name, inp.type, inp.required, inp.default_display, inp.position)
        for inp in entry.inputs
    ] == [
        ("required_word", "word", True, None, 0),
        ("string_default", "line", False, None, 1),
        ("null_default", "text", False, None, 2),
        ("count", "int", False, "3", 3),
        ("enabled", "bool", False, "false", 4),
    ]
    assert entry.inputs[-1].description == "Whether to enable the operation."
    assert [inp.name for inp in visible_inputs(entry)] == [
        "required_word",
        "string_default",
        "null_default",
        "count",
        "enabled",
    ]
    assert [inp.name for inp in required_inputs(entry)] == ["required_word"]


def test_assist_adapter_preserves_memory_identity(tmp_path: Path) -> None:
    source = tmp_path / "sase" / "memory" / "glossary.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\ntype: short\n---\nbody\n")
    xp = _make_xprompt(
        "memory/glossary",
        source_path=str(source),
        description="Glossary terms.",
        memory_type="short",
    )

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"memory/glossary": xp},
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entries = build_xprompt_assist_entries()

    entry = entries[0]
    assert entry.name == "memory/glossary"
    assert entry.insertion == "#memory/glossary"
    assert entry.kind == "memory"
    assert entry.memory_type == "short"
    assert entry.is_skill is False
    assert entry.skill_name is None


def test_assist_adapter_filters_project_entries(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    project_source = ws / ".xprompts" / "local.md"
    project_source.parent.mkdir()
    project_source.write_text("local")
    global_xp = _make_xprompt("global")
    project_xp = _make_xprompt("local", source_path=str(project_source))
    other_xp = _make_xprompt("other", source_path=str(tmp_path / "other.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"global": global_xp},
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": ws, "other": tmp_path / "other"},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            side_effect=[{"local": project_xp}, {"other": other_xp}],
        ),
        patch(
            "sase.xprompt.catalog.load_project_file_xprompts",
            return_value={},
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        entries = build_xprompt_assist_entries(project="sase")

    assert [entry.name for entry in entries] == ["global", "local"]


def test_entry_with_only_step_inputs_has_no_user_facing_hints() -> None:
    xp = _make_xprompt(
        "step_only",
        inputs=[
            InputArg(
                name="prior",
                type=InputType.LINE,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            )
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"step_only": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert entry.input_signature is None
    assert entry.inputs == ()
    assert named_args_skeleton(entry) == "#step_only"


def test_input_label_formatting_and_rich_rendering() -> None:
    xp = _make_xprompt(
        "rendered",
        inputs=[
            InputArg(name="path", type=InputType.PATH),
            InputArg(name="count", type=InputType.INT, default=2),
            InputArg(name="maybe", type=InputType.LINE, default=None),
        ],
    )
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"rendered": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert [input_label(inp) for inp in entry.inputs] == [
        "path: path",
        "count?: int",
        "maybe?: line",
    ]

    text = Text("rendered")
    append_input_hints(text, entry.inputs)
    assert (
        text.plain
        == "rendered\n     path: path\n     count?: int=2\n     maybe?: line?"
    )


def test_append_input_hints_can_render_descriptions() -> None:
    text = Text("rendered")
    append_input_hints(
        text,
        (
            XPromptInputHint(
                name="path",
                type="path",
                required=True,
                default_display=None,
                position=0,
                description="File to inspect.",
            ),
        ),
        include_descriptions=True,
    )

    assert text.plain == "rendered\n     path: path - File to inspect."


def test_append_input_args_preserves_modal_style_for_input_args() -> None:
    text = Text("example")
    append_input_args(
        text,
        [
            InputArg(name="path", type=InputType.PATH),
            InputArg(name="count", type=InputType.INT, default=2),
        ],
    )

    assert text.plain == "example\n     path\n     count=2"
    spans = [(span.start, span.end, span.style) for span in text.spans]
    assert spans == [
        (13, 17, "#D7AF87"),
        (23, 28, "dim #D7AF87"),
        (28, 30, "dim #888888"),
    ]
