"""Tests for ``sase.core.question_round_facade``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core import question_round_facade

from tests._rust_extension_module_helpers import install_fake_rust_extension


def _request(**overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": question_round_facade.QUESTION_ROUND_WIRE_SCHEMA_VERSION,
        "gate": {"gate_id": "gate-1", "gate_state": "pending"},
        "request": {
            "payload": {
                "questions": [{"question": "Probe?", "options": [{"label": "Yes"}]}]
            }
        },
    }
    request.update(overrides)
    return request


def test_question_round_wire_schema_version_is_one() -> None:
    assert question_round_facade.QUESTION_ROUND_WIRE_SCHEMA_VERSION == 1


def test_project_question_round_returns_binding_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def project_question_round(request: dict[str, Any]) -> dict[str, Any]:
        seen["request"] = request
        return {"gate_id": "gate-1", "status": "pending"}

    install_fake_rust_extension(
        monkeypatch, project_question_round=project_question_round
    )
    result = question_round_facade.project_question_round(_request())
    assert result == {"gate_id": "gate-1", "status": "pending"}
    assert seen["request"]["gate"]["gate_id"] == "gate-1"


def test_project_question_round_rejects_non_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_rust_extension(
        monkeypatch, project_question_round=lambda _request: ["not", "a", "dict"]
    )
    with pytest.raises(TypeError):
        question_round_facade.project_question_round(_request())
