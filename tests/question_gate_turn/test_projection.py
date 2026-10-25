"""Tests for ``sase.question_gate_turn.projection``.

Fixture bundles use the real on-disk bundle shapes (``payload.questions``
with ``header``/``options``/``multiSelect``, the ``option_results[submit]``
response envelope, and ``cancellation.json``). The Rust binding itself is
faked so these tests stay green against cores that predate the
``project_question_round`` binding; the core's own ``question_round``
tests cover the projection logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.question_gate_turn.projection import (
    NumberedQuestionRound,
    QuestionRoundView,
    load_question_round,
    parse_question_round_wire,
)

from tests._rust_extension_module_helpers import install_fake_rust_extension


def _write_bundle(bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "payload": {
                    "questions": [
                        {
                            "question": "Ship it?",
                            "header": "Release",
                            "multiSelect": False,
                            "options": [
                                {
                                    "label": "Yes",
                                    "description": "Ship today",
                                },
                                {"label": "No"},
                            ],
                        }
                    ]
                },
                "auto": {
                    "policy": {
                        "profile": "standard",
                        "rule": "gates.question",
                        "value": "first",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (bundle / "response.json").write_text(
        json.dumps(
            {
                "source": "tui",
                "responded_at_unix": 1_792_243_226.0,
                "feedback": "",
                "option_results": [
                    {
                        "id": "submit",
                        "result": {
                            "answers": [
                                {
                                    "question": "Ship it?",
                                    "selected": ["Yes"],
                                    "custom_feedback": None,
                                }
                            ],
                            "global_note": "",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _wire(**overrides: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "schema_version": 1,
        "gate_id": "gate-1",
        "round_index": 2,
        "asked_by": "lane--0",
        "asked_at_unix": 1_792_243_181.0,
        "status": "answered",
        "gate_state": "answered",
        "data_state": "complete",
        "entries": [
            {
                "index": 0,
                "header": "Release",
                "question": "Ship it?",
                "options": [
                    {"label": "Yes", "description": "Ship today"},
                    {"label": "No"},
                ],
                "multi_select": False,
                "recommended_index": 0,
                "recommendation_basis": "option_order",
                "answer": {"selected": ["Yes"], "custom_feedback": None},
                "recommendation_match": "followed",
            }
        ],
        "global_note": None,
        "provenance": {
            "channel": "tui",
            "actor": "human",
            "policy": None,
            "responded_at_unix": 1_792_243_226.0,
        },
        "cancellation": None,
    }
    wire.update(overrides)
    return wire


def test_loader_forwards_bundle_contents_to_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    seen: dict[str, Any] = {}

    def project_question_round(request: dict[str, Any]) -> dict[str, Any]:
        seen["request"] = request
        return _wire()

    install_fake_rust_extension(
        monkeypatch, project_question_round=project_question_round
    )
    view = load_question_round(
        gate_id="gate-1",
        gate_state="answered",
        bundle_path=str(bundle),
        asked_by="lane--0",
        asked_at_unix=1_792_243_181.0,
        round_index=2,
    )
    request = seen["request"]
    assert request["schema_version"] == 1
    assert request["gate"]["gate_id"] == "gate-1"
    assert request["gate"]["round_index"] == 2
    questions = request["request"]["payload"]["questions"]
    assert questions[0]["header"] == "Release"
    assert questions[0]["options"][0]["description"] == "Ship today"
    answers = request["response"]["option_results"][0]["result"]["answers"]
    assert answers[0]["selected"] == ["Yes"]
    assert "cancellation" not in request

    assert isinstance(view, QuestionRoundView)
    assert view.gate_id == "gate-1"
    assert view.status == "answered"
    assert view.data_state == "complete"
    assert len(view.entries) == 1
    entry = view.entries[0]
    assert entry.header == "Release"
    assert entry.options[0].label == "Yes"
    assert entry.options[0].description == "Ship today"
    assert entry.options[1].label == "No"
    assert entry.answer is not None
    assert entry.answer.selected == ("Yes",)
    assert entry.recommendation_match == "followed"
    assert view.provenance is not None
    assert view.provenance.actor == "human"
    assert view.provenance.channel == "tui"


def test_loader_with_cancellation_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    (bundle / "response.json").unlink()
    (bundle / "cancellation.json").write_text(
        json.dumps(
            {
                "reason": "timeout",
                "source": "gate_shell_reclaim",
                "cancelled_at_unix": 1_789_320_389.0,
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, Any] = {}

    def project_question_round(request: dict[str, Any]) -> dict[str, Any]:
        seen["request"] = request
        return _wire(
            status="timed_out",
            entries=[],
            cancellation={
                "reason": "timeout",
                "source": "gate_shell_reclaim",
                "cancelled_at_unix": 1_789_320_389.0,
            },
        )

    install_fake_rust_extension(
        monkeypatch, project_question_round=project_question_round
    )
    view = load_question_round(
        gate_id="gate-1",
        gate_state="timeout",
        bundle_path=str(bundle),
        asked_by="lane--0",
        asked_at_unix=1_792_243_181.0,
    )
    assert "response" not in seen["request"]
    assert seen["request"]["cancellation"]["reason"] == "timeout"
    assert view.status == "timed_out"
    assert view.cancellation is not None
    assert view.cancellation.reason == "timeout"


def test_loader_returns_unavailable_when_binding_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def project_question_round(request: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("unsupported_question_round_schema: stale core")

    install_fake_rust_extension(
        monkeypatch, project_question_round=project_question_round
    )
    view = load_question_round(
        gate_id="gate-9",
        gate_state="answered",
        bundle_path=str(tmp_path / "missing"),
        asked_by="lane--3",
        asked_at_unix=1.0,
        round_index=4,
    )
    assert view.data_state == "unavailable"
    assert view.gate_id == "gate-9"
    assert view.gate_state == "answered"
    assert view.asked_by == "lane--3"
    assert view.round_index == 4
    assert view.entries == ()


def test_loader_returns_unavailable_on_non_mapping_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_rust_extension(
        monkeypatch, project_question_round=lambda _request: ["nope"]
    )
    view = load_question_round(
        gate_id="gate-1",
        gate_state="pending",
        bundle_path=str(tmp_path),
        asked_by=None,
        asked_at_unix=None,
    )
    assert view.data_state == "unavailable"


def test_parse_wire_is_tolerant() -> None:
    view = parse_question_round_wire(
        {
            "gate_id": 42,
            "status": ["answered"],
            "data_state": "complete",
            "round_index": True,
            "asked_at_unix": "soon",
            "entries": [
                {"question": "Q?", "options": [{"label": "Yes"}, "bogus"]},
                "bogus",
            ],
            "provenance": {"actor": "human", "policy": {"profile": "x"}},
            "surprise": "ignored",
        }
    )
    assert view.gate_id == ""
    assert view.status == "unknown"
    assert view.data_state == "complete"
    assert view.round_index is None
    assert view.asked_at_unix is None
    assert len(view.entries) == 2
    assert view.entries[0].question == "Q?"
    assert len(view.entries[0].options) == 1
    assert view.entries[1].question == ""
    assert view.provenance is not None
    assert view.provenance.actor == "human"
    assert view.provenance.policy is not None
    assert view.provenance.policy.profile == "x"


def test_parse_wire_accepts_empty_mapping() -> None:
    view = parse_question_round_wire({})
    assert view.data_state == "unavailable"
    assert view.entries == ()
    assert view.provenance is None


def test_numbered_round_defaults() -> None:
    numbered = NumberedQuestionRound(view=QuestionRoundView(gate_id="g"))
    assert numbered.first_number == 1
    assert numbered.member_label == "gate"
    assert numbered.deadline_unix is None
