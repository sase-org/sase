"""Gate-shell transaction refusal from host finalizer turns."""

from __future__ import annotations

from typing import Any

import pytest

from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV
from sase.gate_shell import transaction as transaction_module
from sase.gate_shell.models import GateShellError, GateShellLaneError
from sase.gate_shell.transaction import create_gate_shell


def _shell_gate_spec() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "request_id": "finalizer-refused",
        "kind": "custom",
        "producer": {"agent": "agent-1"},
        "payload": {},
        "presentation": {"title": "Review action"},
        "query": "approve OR reject",
        "primary_branch": ["approve"],
        "options": [
            {
                "id": "approve",
                "label": "Approve",
                "command": {"argv": ["commands/approve"]},
            },
            {
                "id": "reject",
                "label": "Reject",
                "command": {"argv": ["commands/reject"]},
            },
        ],
        "shell": {"next": {"prompt": "Continue after approval."}},
    }


def test_finalizer_owned_turn_refuses_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    monkeypatch.setattr(
        transaction_module,
        "_resolve_project_name",
        lambda: pytest.fail("project resolution must not run"),
    )
    monkeypatch.setattr(
        transaction_module,
        "create_gate_shell_member",
        lambda *args, **kwargs: pytest.fail("member creation must not run"),
    )
    monkeypatch.setattr(
        transaction_module,
        "move_gate_shell_claim",
        lambda *args, **kwargs: pytest.fail("claim movement must not run"),
    )

    with pytest.raises(GateShellError, match="host finalizer turn"):
        create_gate_shell(_shell_gate_spec())


def test_non_finalizer_turn_continues_to_normal_creation_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "0")
    observed: list[str] = []

    def _resolve_project_name() -> str:
        observed.append("resolved")
        raise GateShellLaneError("creation continued")

    monkeypatch.setattr(
        transaction_module, "_resolve_project_name", _resolve_project_name
    )

    with pytest.raises(GateShellLaneError, match="creation continued"):
        create_gate_shell(_shell_gate_spec())

    assert observed == ["resolved"]
