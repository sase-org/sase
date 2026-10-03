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
    input_default_suffix,
    input_label,
    named_args_skeleton,
    required_inputs,
    visible_inputs,
    xprompt_assist_entry_from_workflow,
)
from sase.macro.models import UNSET, InputArg, InputType, OutputSpec, Macro
from sase.macro.models import MemoryType
from sase.macro.workflow_models import Workflow, WorkflowStep


def _make_xprompt(
    name: str,
    *,
    source_path: str | None = "config",
    inputs: list[InputArg] | None = None,
    content: str = "body",
    skill: bool | list[str] | None = None,
    description: str | None = None,
    memory_type: MemoryType | None = None,
) -> Macro:
    return Macro(
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
        patch("sase.macro.catalog.get_all_macros", return_value={"typed": xp}),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.macro.catalog.get_sase_package_macros_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        entries = build_xprompt_assist_entries()

    entry = entries[0]
    assert entry.name == "typed"
    assert entry.description == "Run typed inputs."
    assert entry.insertion == "#typed"
    assert entry.reference_prefix == "#"
    assert entry.kind == "macro"
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
        ("string_default", "line", False, "secret", 1),
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
    source.write_text("---\ntype: core\n---\nbody\n")
    xp = _make_xprompt(
        "memory/glossary",
        source_path=str(source),
        description="Glossary terms.",
        memory_type="core",
    )

    with (
        patch(
            "sase.macro.catalog.get_all_macros",
            return_value={"memory/glossary": xp},
        ),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
    ):
        entries = build_xprompt_assist_entries()

    entry = entries[0]
    assert entry.name == "memory/glossary"
    assert entry.insertion == "#memory/glossary"
    assert entry.kind == "memory"
    assert entry.memory_type == "core"
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
            "sase.macro.catalog.get_all_macros",
            return_value={"global": global_xp},
        ),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.macro.catalog.get_known_project_workspaces",
            return_value={"sase": ws, "other": tmp_path / "other"},
        ),
        patch(
            "sase.macro.catalog.load_project_local_macros",
            side_effect=[{"local": project_xp}, {"other": other_xp}],
        ),
        patch(
            "sase.macro.catalog.load_project_file_macros",
            return_value={},
        ),
        patch(
            "sase.macro.catalog.get_sase_package_macros_dir",
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
        patch("sase.macro.catalog.get_all_macros", return_value={"step_only": xp}),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
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
        patch("sase.macro.catalog.get_all_macros", return_value={"rendered": xp}),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
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


def test_string_default_renders_in_prompt_bar_hints(tmp_path: Path) -> None:
    xp = _make_xprompt(
        "split_epic_like",
        inputs=[InputArg(name="lang", type=InputType.WORD, default="Rust")],
    )
    with (
        patch(
            "sase.macro.catalog.get_all_macros",
            return_value={"split_epic_like": xp},
        ),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert entry.inputs[0].default_display == "Rust"
    text = Text("split_epic_like")
    append_input_hints(text, entry.inputs)
    assert "lang?: word=Rust" in text.plain


def test_catalog_and_workflow_adapters_agree_on_string_defaults(
    tmp_path: Path,
) -> None:
    inputs = [
        InputArg(name="lang", type=InputType.WORD, default="Rust"),
        InputArg(name="count", type=InputType.INT, default=3),
    ]
    xp = _make_xprompt("typed", inputs=list(inputs))
    workflow = Workflow(
        name="typed",
        steps=[WorkflowStep(name="main", agent="Do it")],
        source_path="config",
        inputs=list(inputs),
    )
    with (
        patch("sase.macro.catalog.get_all_macros", return_value={"typed": xp}),
        patch("sase.macro.catalog.get_all_workflows", return_value={}),
        patch("sase.macro.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.macro.catalog.get_sase_package_macros_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        catalog_entry = build_xprompt_assist_entries()[0]
    workflow_entry = xprompt_assist_entry_from_workflow("typed", workflow)

    catalog_by_name = {inp.name: inp.default_display for inp in catalog_entry.inputs}
    workflow_by_name = {inp.name: inp.default_display for inp in workflow_entry.inputs}
    assert catalog_by_name["lang"] == workflow_by_name["lang"] == "Rust"
    assert catalog_by_name["count"] == workflow_by_name["count"] == "3"


def test_multiline_string_default_renders_on_one_row() -> None:
    hint = XPromptInputHint(
        name="body",
        type="text",
        required=False,
        default_display="first\nsecond",
        position=0,
    )
    text = Text("example")
    append_input_hints(text, (hint,))
    assert "=first …" in text.plain
    row = text.plain.split("body?: text", 1)[1]
    assert "\n" not in row
    assert input_default_suffix(hint) == "=first …"


def test_newlines_only_default_falls_back_to_question_mark() -> None:
    hint = XPromptInputHint(
        name="body",
        type="text",
        required=False,
        default_display="\n\n",
        position=0,
    )
    text = Text("example")
    append_input_hints(text, (hint,))
    assert "body?: text?" in text.plain
    assert input_default_suffix(hint) == "?"
