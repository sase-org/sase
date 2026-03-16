"""Tests for xprompt/graph.py - workflow DAG visualization."""

from sase.xprompt.graph import (
    _escape_label,
    _get_step_texts,
    _mermaid_id,
    _node_label,
    collect_all_step_names,
    control_annotations,
    extract_step_references,
    list_workflows,
    step_type,
    workflow_to_mermaid,
    workflow_to_text,
)
from sase.xprompt.workflow_models import (
    LoopConfig,
    ParallelConfig,
    Workflow,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# step_type
# ---------------------------------------------------------------------------


def test_step_type_agent() -> None:
    step = WorkflowStep(name="s", agent="do something")
    assert step_type(step) == "agent"


def test_step_type_bash() -> None:
    step = WorkflowStep(name="s", bash="echo hi")
    assert step_type(step) == "bash"


def test_step_type_python() -> None:
    step = WorkflowStep(name="s", python="print(1)")
    assert step_type(step) == "python"


def test_step_type_prompt_part() -> None:
    step = WorkflowStep(name="s", prompt_part="text")
    assert step_type(step) == "prompt_part"


def test_step_type_parallel() -> None:
    step = WorkflowStep(
        name="s",
        parallel_config=ParallelConfig(steps=[WorkflowStep(name="sub", bash="ls")]),
    )
    assert step_type(step) == "parallel"


def test_step_type_unknown() -> None:
    step = WorkflowStep(name="s")
    assert step_type(step) == "unknown"


# ---------------------------------------------------------------------------
# _mermaid_id / _escape_label
# ---------------------------------------------------------------------------


def test_mermaid_id_simple() -> None:
    assert _mermaid_id("step_one") == "step_one"


def test_mermaid_id_special_chars() -> None:
    assert _mermaid_id("my-step.2") == "my_step_2"


def test_escape_label_quotes() -> None:
    assert _escape_label('say "hello"') == "say &quot;hello&quot;"


# ---------------------------------------------------------------------------
# control_annotations
# ---------------------------------------------------------------------------


def test_control_annotations_none() -> None:
    step = WorkflowStep(name="s", bash="echo")
    assert control_annotations(step) == ""


def test_control_annotations_condition() -> None:
    step = WorkflowStep(name="s", bash="echo", condition="x > 1")
    assert control_annotations(step) == "if:"


def test_control_annotations_for_loop() -> None:
    step = WorkflowStep(name="s", bash="echo", for_loop={"item": "{{ items }}"})
    assert control_annotations(step) == "for:"


def test_control_annotations_repeat() -> None:
    step = WorkflowStep(
        name="s", bash="echo", repeat_config=LoopConfig(condition="done")
    )
    assert control_annotations(step) == "repeat:"


def test_control_annotations_while() -> None:
    step = WorkflowStep(
        name="s", bash="echo", while_config=LoopConfig(condition="running")
    )
    assert control_annotations(step) == "while:"


def test_control_annotations_combined() -> None:
    step = WorkflowStep(
        name="s",
        bash="echo",
        condition="x",
        for_loop={"i": "items"},
    )
    assert "if:" in control_annotations(step)
    assert "for:" in control_annotations(step)


# ---------------------------------------------------------------------------
# _get_step_texts
# ---------------------------------------------------------------------------


def test_get_step_texts_agent() -> None:
    step = WorkflowStep(name="s", agent="run {{ prev.output }}")
    texts = _get_step_texts(step)
    assert "run {{ prev.output }}" in texts


def test_get_step_texts_for_loop() -> None:
    step = WorkflowStep(name="s", bash="echo", for_loop={"x": "{{ items }}"})
    texts = _get_step_texts(step)
    assert "{{ items }}" in texts


def test_get_step_texts_repeat_config() -> None:
    step = WorkflowStep(
        name="s", bash="echo", repeat_config=LoopConfig(condition="{{ done }}")
    )
    texts = _get_step_texts(step)
    assert "{{ done }}" in texts


def test_get_step_texts_while_config() -> None:
    step = WorkflowStep(
        name="s", bash="echo", while_config=LoopConfig(condition="{{ running }}")
    )
    texts = _get_step_texts(step)
    assert "{{ running }}" in texts


# ---------------------------------------------------------------------------
# extract_step_references
# ---------------------------------------------------------------------------


def test_extract_step_references_simple() -> None:
    step = WorkflowStep(name="step2", agent="Use {{ step1.output }}")
    refs = extract_step_references(step, {"step1", "step2"})
    assert refs == {"step1"}


def test_extract_step_references_no_self_ref() -> None:
    step = WorkflowStep(name="s", agent="{{ s.output }}")
    refs = extract_step_references(step, {"s"})
    assert refs == set()


def test_extract_step_references_unknown_ignored() -> None:
    step = WorkflowStep(name="s", agent="{{ nonexistent.value }}")
    refs = extract_step_references(step, {"s", "other"})
    assert refs == set()


def test_extract_step_references_parallel_substeps() -> None:
    sub = WorkflowStep(name="sub", agent="{{ base.output }}")
    step = WorkflowStep(name="par", parallel_config=ParallelConfig(steps=[sub]))
    refs = extract_step_references(step, {"base", "par", "sub"})
    assert "base" in refs


# ---------------------------------------------------------------------------
# collect_all_step_names
# ---------------------------------------------------------------------------


def test_collect_all_step_names_simple() -> None:
    steps = [WorkflowStep(name="a"), WorkflowStep(name="b")]
    assert collect_all_step_names(steps) == {"a", "b"}


def test_collect_all_step_names_with_parallel() -> None:
    sub = WorkflowStep(name="sub1", bash="ls")
    step = WorkflowStep(name="par", parallel_config=ParallelConfig(steps=[sub]))
    names = collect_all_step_names([step, WorkflowStep(name="c")])
    assert names == {"par", "sub1", "c"}


# ---------------------------------------------------------------------------
# _node_label
# ---------------------------------------------------------------------------


def test_node_label_basic() -> None:
    step = WorkflowStep(name="build", bash="make")
    label = _node_label(step)
    assert "build" in label
    assert "bash" in label


def test_node_label_with_flow() -> None:
    step = WorkflowStep(name="check", bash="test", condition="x")
    label = _node_label(step)
    assert "if:" in label


# ---------------------------------------------------------------------------
# workflow_to_mermaid
# ---------------------------------------------------------------------------


def test_workflow_to_mermaid_basic() -> None:
    wf = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="step1", bash="echo 1"),
            WorkflowStep(name="step2", agent="Use {{ step1.output }}"),
        ],
    )
    mermaid = workflow_to_mermaid(wf)
    assert mermaid.startswith("graph TD")
    assert "step1" in mermaid
    assert "step2" in mermaid
    # step2 depends on step1
    assert "-->" in mermaid


