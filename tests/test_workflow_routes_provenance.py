"""Workflow-route provenance acceptance matrix (sase-1tc.1.1.3).

Every prompt rendering route must preserve provenance: literal ``$(command)``
expressions from admitted definitions execute in a human launch, while every
interpolated context value — model fields, ``_data``, ``_raw``/``_response``,
loop items and joins, bash/python producer results, branch names — stays
literal all the way to the provider boundary. Agent launches execute nothing.

Routes covered: shared prepare, parallel pre-expansion (plus its second pass
through preparation), embedded prompt_part expansion, tagged workflow content,
the simple-macro runner path through to ``invoke_agent``, standalone steps,
and the mentor prompt build. A combined-output case proves macros from
rendered data still expand without executing embedded command text, and one
mixed template proves an authored command next to a malicious value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.macro.models import InputArg, InputType, Macro


def _human(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run the boundary in a human launch rooted at a scratch cwd."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "human")


def _touch(marker: str) -> str:
    return f"$(touch {marker})"


def _malicious_context() -> dict[str, Any]:
    """The workflow data channels that must never execute."""
    return {
        "review": {
            "summary": _touch("route-field-marker"),
            "_data": _touch("route-data-marker"),
            "_raw": _touch("route-raw-marker"),
            "_response": _touch("route-response-marker"),
        },
        "loop_step": _touch("route-join-marker"),
        "setup": {"branch_name": "topic/" + _touch("route-branch-marker")},
    }


def _markers() -> list[str]:
    return [
        "route-field-marker",
        "route-data-marker",
        "route-raw-marker",
        "route-response-marker",
        "route-join-marker",
        "route-branch-marker",
    ]


def _assert_all_literal(result: str, tmp_path: Path) -> None:
    for marker in _markers():
        assert not (tmp_path / marker).exists()
        assert _touch(marker) in result


def _executor(workflow: Any, tmp_path: Path) -> Any:
    from sase.macro import WorkflowExecutor

    return WorkflowExecutor(workflow=workflow, args={}, artifacts_dir=str(tmp_path))


# --- render layer -----------------------------------------------------------


def test_render_prompt_template_mixed_authored_and_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An authored command executes next to malicious values that stay literal."""
    from sase.macro.workflow_executor_utils import render_prompt_template

    _human(monkeypatch, tmp_path)
    rendered = render_prompt_template(
        "real=$(touch route-real-marker)\n"
        "summary={{ review.summary }} data={{ review._data }}\n"
        "raw={{ review._raw }} response={{ review._response }}\n"
        "join={{ loop_step }} branch={{ setup.branch_name }}\n"
        "again={{ review.summary }}",
        _malicious_context(),
    )

    assert (tmp_path / "route-real-marker").exists()
    assert "$(touch route-real-marker)" not in rendered
    _assert_all_literal(rendered, tmp_path)
    assert rendered.count(_touch("route-field-marker")) == 2
    # The branch value is data even though it looks git-shaped.
    assert "topic/$(touch route-branch-marker)" in rendered


def test_render_prompt_template_jinja_conditionals_see_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.macro.workflow_executor_utils import render_prompt_template

    _human(monkeypatch, tmp_path)
    rendered = render_prompt_template(
        '{% if "LGTM" in review._raw %}approved{% else %}changes{% endif %}'
        " :: {{ review._raw }}",
        {"review": {"_raw": "LGTM"}},
    )

    assert "approved" in rendered
    assert "changes" not in rendered


