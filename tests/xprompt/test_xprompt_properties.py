"""Tests for the shared xprompt/workflow properties projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.xprompt.cli_show_model import XPromptShowRecord
from sase.xprompt.cli_show_resolve import resolve_show_record
from sase.xprompt.models import InputArg, InputChoice, InputType, XPrompt
from sase.xprompt.properties import (
    show_inputs,
    single_line_default,
    xprompt_properties,
)
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_models import Workflow, WorkflowStep


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


def test_xprompt_properties_projects_everything_declared() -> None:
    xprompt = XPrompt(
        name="review",
        content="Review {{ project }}",
        inputs=[InputArg("project", InputType.LINE, default="sase")],
        description="Review open task beads.",
        tags=frozenset({XPromptTag.vcs, XPromptTag.commit}),
        skill=["claude", "codex"],
        snippet="rv",
        log_skill_use=False,
        memory_type="long",
        local_xprompts={"_helper": XPrompt(name="_helper", content="helper body")},
    )

    properties = xprompt_properties(
        xprompt,
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
    assert properties.memory_type == "long"
    assert [item.name for item in properties.local_xprompts] == ["_helper"]
    assert properties.project == "sase"
    assert properties.source_bucket == "config"
    assert properties.definition_path == "/work/sase.yml"
    assert properties.is_empty is False


def test_xprompt_properties_skill_bare_flag_and_snippet_bool_project() -> None:
    xprompt = XPrompt(name="demo", content="body", skill=True, snippet=True)

    properties = xprompt_properties(xprompt, reference="#demo", kind="skill")

    assert properties.skill is True
    assert properties.snippet is True


def test_xprompt_properties_workflow_steps_project() -> None:
    workflow = Workflow(
        name="ship",
        steps=[
            WorkflowStep(name="prep", bash="just test"),
            WorkflowStep(name="run", agent="Implement the fix"),
        ],
    )

    properties = xprompt_properties(workflow, reference="#ship", kind="workflow")

    assert [step.name for step in properties.steps] == ["prep", "run"]
    assert [step.type for step in properties.steps] == ["bash", "agent"]


def test_xprompt_properties_segment_count_reflects_swarm_separators() -> None:
    xprompt = XPrompt(name="swarm", content="one\n---\ntwo\n---\nthree")

    properties = xprompt_properties(xprompt, reference="#swarm", kind="xprompt")

    assert properties.segment_count == 3


def test_xprompt_properties_is_empty_true_for_bare_body_xprompt() -> None:
    xprompt = XPrompt(name="bare", content="Just a body, nothing declared.")

    properties = xprompt_properties(xprompt, reference="#bare", kind="xprompt")

    assert properties.is_empty is True


@pytest.mark.parametrize(
    "build",
    [
        lambda: XPrompt(name="d", content="x", description="Has a description."),
        lambda: XPrompt(name="d", content="x", inputs=[InputArg("a", InputType.WORD)]),
        lambda: XPrompt(name="d", content="x", tags=frozenset({XPromptTag.vcs})),
        lambda: XPrompt(name="d", content="x", skill=True),
        lambda: XPrompt(name="d", content="x", memory_type="short"),
        lambda: XPrompt(name="d", content="one\n---\ntwo"),
    ],
)
def test_xprompt_properties_is_empty_false_once_any_property_exists(
    build: Any,
) -> None:
    properties = xprompt_properties(build(), reference="#d", kind="xprompt")

    assert properties.is_empty is False


def _patch_catalog(
    monkeypatch: pytest.MonkeyPatch,
    resolve_module: Any,
    *,
    workflows: dict[str, Workflow] | None = None,
    xprompts: dict[str, XPrompt] | None = None,
) -> None:
    monkeypatch.setattr(
        resolve_module,
        "get_all_workflows",
        lambda *, project=None: workflows or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "get_all_xprompts",
        lambda *, project=None: xprompts or {},
    )
    monkeypatch.setattr(
        resolve_module,
        "_hosted_url_for_definition",
        lambda **_kwargs: None,
    )


def test_inputs_local_xprompts_and_steps_never_drift_from_show_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both surfaces must describe the same definition identically."""
    import sase.xprompt.cli_show_resolve as resolve_module

    xprompt_path = tmp_path / "review.md"
    xprompt_path.write_text("body", encoding="utf-8")
    xprompt = XPrompt(
        name="review",
        content="body",
        source_path=str(xprompt_path),
        inputs=[
            InputArg("project", InputType.LINE, default="sase"),
            InputArg("dry_run", InputType.BOOL, default=False),
        ],
        local_xprompts={"_helper": XPrompt(name="_helper", content="helper body")},
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
        xprompts={"review": xprompt},
        workflows={"ship": workflow},
    )

    xprompt_record = resolve_show_record("review")
    workflow_record = resolve_show_record("ship")
    assert isinstance(xprompt_record, XPromptShowRecord)
    assert isinstance(workflow_record, XPromptShowRecord)

    xprompt_result = xprompt_properties(xprompt, reference="#review", kind="xprompt")
    workflow_result = xprompt_properties(workflow, reference="#ship", kind="workflow")

    assert xprompt_result.inputs == xprompt_record.inputs
    assert xprompt_result.local_xprompts == xprompt_record.local_xprompts
    assert xprompt_result.steps == xprompt_record.steps
    assert workflow_result.inputs == workflow_record.inputs
    assert workflow_result.local_xprompts == workflow_record.local_xprompts
    assert workflow_result.steps == workflow_record.steps