def test_workflow_to_mermaid_agent_shape() -> None:
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="do_agent", agent="prompt")],
    )
    mermaid = workflow_to_mermaid(wf)
    # Agent nodes use stadium shape ([" ... "])
    assert '(["' in mermaid


def test_workflow_to_mermaid_prompt_part_shape() -> None:
    wf = Workflow(
        name="test",
        steps=[WorkflowStep(name="pp", prompt_part="text")],
    )
    mermaid = workflow_to_mermaid(wf)
    # Prompt parts use asymmetric shape (>" ... "])
    assert '>"' in mermaid


def test_workflow_to_mermaid_parallel_subgraph() -> None:
    sub = WorkflowStep(name="sub1", bash="ls")
    wf = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="par",
                parallel_config=ParallelConfig(steps=[sub]),
            ),
        ],
    )
    mermaid = workflow_to_mermaid(wf)
    assert "subgraph" in mermaid
    assert "end" in mermaid


# ---------------------------------------------------------------------------
# workflow_to_text
# ---------------------------------------------------------------------------


def test_workflow_to_text_basic() -> None:
    wf = Workflow(
        name="my_workflow",
        steps=[
            WorkflowStep(name="build", bash="make"),
            WorkflowStep(name="deploy", agent="deploy {{ build.output }}"),
        ],
        source_path="/path/to/wf.yml",
    )
    text = workflow_to_text(wf)
    assert "Workflow: my_workflow" in text
    assert "Source: /path/to/wf.yml" in text
    assert "1. build [bash]" in text
    assert "2. deploy [agent]" in text
    assert "depends on: build" in text


def test_workflow_to_text_with_inputs() -> None:
    from sase.xprompt.models import InputArg, InputType

    wf = Workflow(
        name="wf",
        inputs=[InputArg(name="msg", type=InputType.TEXT)],
        steps=[WorkflowStep(name="s", bash="echo")],
    )
    text = workflow_to_text(wf)
    assert "Inputs:" in text
    assert "msg" in text


def test_workflow_to_text_parallel_substeps() -> None:
    sub = WorkflowStep(name="sub1", bash="ls")
    wf = Workflow(
        name="wf",
        steps=[
            WorkflowStep(name="par", parallel_config=ParallelConfig(steps=[sub])),
        ],
    )
    text = workflow_to_text(wf)
    assert "sub1" in text


def test_workflow_to_text_no_source() -> None:
    wf = Workflow(
        name="wf",
        steps=[WorkflowStep(name="s", bash="echo")],
    )
    text = workflow_to_text(wf)
    assert "Workflow: wf" in text
    assert "Source:" not in text


def test_workflow_to_text_flow_annotations() -> None:
    wf = Workflow(
        name="wf",
        steps=[WorkflowStep(name="s", bash="echo", condition="x > 1")],
    )
    text = workflow_to_text(wf)
    assert "if:" in text


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------


def test_list_workflows_empty() -> None:
    assert list_workflows({}) == "No workflows found."


def test_list_workflows_only_simple() -> None:
    wf = Workflow(
        name="simple",
        steps=[WorkflowStep(name="s", prompt_part="text")],
    )
    assert list_workflows({"simple": wf}) == "No multi-step workflows found."


def test_list_workflows_table() -> None:
    wf = Workflow(
        name="build_and_test",
        steps=[
            WorkflowStep(name="build", bash="make"),
            WorkflowStep(name="test", bash="pytest"),
        ],
        source_path="/path/to/wf.yml",
    )
    result = list_workflows({"build_and_test": wf})
    assert "build_and_test" in result
    assert "2" in result  # step count
    assert "/path/to/wf.yml" in result
    assert "Name" in result  # header
    assert "Steps" in result