def test_render_workflow_template_expands_macros_and_jinja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared-boundary render+macro: authored arg commands run, data does not."""
    from sase.macro.workflow_executor_utils import render_workflow_template

    _human(monkeypatch, tmp_path)
    echo = Macro(name="echo", content="ECHO:{{ _1 }}")
    rendered = render_workflow_template(
        "static=$(touch route-static-marker)\n"
        "#echo($(printf hello)-$(touch route-macro-arg-marker))\n"
        "false-branch={% if false %}$(touch route-false-marker){% endif %}done\n"
        "summary={{ review.summary }} data={{ review._data }}\n"
        "raw={{ review._raw }} response={{ review._response }}\n"
        "join={{ loop_step }} branch={{ setup.branch_name }}\n",
        _malicious_context(),
        extra_macros={"echo": echo},
    )

    assert (tmp_path / "route-static-marker").exists()
    assert (tmp_path / "route-macro-arg-marker").exists()
    assert not (tmp_path / "route-false-marker").exists()
    assert "false-branch=done" in rendered
    assert "ECHO:hello-" in rendered
    _assert_all_literal(rendered, tmp_path)


def test_render_workflow_template_agent_launch_executes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.macro.workflow_executor_utils import render_workflow_template

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "agent")
    echo = Macro(name="echo", content="ECHO:{{ _1 }}")
    rendered = render_workflow_template(
        "static=$(touch route-agent-real-marker)\n"
        "#echo(hi-$(touch route-agent-arg-marker))\n"
        "summary={{ review.summary }} data={{ review._data }}\n"
        "raw={{ review._raw }} response={{ review._response }}\n"
        "join={{ loop_step }} branch={{ setup.branch_name }}\n",
        _malicious_context(),
        extra_macros={"echo": echo},
    )

    assert not (tmp_path / "route-agent-real-marker").exists()
    assert not (tmp_path / "route-agent-arg-marker").exists()
    assert "$(touch route-agent-real-marker)" in rendered
    assert "ECHO:" in rendered
    _assert_all_literal(rendered, tmp_path)


# --- prepare route ----------------------------------------------------------


def test_prepare_prompt_step_keeps_workflow_data_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared prepare route: structured outputs stay data to the provider."""
    from sase.macro.workflow_models import Workflow, WorkflowStep

    _human(monkeypatch, tmp_path)
    step = WorkflowStep(
        name="main",
        agent=(
            "summary={{ review.summary }} data={{ review._data }}\n"
            "raw={{ review._raw }} response={{ review._response }}\n"
            "join={{ loop_step }} branch={{ setup.branch_name }}\n"
            '{% if "LGTM" in review._raw %}approved{% else %}changes{% endif %}'
        ),
    )
    executor = _executor(Workflow(name="t", steps=[step]), tmp_path)
    executor.context.update(_malicious_context())

    prepared = executor._prepare_prompt_step(step)

    _assert_all_literal(prepared.expanded_prompt, tmp_path)
    # Value semantics hold on this route too (the old placeholder took the
    # false branch); the raw payload itself stays literal.
    assert "changes" in prepared.expanded_prompt
    assert _touch("route-raw-marker") in prepared.expanded_prompt


def test_prepare_prompt_step_structured_storage_shapes_stay_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-dict _data, nested containers, and repeated interpolation."""
    from sase.macro.workflow_models import Workflow, WorkflowStep

    _human(monkeypatch, tmp_path)
    step = WorkflowStep(
        name="main",
        agent=(
            "nd={{ step._data }} nested={{ nested.deep.cmd }} "
            "items={{ items }} again={{ step._data }}"
        ),
    )
    executor = _executor(Workflow(name="t", steps=[step]), tmp_path)
    executor.context.update(
        {
            "step": {"_data": ["a", _touch("route-nd-marker")]},
            "nested": {"deep": {"cmd": _touch("route-nested-marker")}},
            "items": [_touch("route-items-marker")],
        }
    )

    prepared = executor._prepare_prompt_step(step)

    # The late formatting pass may line-wrap long rendered lines, so compare
    # whitespace-insensitively; what matters is no execution and no loss.
    squashed = "".join(prepared.expanded_prompt.split())
    for marker in ("route-nd-marker", "route-nested-marker", "route-items-marker"):
        assert not (tmp_path / marker).exists()
        assert marker in squashed
    assert squashed.count("route-nd-marker") == 2


# --- parallel route ---------------------------------------------------------


def test_parallel_pre_expansion_marks_and_second_pass_stays_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre-expanded copies carry provenance; preparation never re-executes."""
    from sase.macro.workflow_executor_utils import pre_rendered_mark
    from sase.macro.workflow_models import Workflow, WorkflowStep

    _human(monkeypatch, tmp_path)
    nested = WorkflowStep(
        name="child",
        agent=(
            "static=$(touch route-par-real-marker)\n"
            "summary={{ review.summary }} data={{ review._data }}\n"
            "raw={{ review._raw }} response={{ review._response }}\n"
            "join={{ loop_step }} branch={{ setup.branch_name }}"
        ),
    )
    executor = _executor(Workflow(name="t", steps=[nested]), tmp_path)
    executor.context.update(_malicious_context())

    modified, _ = executor._pre_expand_parallel_embedded_workflows([nested])

    assert len(modified) == 1
    mark = pre_rendered_mark(modified[0])
    assert mark is not None
    assert (tmp_path / "route-par-real-marker").exists()

    # The copy flows back through normal preparation (the second-pass defect
    # class): rendered data must not become source.
    prepared = executor._prepare_prompt_step(modified[0])

    _assert_all_literal(prepared.expanded_prompt, tmp_path)
    assert not (tmp_path / "route-join-marker").exists()


