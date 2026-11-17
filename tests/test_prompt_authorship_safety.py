"""Regressions for shell substitution in agent-authored prompt text."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.llm_provider.preprocessing import (
    preprocess_prompt_early,
    preprocess_prompt_late,
)
from sase.macro.models import Macro


def test_agent_authored_late_preprocessing_keeps_cmdsub_literal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "agent-command-ran"
    monkeypatch.chdir(tmp_path)
    command = "$(touch agent-command-ran)"

    result = preprocess_prompt_late(
        f"handoff prompt {command}",
        file_ref_mode="skip",
    )

    assert command in result
    assert "handoff prompt" in result
    assert not marker.exists()


def test_human_authored_cmdsub_executes_at_early_boundary_not_late() -> None:
    # Phase sase-1tc.1.1.2 moved command substitution to the early source
    # boundary: the late phase never executes, so rendered text cannot
    # become source through a second pass.
    late_result = preprocess_prompt_late(
        "human prompt $(printf human)",
        file_ref_mode="skip",
    )

    assert "$(printf human)" in late_result

    early = preprocess_prompt_early("human prompt $(printf human)")

    assert "human prompt human" in early.prompt
    assert "$(" not in early.prompt


def test_handoff_macros_expand_while_cmdsub_stays_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "macro-command-ran"
    monkeypatch.chdir(tmp_path)
    # An agent-authored handoff carries the launch stamp; source commands
    # in it must not execute at the early boundary either.
    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "agent")
    command = "$(touch macro-command-ran)"
    early = preprocess_prompt_early(
        f"#handoff {command}",
        extra_macros={"handoff": Macro(name="handoff", content="expanded")},
    )

    result = preprocess_prompt_late(
        early.prompt,
        file_ref_mode="skip",
    )

    assert "expanded" in result
    assert command in result
    assert not marker.exists()


def test_workflow_model_output_interpolated_twice_stays_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase sase-1tc.1.1.3 removed the opaque placeholder representation
    # (``__SASE_MODEL_OUTPUT_*`` plus disabled-region wrapping): placeholders
    # broke Jinja value semantics while covering only two keys. Interpolated
    # model output is data by construction now — it renders literally, twice,
    # with no markers — and the late phase keeps it literal.
    from sase.macro.workflow_executor_utils import render_prompt_template

    marker = tmp_path / "twice-response-command-ran"
    monkeypatch.chdir(tmp_path)
    raw = "$(touch twice-response-command-ran)"

    rendered = render_prompt_template(
        "A {{ step._raw }} B {{ step._raw }} C",
        {"step": {"_raw": raw}},
    )

    assert "__SASE_MODEL_OUTPUT_" not in rendered
    assert "%macros_enabled" not in rendered
    assert rendered.count(raw) == 2

    result = preprocess_prompt_late(
        rendered,
        file_ref_mode="skip",
    )

    assert raw in result
    assert result.count(raw) == 2
    assert not marker.exists()


def test_workflow_render_sees_typed_values_in_conditionals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Jinja operates on the original typed context values (the placeholder
    # scheme broke this: ``{% if "LGTM" in review._raw %}`` took the false
    # branch). Source-aware rendering keeps value semantics while leaving
    # model output literal.
    from sase.macro.workflow_executor_utils import render_prompt_template

    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "human")
    rendered = render_prompt_template(
        '{% if "LGTM" in review._raw %}approved{% else %}changes{% endif %}'
        " :: {{ review._raw }}",
        {"review": {"_raw": "LGTM"}},
    )

    assert "approved" in rendered
    assert "LGTM" in rendered


def test_workflow_model_output_cannot_reintroduce_cmdsub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_marker = tmp_path / "raw-response-command-ran"
    response_marker = tmp_path / "response-command-ran"
    monkeypatch.chdir(tmp_path)
    raw = "$(touch raw-response-command-ran)"
    response = "$(touch response-command-ran)"
    early = preprocess_prompt_early(
        "Prior output: {{ step._raw }}; response: {{ _response }}",
        context={"step": {"_raw": raw}, "_response": response},
    )

    result = preprocess_prompt_late(
        early.prompt,
        file_ref_mode="skip",
    )

    assert raw in result
    assert response in result
    assert not raw_marker.exists()
    assert not response_marker.exists()
