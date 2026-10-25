"""Tests for the GATE detail section and ANSI output rendering."""

from __future__ import annotations

import json
import types
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_gate_section import (
    build_gate_phase,
    build_gate_section,
    gate_phase_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_questions_render import (
    QuestionNumberCursor,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

import sase_core_rs as _real_extension

from tests._rust_extension_module_helpers import patch_rust_extension


def _console_lines(rendered: object, *, width: int = 120) -> list[str]:
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(rendered, end="")
    return output.getvalue().splitlines()


def _gate_agent(
    tmp_path: Path,
    *,
    status: str = "APPROVE",
    gate_state: str = "pending",
    gate_kind: str = "approval",
    gate_start_status: str = "APPROVE",
    gate_stop_status: str = "APPROVED",
    output: str | None = None,
    output_truncated: bool = False,
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    output_path: str | None = None
    if output is not None:
        path = tmp_path / "gate.log"
        path.write_text(output, encoding="utf-8")
        output_path = str(path)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gate-row",
        project_file="/tmp/gate.sase",
        status=status,
        status_bucket="Running" if gate_state == "settling" else "Stopped",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--gate",
        agent_session="alpha",
        agent_session_role="gate",
        role_suffix="--gate",
        gate_id="g123abc456def",
        gate_kind=gate_kind,
        gate_state=gate_state,
        gate_start_status=gate_start_status,
        gate_stop_status=gate_stop_status,
        gate_accent="#0BCDEC",
        gate_label="Approve deploy",
        gate_reason="Release needs confirmation",
        gate_timeout_seconds=2700.0,
        gate_output_path=output_path,
        gate_output_truncated=output_truncated,
        gate_next_action="Continue the deployment.",
        gate_followup_outcome="not-launchable" if gate_state == "failed" else None,
        gate_followup_error="No branch selected" if gate_state == "failed" else None,
    )


def _render(agent: Agent) -> object:
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
    return mock_update.call_args.args[0]


def _annotate(value: str | Text) -> Text:
    return value if isinstance(value, Text) else Text(value)


def _gate_phase_text(agent: Agent) -> Text:
    result = Text(end="")
    for part in build_gate_phase(agent, annotate=_annotate):
        assert isinstance(part, Text)
        result.append_text(part)
    return result


def test_gate_row_renders_gate_section_fields(tmp_path: Path) -> None:
    rendered = _render(_gate_agent(tmp_path))

    assert isinstance(rendered, Group)
    text = "\n".join(_console_lines(rendered))

    assert "GATE" in text
    assert "Approve deploy" in text
    assert "approval" in text
    assert "APPROVE" in text
    assert "APPROVED" in text
    assert "pending" in text
    assert "Release needs confirmation" in text
    assert "Continue the deployment." in text
    assert "g123abc456def" in text
    assert "sase gate show" in text
    assert "AGENT PROMPT" not in text
    assert "AGENT REPLY" not in text


def test_sudo_gate_section_renders_execution_proc(tmp_path: Path) -> None:
    agent = _gate_agent(
        tmp_path,
        status="SUDO",
        gate_kind="sudo",
        gate_start_status="SUDO",
        gate_stop_status="SUDOED",
    )
    agent.gate_execution_active = True
    agent.gate_finalize_proc_id = "proc-detach-1"

    section_text = "".join(
        part.plain if hasattr(part, "plain") else str(part)
        for part in build_gate_section(agent)
    )

    assert "Executing:" in section_text
    assert "background proc proc-detach-1" in section_text


def test_gate_row_no_output_shows_placeholder(tmp_path: Path) -> None:
    rendered = _render(_gate_agent(tmp_path))
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "No output yet." in text


def test_gate_row_renders_output_as_ansi_not_markdown(tmp_path: Path) -> None:
    rendered = _render(
        _gate_agent(
            tmp_path,
            output="line one\n**not markdown** `still not markdown`\n",
            output_truncated=True,
        )
    )
    text = "\n".join(_console_lines(rendered))

    assert "OUTPUT" in text
    assert "truncated" in text.lower()
    assert "**not markdown**" in text
    assert "`still not markdown`" in text


def test_gate_phase_text_flattens_agent_session_phase(tmp_path: Path) -> None:
    agent = _gate_agent(
        tmp_path,
        status="APPROVED",
        gate_state="answered",
        output="selected approve\n",
    )

    text = _gate_phase_text(agent).plain

    assert "GATE" in text
    assert "APPROVE" in text
    assert "APPROVED" in text
    assert "answered" in text
    assert "Output:" in text
    assert "selected approve" in text


def test_sudo_gate_phase_and_section_use_typed_status_labels(tmp_path: Path) -> None:
    agent = _gate_agent(
        tmp_path,
        status="SUDO",
        gate_kind="sudo",
        gate_start_status="SUDO",
        gate_stop_status="SUDOED",
    )

    phase_text = _gate_phase_text(agent).plain
    section_text = "".join(
        part.plain if hasattr(part, "plain") else str(part)
        for part in build_gate_section(agent)
    )

    assert "SUDO" in phase_text
    assert "GATE" not in phase_text
    assert "SUDO" in section_text


def test_sudo_gate_answered_phase_uses_settled_label(tmp_path: Path) -> None:
    agent = _gate_agent(
        tmp_path,
        status="SUDOED",
        gate_state="answered",
        gate_kind="sudo",
        gate_start_status="SUDO",
        gate_stop_status="SUDOED",
    )

    text = _gate_phase_text(agent).plain

    assert "SUDOED" in text


def _question_wire(gate_id: str, *, question: str, selected: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "gate_id": gate_id,
        "asked_by": "alpha--0",
        "asked_at_unix": datetime(2026, 8, 12, 9, 0, 0).timestamp(),
        "status": "answered",
        "gate_state": "answered",
        "data_state": "complete",
        "entries": [
            {
                "index": 0,
                "header": "Deploy",
                "question": question,
                "options": [
                    {"label": "Yes", "description": "Ship today"},
                    {"label": "No"},
                ],
                "multi_select": False,
                "recommended_index": 0,
                "recommendation_basis": "option_order",
                "answer": {"selected": [selected], "custom_feedback": None},
                "recommendation_match": (
                    "followed" if selected == "Yes" else "different_option"
                ),
            }
        ],
        "global_note": None,
        "provenance": {
            "channel": "tui",
            "actor": "human",
            "policy": None,
            "responded_at_unix": datetime(2026, 8, 12, 9, 3, 0).timestamp(),
        },
        "cancellation": None,
    }


@pytest.fixture
def question_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake only ``project_question_round``; delegate other bindings.

    Gate rendering touches unrelated extension bindings (live-reply
    timestamps, config layout), so a bare fake would break paths the
    presenter never exercises. Unknown attributes fall through to the
    real wheel while the question projection stays canned.
    """

    def project_question_round(request: dict[str, Any]) -> dict[str, Any]:
        gate_id = request["gate"]["gate_id"]
        first = gate_id.startswith("g111")
        return _question_wire(
            gate_id,
            question="Ship it?" if first else "Roll back?",
            selected="Yes" if first else "No",
        )

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.project_question_round = project_question_round

    def __getattr__(name: str) -> Any:
        return getattr(_real_extension, name)

    fake.__getattr__ = __getattr__  # type: ignore[attr-defined]
    patch_rust_extension(monkeypatch, fake)


def _question_gate_agent(
    tmp_path: Path,
    *,
    gate_id: str = "g111abc456def",
    role_suffix: str = "--gate",
    gate_state: str = "answered",
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="question-gate-row",
        project_file="/tmp/gate.sase",
        status="QUESTION",
        status_bucket="Stopped",
        start_time=started,
        run_start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--gate",
        agent_session="alpha",
        agent_session_role="gate",
        role_suffix=role_suffix,
        gate_id=gate_id,
        gate_kind="question",
        gate_state=gate_state,
        gate_start_status="QUESTION",
        gate_stop_status="ANSWERED",
        gate_accent="#FFAF00",
        gate_label="Ship it?",
        gate_bundle_path=str(tmp_path),
        gate_creator_agent="alpha--0",
        gate_timeout_seconds=2700.0,
    )


def _flatten(parts: list[object]) -> Text:
    text = Text(end="")
    for part in parts:
        assert isinstance(part, Text)
        text.append_text(part)
    return text


def test_question_gate_section_defers_body_to_questions_section(
    tmp_path: Path, question_binding: None
) -> None:
    text = _flatten(
        build_gate_section(
            _question_gate_agent(tmp_path), panel_level=FoldLevel.EXPANDED
        )
    ).plain

    assert "Q1 Deploy" not in text
    assert "human via TUI" not in text
    assert "Option JSON" not in text
    assert "Branches:" not in text


def test_question_gate_section_keeps_shared_fields(
    tmp_path: Path, question_binding: None
) -> None:
    text = _flatten(
        build_gate_section(
            _question_gate_agent(tmp_path), panel_level=FoldLevel.EXPANDED
        )
    ).plain

    assert "Ship it?" in text
    assert "question" in text
    assert "sase gate show" in text


def test_question_gate_section_collapsed_hides_presenter_body(
    tmp_path: Path, question_binding: None
) -> None:
    text = _flatten(
        build_gate_section(
            _question_gate_agent(tmp_path), panel_level=FoldLevel.COLLAPSED
        )
    ).plain

    assert "Q1 " not in text
    assert "human via TUI" not in text
    assert "Ship it?" in text


def test_question_gate_phase_keeps_presenter_body(
    tmp_path: Path, question_binding: None
) -> None:
    text = _flatten(
        build_gate_phase(_question_gate_agent(tmp_path), annotate=_annotate)
    ).plain

    assert "ANSWERED" in text
    assert "human via TUI" in text
    assert "3m after asking" in text
    assert "Q1 Deploy" in text
    assert "Option JSON" not in text
    assert "Branches:" not in text


def test_non_question_gate_keeps_option_json_dump(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "response.json").write_text(
        json.dumps(
            {
                "feedback": "Looks good",
                "option_results": [
                    {"id": "submit", "result": {"answers": []}},
                ],
            }
        ),
        encoding="utf-8",
    )
    agent = _gate_agent(tmp_path, gate_kind="approval")
    agent.gate_bundle_path = str(bundle)

    parts = build_gate_section(agent)

    assert any(not isinstance(part, Text) for part in parts)
    assert "Option JSON" in _flatten([p for p in parts if isinstance(p, Text)]).plain
    assert "Looks good" in _flatten([p for p in parts if isinstance(p, Text)]).plain


def test_build_gate_phase_numbers_question_rounds_continuously(
    tmp_path: Path, question_binding: None
) -> None:
    first = _question_gate_agent(tmp_path)
    second = _question_gate_agent(
        tmp_path, gate_id="g222abc456def", role_suffix="--gate-0"
    )
    numbering = QuestionNumberCursor()

    first_text = _flatten(
        build_gate_phase(first, annotate=_annotate, numbering=numbering)
    ).plain
    second_text = _flatten(
        build_gate_phase(second, annotate=_annotate, numbering=numbering)
    ).plain

    assert "Q1 Deploy" in first_text
    assert "Q2 " not in first_text
    assert "Q2 Deploy" in second_text
    assert "Roll back?" not in first_text


def test_gate_phase_text_stays_text_only_for_question_gates(
    tmp_path: Path, question_binding: None
) -> None:
    text = gate_phase_text(_question_gate_agent(tmp_path), annotate=_annotate).plain

    assert "ANSWERED" in text
    assert "Q1 Deploy" in text
    assert "Option JSON" not in text