# --- embedded + tagged routes -----------------------------------------------


def _embedded_workflow(branch_marker: str, real_marker: str) -> Any:
    from sase.macro.workflow_models import Workflow, WorkflowStep

    return Workflow(
        name="emb",
        steps=[
            WorkflowStep(
                name="gen",
                bash=f"echo 'leak={_touch(branch_marker)}'",
            ),
            WorkflowStep(
                name="part",
                prompt_part=(f"LEAK={{{{ gen.leak }}}} REAL={_touch(real_marker)}"),
            ),
            WorkflowStep(
                name="post",
                bash="echo 'post=done'",
            ),
        ],
    )


def test_embedded_prompt_part_preserves_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Embedded pre-step outputs stay data; definition literals still run."""
    from sase.macro.workflow_models import Workflow, WorkflowStep

    _human(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.macro.loader.get_all_workflows",
        lambda project=None: {
            "emb": _embedded_workflow("route-emb-data-marker", "route-emb-real-marker")
        },
    )
    step = WorkflowStep(name="main", agent="before #emb after")
    executor = _executor(Workflow(name="t", steps=[step]), tmp_path)

    expanded, infos, _ = executor._expand_embedded_workflows_in_prompt(step.agent)

    assert (tmp_path / "route-emb-real-marker").exists()
    assert not (tmp_path / "route-emb-data-marker").exists()
    assert _touch("route-emb-data-marker") in expanded
    assert len(infos) == 1


def test_tagged_workflow_content_renders_data_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _human(monkeypatch, tmp_path)
    from sase.macro.workflow_models import Workflow, WorkflowStep

    tagged = _embedded_workflow("route-tag-data-marker", "route-tag-real-marker")
    executor = _executor(Workflow(name="t", steps=[]), tmp_path)

    content, _ = executor._resolve_tagged_workflow_content(tagged, 0)

    assert (tmp_path / "route-tag-real-marker").exists()
    assert not (tmp_path / "route-tag-data-marker").exists()
    assert _touch("route-tag-data-marker") in content


# --- simple-macro runner route, through to invoke -----------------------------


def _capture_invoke(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from sase.llm_provider.messages import AIMessage

    captured: list[dict[str, Any]] = []

    def fake_invoke(prompt: str, **kwargs: Any) -> Any:
        captured.append({"prompt": prompt, **kwargs})
        return AIMessage(content="ok")

    monkeypatch.setattr("sase.llm_provider.invoke_agent", fake_invoke)
    return captured


def test_simple_macro_runner_proves_payload_literal_at_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full runner path: render, prepare, skip-preprocessing invoke."""
    from sase.macro.workflow_models import Workflow, WorkflowStep
    from sase.macro.workflow_runner import execute_workflow

    _human(monkeypatch, tmp_path)
    captured = _capture_invoke(monkeypatch)
    workflow = Workflow(
        name="greet",
        inputs=[InputArg(name="payload", type=InputType.TEXT, default="x")],
        steps=[
            WorkflowStep(
                name="part",
                prompt_part=(
                    "static=$(touch route-run-real-marker)\nDATA={{ payload }}"
                ),
            )
        ],
    )

    execute_workflow(
        "greet",
        [],
        {"payload": _touch("route-run-data-marker")},
        artifacts_dir=str(tmp_path),
        silent=True,
        workflow_obj=workflow,
    )

    assert (tmp_path / "route-run-real-marker").exists()
    assert not (tmp_path / "route-run-data-marker").exists()
    assert len(captured) == 1
    assert captured[0].get("skip_preprocessing") is True
    assert _touch("route-run-data-marker") in captured[0]["prompt"]


