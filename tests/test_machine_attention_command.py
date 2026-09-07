from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.dispatch.attention import RemoteAttentionResult
from sase.feature_flags import override_flags
from sase.ops.models import DurableOperationRequest
from sase.ops.commands import machine_attention
from sase.ops.commands.machine_attention import handle_machine_attention_command


def test_machine_attention_refuses_when_remote_dispatch_disabled() -> None:
    args = SimpleNamespace(
        machine_attention_subcommand="answer",
        alias="apollo",
        request="question-0001",
        answer="ship it",
        timeout=None,
        json=False,
        operation_request_path=None,
        operation_result_path=None,
    )
    with override_flags(remote_dispatch=False):
        code = handle_machine_attention_command(args)
    assert code != 0


def test_machine_attention_requires_a_known_subcommand() -> None:
    args = SimpleNamespace(
        machine_attention_subcommand=None,
        alias="apollo",
        request="question-0001",
        answer=None,
        timeout=None,
        json=False,
        operation_request_path=None,
        operation_result_path=None,
    )
    with override_flags(remote_dispatch=True):
        code = handle_machine_attention_command(args)
    assert code == 2


def test_machine_attention_sidecar_intent_yields_typed_durable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_intent = {
        "kind": "gate",
        "request_key": {
            "schema_version": 1,
            "origin_installation_id": "sase_inst_v1_" + "a" * 64,
            "request_id": "gate-00000001",
            "pending_action_prefix": "gate-000",
        },
        "observed_revision": 3,
        "selected_option_ids": ["approve"],
    }

    def _fake_load_request(_operation: str, _args: object) -> DurableOperationRequest:
        return DurableOperationRequest(
            operation=machine_attention.MACHINE_ATTENTION_ACTION,
            payload={
                "alias": "apollo",
                "request_id": "gate-00000001",
                "intent": full_intent,
            },
        )

    captured: dict[str, Any] = {}

    def _fake_submit(
        alias: str,
        intent: Any,
        *,
        operation_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> RemoteAttentionResult:
        captured["alias"] = alias
        captured["intent"] = dict(intent)
        return RemoteAttentionResult(
            alias=alias,
            outcome="applied",
            message="Approved on apollo",
            receipt={"state": "settled", "outcome": "applied"},
            decision="accept_new",
            reason="unseen_in_window",
        )

    monkeypatch.setattr(machine_attention, "load_request", _fake_load_request)
    monkeypatch.setattr(
        machine_attention, "submit_remote_attention_answer", _fake_submit
    )
    args = SimpleNamespace(
        machine_attention_subcommand="approve",
        alias="apollo",
        request="gate-00000001",
        options=[],
        feedback=None,
        timeout=None,
        json=True,
        operation_request_path=None,
        operation_result_path=None,
    )
    with override_flags(remote_dispatch=True):
        code = handle_machine_attention_command(args)
    assert code == 0
    assert captured["alias"] == "apollo"
    assert captured["intent"] == full_intent
