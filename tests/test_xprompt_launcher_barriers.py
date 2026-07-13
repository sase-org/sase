"""Regression tests for drain barriers on bundled detached-agent workflows."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.multi_prompt import parse_multi_prompt
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_validator import validate_workflow


XPROMPTS_DIR = Path(__file__).resolve().parents[1] / "xprompts"


def _launch_step(workflow_name: str, step_name: str) -> str:
    workflow = _load_workflow_from_file(XPROMPTS_DIR / f"{workflow_name}.yml")
    assert workflow is not None
    validate_workflow(workflow)

    step = next(step for step in workflow.steps if step.name == step_name)
    assert step.python is not None
    return step.python


def _execute_launch_step(
    step_python: str,
    *,
    replacements: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    captured: list[str] = []

    def fake_launch(prompt, *_args, **_kwargs):  # type: ignore[no-untyped-def]  # noqa: ARG001
        captured.append(prompt)

    monkeypatch.setattr("sase.agent.launcher.launch_agent_from_cwd", fake_launch)

    rendered = step_python
    for marker, value in replacements.items():
        rendered = rendered.replace(marker, value)
    assert "{{" not in rendered

    exec(  # noqa: S102 - test executes its own controlled workflow snippet
        compile(rendered, "<launcher-workflow-step>", "exec"),
        {"print": lambda *_args, **_kwargs: None},
    )
    return captured


@pytest.mark.parametrize(
    ("workflow_name", "step_name", "count_step", "expected_text"),
    [
        (
            "audit_recent_bugs",
            "launch_bug_audit_agent",
            "count_recent_bug_audit_commits",
            "Audit recent commits in sase-core for bugs.",
        ),
        (
            "audit_recent_improvements",
            "launch_improvement_audit_agent",
            "count_recent_improvement_audit_commits",
            "Audit recent commits in sase-core for objective improvements.",
        ),
    ],
)
def test_audit_launch_prompt_has_drain_barrier(
    workflow_name: str,
    step_name: str,
    count_step: str,
    expected_text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _execute_launch_step(
        _launch_step(workflow_name, step_name),
        replacements={
            "{{ project }}": "sase-core",
            "{{ gh_ref }}": "sase-org/sase-core",
            f"{{{{ {count_step}.head }}}}": "abcdef0123456789",
            f"{{{{ {count_step}.head_short }}}}": "abcdef012345",
            f"{{{{ {count_step}.marker }}}}": "/tmp/audit-marker",
            f"{{{{ {count_step}.base_context }}}}": "marker SHA 1234",
            f"{{{{ {count_step}.range_desc }}}}": "1234..abcdef",
            f"{{{{ {count_step}.count }}}}": "42",
        },
        monkeypatch=monkeypatch,
    )

    assert len(captured) == 1
    prompt = captured[0]
    assert prompt.count("%w(runners=0)") == 1
    assert "#!" not in prompt

    cleaned, directives = extract_prompt_directives(prompt)
    assert directives.wait_runners == 0
    assert directives.wait == []
    assert "%w(runners=0)" not in cleaned
    assert expected_text in cleaned


def test_refresh_docs_launch_prompts_have_chained_drain_barriers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _execute_launch_step(
        _launch_step("refresh_docs", "launch_docs_agents"),
        replacements={
            "{{ project }}": "sase-core",
            "{{ gh_ref }}": "sase-org/sase-core",
            "{{ count_commits.head_short }}": "abcdef012345",
        },
        monkeypatch=monkeypatch,
    )

    assert len(captured) == 1
    segments = parse_multi_prompt(captured[0]).segments
    assert len(segments) == 2
    assert "%wait" not in segments[0]
    assert segments[1].startswith("%wait\n")

    previous_name = "refresh_docs.sase_core.abcdef012345.update"
    parsed = []
    for segment in segments:
        assert segment.count("%w(runners=0)") == 1
        assert "#!" not in segment
        with patch(
            "sase.agent.names.get_most_recent_agent_name",
            return_value=previous_name,
        ):
            cleaned, directives = extract_prompt_directives(segment)
        assert directives.wait_runners == 0
        assert "%w(runners=0)" not in cleaned
        parsed.append((cleaned, directives))

    assert parsed[0][1].wait == []
    assert parsed[1][1].wait == [previous_name]
    assert "#sase/docs" in parsed[0][0]
    assert "Inspect the documentation changes" in parsed[1][0]