def test_execute_prompt_step_full_preparation_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entire invoke_agent preparation path: stopping at first render misses
    the second pass, so drive preparation through to the provider call."""
    from sase.macro.workflow_models import Workflow, WorkflowStep

    _human(monkeypatch, tmp_path)
    captured = _capture_invoke(monkeypatch)
    step = WorkflowStep(
        name="main",
        agent=(
            "static=$(touch route-full-real-marker)\n"
            "summary={{ review.summary }} data={{ review._data }}\n"
            "raw={{ review._raw }} response={{ review._response }}\n"
            "join={{ loop_step }} branch={{ setup.branch_name }}"
        ),
    )
    executor = _executor(Workflow(name="t", steps=[step]), tmp_path)
    executor.context.update(_malicious_context())
    from sase.macro.workflow_models import StepState, StepStatus

    assert executor._execute_prompt_step(
        step, StepState(name="main", status=StepStatus.IN_PROGRESS)
    )

    assert (tmp_path / "route-full-real-marker").exists()
    assert len(captured) == 1
    _assert_all_literal(captured[0]["prompt"], tmp_path)


# --- standalone route ---------------------------------------------------------


def test_standalone_agent_step_skips_reprocessing_at_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.query_handler._standalone_steps import execute_standalone_steps
    from sase.macro.workflow_models import WorkflowStep

    _human(monkeypatch, tmp_path)
    captured = _capture_invoke(monkeypatch)
    context: dict[str, Any] = dict(_malicious_context())
    steps = [
        WorkflowStep(
            name="s",
            agent=(
                "static=$(touch route-alone-real-marker)\n"
                "summary={{ review.summary }} data={{ review._data }}\n"
                "raw={{ review._raw }} response={{ review._response }}\n"
                "join={{ loop_step }} branch={{ setup.branch_name }}"
            ),
        )
    ]

    execute_standalone_steps(steps, context, "t", str(tmp_path))

    assert (tmp_path / "route-alone-real-marker").exists()
    assert len(captured) == 1
    assert captured[0].get("skip_preprocessing") is True
    _assert_all_literal(captured[0]["prompt"], tmp_path)
    assert context["s"]["_raw"] == "ok"


def test_standalone_producer_result_stays_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bash/python producer results interpolated into agent steps stay literal."""
    from sase.main.query_handler._standalone_steps import execute_standalone_steps
    from sase.macro.workflow_models import WorkflowStep

    _human(monkeypatch, tmp_path)
    captured = _capture_invoke(monkeypatch)
    context: dict[str, Any] = {}
    # A producer emitting command text must not arm the next agent step.
    steps = [
        WorkflowStep(name="evil", bash=f"echo 'out={_touch('route-prod-marker')}'"),
        WorkflowStep(name="s", agent="result={{ evil.out }}"),
    ]

    execute_standalone_steps(steps, context, "t", str(tmp_path))

    assert not (tmp_path / "route-prod-marker").exists()
    assert _touch("route-prod-marker") in captured[0]["prompt"]


# --- mentor route ---------------------------------------------------------------


def test_mentor_prompt_build_keeps_producer_data_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.config.mentor import MentorConfig, _MentorFocusArea
    from sase.workflows.mentor import _build_mentor_prompt

    _human(monkeypatch, tmp_path)
    mentor = MentorConfig(
        mentor_name="m",
        role="reviewer " + _touch("route-mentor-role-marker"),
        focus_areas=[
            _MentorFocusArea(
                focus_name="x",
                description="desc " + _touch("route-mentor-desc-marker"),
            )
        ],
    )

    prompt = _build_mentor_prompt(mentor, "my-patch", "")

    assert not (tmp_path / "route-mentor-role-marker").exists()
    assert not (tmp_path / "route-mentor-desc-marker").exists()
    assert _touch("route-mentor-role-marker") in prompt
    assert _touch("route-mentor-desc-marker") in prompt


# --- combined rendered output -----------------------------------------------------


def test_combined_rendered_macros_expand_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``render.combined``-style data: macros expand, embedded commands do not."""
    from sase.macro import process_macro_references
    from sase.macro.cmdsub_source import generated_provenance

    _human(monkeypatch, tmp_path)
    echo = Macro(name="echo", content="ECHO:{{ _1 }}")
    combined = "#echo(hi " + _touch("route-combined-marker") + ")"

    from sase.macro.processor import process_macro_references_with_catalog

    expanded = process_macro_references_with_catalog(
        combined,
        {"echo": echo},
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=generated_provenance(),
    )
    # The generated pass expands the reference without executing: a
    # first-pass source boundary would have run the embedded command.
    assert not (tmp_path / "route-combined-marker").exists()
    assert "ECHO:" in expanded
    assert _touch("route-combined-marker") in expanded

    # And the plain helper honors the same generated provenance.
    assert _touch("route-combined-marker") in process_macro_references(
        combined,
        extra_macros={"echo": echo},
        cmdsub_provenance=generated_provenance(),
    )
