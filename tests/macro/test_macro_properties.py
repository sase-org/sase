"""Tests for the shared macro/workflow properties projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.macro.cli_show_model import MacroShowRecord
from sase.macro.cli_show_resolve import resolve_show_record
from sase.macro.models import InputArg, InputChoice, InputType, Macro
from sase.macro.properties import (
    show_inputs,
    single_line_default,
    macro_properties,
)
from sase.macro.tags import MacroTag
from sase.macro.workflow_models import Workflow, WorkflowStep


def test_show_inputs_required_input_has_no_default_display() -> None:
    rows = show_inputs([InputArg("target", InputType.WORD)])

    assert rows[0].required is True
    assert rows[0].default_display is None


def test_show_inputs_default_and_explicit_null_render_distinctly() -> None:
    rows = show_inputs(
        [
            InputArg("name", InputType.LINE, default="sase"),
            InputArg("notes", InputType.TEXT, default=None),
        ]
    )

    assert rows[0].required is False
    assert rows[0].default_display == "sase"
    assert rows[1].required is False
    assert rows[1].default_display == "null"


def test_single_line_default_elides_multiline_value() -> None:
    assert single_line_default("first line\nsecond line") == "first line …"
    assert single_line_default("only line") == "only line"


def test_show_inputs_repeatable_survives_projection() -> None:
    rows = show_inputs([InputArg("files", InputType.PATH, repeatable=True)])

    assert rows[0].repeatable is True


def test_show_inputs_enum_choices_carry_through() -> None:
    rows = show_inputs(
        [
            InputArg(
                "mode",
                InputType.ENUM,
                choices=(InputChoice("fast"), InputChoice("slow", label="Slow")),
            )
        ]
    )

    assert rows[0].choices == ("fast", "slow")


def test_show_inputs_filters_step_inputs() -> None:
    rows = show_inputs(
        [
            InputArg("visible", InputType.WORD),
            InputArg("hidden", InputType.WORD, is_step_input=True),
        ]
    )

    assert [row.name for row in rows] == ["visible"]


def test_macro_properties_projects_everything_declared() -> None:
    macro_def = Macro(
        name="review",
        content="Review {{ project }}",
        inputs=[InputArg("project", InputType.LINE, default="sase")],
        description="Review open task beads.",
        tags=frozenset({MacroTag.vcs, MacroTag.commit}),
        skill=["claude", "codex"],
        snippet="rv",
        log_skill_use=False,
        memory_type="reference",
        local_macros={"_helper": Macro(name="_helper", content="helper body")},
    )

    properties = macro_properties(
        macro_def,
        reference="#review",
        kind="xprompt",
        project="sase",
        source_bucket="config",
        definition_path="/work/sase.yml",
    )

    assert properties.reference == "#review"
    assert properties.kind == "xprompt"
    assert properties.description == "Review open task beads."
    assert [row.name for row in properties.inputs] == ["project"]
    assert properties.tags == ["commit", "vcs"]
    assert properties.skill == ["claude", "codex"]
    assert properties.snippet == "rv"
    assert properties.log_skill_use is False
    assert properties.memory_type == "reference"
    assert [item.name for item in properties.local_macros] == ["_helper"]
    assert properties.project == "sase"
    assert properties.source_bucket == "config"
    assert properties.definition_path == "/work/sase.yml"
    assert properties.is_empty is False


def test_macro_properties_skill_bare_flag_and_snippet_bool_project() -> None:
    macro_def = Macro(name="demo", content="body", skill=True, snippet=True)

    properties = macro_properties(macro_def, reference="#demo", kind="skill")

    assert properties.skill is True
    assert properties.snippet is True


def test_macro_properties_workflow_steps_project() -> None:
    workflow = Workflow(
        name="ship",
        steps=[
            WorkflowStep(name="prep", bash="just test"),
            WorkflowStep(name="run", agent="Implement the fix"),
        ],
    )

    properties = macro_properties(workflow, reference="#ship", kind="workflow")

    assert [step.name for step in properties.steps] == ["prep", "run"]
    assert [step.type for step in properties.steps] == ["bash", "agent"]


def test_macro_properties_segment_count_reflects_swarm_separators() -> None:
    macro_def = Macro(name="swarm", content="one\n---\ntwo\n---\nthree")

    properties = macro_properties(macro_def, reference="#swarm", kind="xprompt")

    assert properties.segment_count == 3


def test_macro_properties_is_empty_true_for_bare_body_macro() -> None:
    macro_def = Macro(name="bare", content="Just a body, nothing declared.")

    properties = macro_properties(macro_def, reference="#bare", kind="xprompt")

    assert properties.is_empty is True


@pytest.mark.parametrize(
    "build",
    [
        lambda: Macro(name="d", content="x", description="Has a description."),
        lambda: Macro(name="d", content="x", inputs=[InputArg("a", InputType.WORD)]),
        lambda: Macro(name="d", content="x", tags=frozenset({MacroTag.vcs})),
        lambda: Macro(name="d", content="x", skill=True),
        lambda: Macro(name="d", content="x", memory_type="core"),
        lambda: Macro(name="d", content="one\n---\ntwo"),
    ],
)
def test_macro_properties_is_empty_false_once_any_property_exists(
    build: Any,
) -> None:
    properties = macro_properties(build(), reference="#d", kind="xprompt")

    assert properties.is_empty is False


def _patch_catalog(
    monkeypatch: pytest.MonkeyPatch,
    resolve_module: Any,
    *,
    workflows: dict[str, Workflow] | None = None,
    macros: dict[str, Macro] | None = None,
) -> None:
    monkeypatch.setattr(
        resolve_module,
        "get_all_workflows",
        lambda *, project=None: workflows or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "get_all_macros",
        lambda *, project=None: macros or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "_hosted_url_for_definition",
        lambda **_kwargs: None,
    )


def test_inputs_local_macros_and_steps_never_drift_from_show_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both surfaces must describe the same definition identically."""
    import sase.macro.cli_show_resolve as resolve_module

    macro_path = tmp_path / "review.md"
    macro_path.write_text("body", encoding="utf-8")
    macro_def = Macro(
        name="review",
        content="body",
        source_path=str(macro_path),
        inputs=[
            InputArg("project", InputType.LINE, default="sase"),
            InputArg("dry_run", InputType.BOOL, default=False),
        ],
        local_macros={"_helper": Macro(name="_helper", content="helper body")},
    )

    workflow_path = tmp_path / "ship.yml"
    workflow_path.write_text("name: ship", encoding="utf-8")
    workflow = Workflow(
        name="ship",
        source_path=str(workflow_path),
        steps=[
            WorkflowStep(name="prep", bash="just test"),
            WorkflowStep(name="run", agent="Implement the fix"),
        ],
    )

    _patch_catalog(
        monkeypatch,
        resolve_module,
        macros={"review": macro_def},
        workflows={"ship": workflow},
    )

    macro_record = resolve_show_record("review")
    workflow_record = resolve_show_record("ship")
    assert isinstance(macro_record, MacroShowRecord)
    assert isinstance(workflow_record, MacroShowRecord)

    macro_result = macro_properties(macro_def, reference="#review", kind="xprompt")
    workflow_result = macro_properties(workflow, reference="#ship", kind="workflow")

    assert macro_result.inputs == macro_record.inputs
    assert macro_result.local_macros == macro_record.local_macros
    assert macro_result.steps == macro_record.steps
    assert workflow_result.inputs == workflow_record.inputs
    assert workflow_result.local_macros == workflow_record.local_macros
    assert workflow_result.steps == workflow_record.steps
