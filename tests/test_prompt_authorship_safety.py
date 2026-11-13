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
        agent_authored=True,
        file_ref_mode="skip",
    )

    assert command in result
    assert "handoff prompt" in result
    assert not marker.exists()


def test_human_authored_late_preprocessing_keeps_cmdsub_behavior() -> None:
    result = preprocess_prompt_late(
        "human prompt $(printf human)",
        file_ref_mode="skip",
    )

    assert result == "human prompt human\n"


def test_handoff_macros_expand_while_cmdsub_stays_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "macro-command-ran"
    monkeypatch.chdir(tmp_path)
    command = "$(touch macro-command-ran)"
    early = preprocess_prompt_early(
        f"#handoff {command}",
        extra_macros={"handoff": Macro(name="handoff", content="expanded")},
    )

    result = preprocess_prompt_late(
        early.prompt,
        agent_authored=True,
        file_ref_mode="skip",
    )

    assert "expanded" in result
    assert command in result
    assert not marker.exists()


def test_workflow_model_output_interpolated_twice_stays_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.macro.workflow_executor_utils import render_prompt_template

    marker = tmp_path / "twice-response-command-ran"
    monkeypatch.chdir(tmp_path)
    raw = "$(touch twice-response-command-ran)"

    rendered = render_prompt_template(
        "A {{ step._raw }} B {{ step._raw }} C",
        {"step": {"_raw": raw}},
    )

    assert "__SASE_MODEL_OUTPUT_" not in rendered
    assert rendered.count(raw) == 2
    assert rendered.count("%macros_enabled:false") == 2

    result = preprocess_prompt_late(
        rendered,
        agent_authored=False,
        file_ref_mode="skip",
    )

    assert raw in result
    assert result.count(raw) == 2
    assert not marker.exists()


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
        agent_authored=False,
        file_ref_mode="skip",
    )

    assert raw in result
    assert response in result
    assert not raw_marker.exists()
    assert not response_marker.exists()
