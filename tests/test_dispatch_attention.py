from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.dispatch.attention as attention
from sase.dispatch.models import DispatchConfig, MachineRecord, ProviderSettings
from tests.conftest import redirect_sase_home


def _pin(hex_char: str = "a") -> str:
    return "sase_inst_v1_" + hex_char * 64


def _machine(alias: str = "apollo", hex_char: str = "a") -> MachineRecord:
    return MachineRecord(
        alias=alias,
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref=f"fleet:{alias}",
        pinned_installation_id=_pin(hex_char),
    )


def _config(*machines: MachineRecord) -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True)
        },
        machines=machines,
        request_timeout_seconds=5.0,
    )


def _request_key(install: str, request_id: str = "gate-00000001") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "origin_installation_id": install,
        "request_id": request_id,
        "pending_action_prefix": request_id[:8],
    }


def _gate_intent(install: str, *, revision: int = 1) -> dict[str, Any]:
    return {
        "kind": "gate",
        "request_key": _request_key(install),
        "observed_revision": revision,
        "selected_option_ids": ["approve"],
        "feedback": None,
        "question_choice": None,
        "question_index": None,
        "selected_option_id": None,
        "selected_option_label": None,
        "selected_option_index": None,
        "custom_answer": None,
        "global_note": None,
    }


def _rust_binding(name: str) -> Any:
    if name == "fleet_installation_identity_ensure":
        return lambda _home: {"record": {"installation_id": "source-install"}}
    if name == "fleet_attention_payload_fingerprint":
        return lambda _intent: {"schema_version": 1, "sha256": "a" * 64}
    if name == "fleet_validate_attention_request":
        return lambda request: request
    raise AssertionError(f"unexpected binding: {name}")


def test_remote_attention_submits_and_replays_same_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)
    calls: list[dict[str, Any]] = []

    class Facade:
        def resolve_attention_sync(
            self, target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            calls.append(request)
            first = len(calls) == 1
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new"
                            if first
                            else "return_original_receipt",
                            "reason": "unseen_in_window"
                            if first
                            else "same_scoped_key_and_payload",
                            "receipt": {
                                "state": "settled",
                                "outcome": "applied",
                                "message": "Approved on apollo",
                                "settled_response": {
                                    "selected_option_ids": ["approve"]
                                },
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    first = attention.submit_remote_attention_answer(
        "apollo", _gate_intent(machine.pinned_installation_id), operation_id="op-1"
    )
    second = attention.submit_remote_attention_answer(
        "apollo", _gate_intent(machine.pinned_installation_id), operation_id="op-1"
    )
    assert first.outcome == "applied"
    assert first.settled_response == {"selected_option_ids": ["approve"]}
    assert second.decision == "return_original_receipt"
    assert len(calls) == 1


def test_remote_attention_unsent_when_worker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise attention.FederationWorkerUnavailable(
                "no configured dispatch machines"
            )

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    with pytest.raises(
        attention.RemoteDispatchAttentionError, match="was not sent"
    ) as exc:
        attention.submit_remote_attention_answer(
            "apollo", _gate_intent(machine.pinned_installation_id)
        )
    assert exc.value.outcome == "unsent"


def test_remote_attention_uncertain_when_worker_response_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise attention.FederationWorkerResponseError({"message": "lost reply"})

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    with pytest.raises(
        attention.RemoteDispatchAttentionError, match="uncertain"
    ) as exc:
        attention.submit_remote_attention_answer(
            "apollo", _gate_intent(machine.pinned_installation_id)
        )
    assert exc.value.outcome == "uncertain"


def test_remote_attention_surfaces_stale_revision_outcome_from_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new",
                            "reason": "unseen_in_window",
                            "receipt": {
                                "state": "settled",
                                "outcome": "stale_revision",
                                "settled_by_host_label": "apollo",
                                "message": "Attention revision is stale on apollo",
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    result = attention.submit_remote_attention_answer(
        "apollo", _gate_intent(machine.pinned_installation_id)
    )
    assert result.outcome == "stale_revision"
    assert result.message == "Attention revision is stale on apollo"


def test_remote_attention_already_settled_names_the_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new",
                            "reason": "unseen_in_window",
                            "receipt": {
                                "state": "settled",
                                "outcome": "already_settled",
                                "settled_by_host_label": "apollo",
                                "settled_response": {"answer": "42"},
                                "message": "Already answered on apollo",
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    result = attention.submit_remote_attention_answer(
        "apollo", _gate_intent(machine.pinned_installation_id)
    )
    assert result.outcome == "already_settled"
    assert result.message == "Already answered on apollo"
    assert result.settled_response == {"answer": "42"}


def test_remote_attention_unknown_alias_refuses_without_remote_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config())
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("unenrolled aliases must not be sent")

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    with pytest.raises(attention.RemoteDispatchAttentionError, match="not enrolled"):
        attention.submit_remote_attention_answer("apollo", _gate_intent(_pin()))


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("capability_missing", "Attention capability missing on apollo"),
        ("unknown_request", "Attention request was not found on apollo"),
    ],
)
def test_remote_attention_surfaces_capability_missing_and_unknown_request(
    outcome: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)

    class Facade:
        def resolve_attention_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new",
                            "reason": "unseen_in_window",
                            "receipt": {
                                "state": "settled",
                                "outcome": outcome,
                                "message": message,
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    result = attention.submit_remote_attention_answer(
        "apollo", _gate_intent(machine.pinned_installation_id)
    )
    assert result.outcome == outcome
    assert result.message == message


def test_remote_attention_lost_reply_reconciles_under_the_same_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attention, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(attention, "require_rust_binding", _rust_binding)
    keys: list[dict[str, Any]] = []

    class Facade:
        def resolve_attention_sync(
            self, _target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            keys.append(request["key"])
            if len(keys) == 1:
                raise attention.FederationWorkerResponseError({"message": "lost reply"})
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "return_original_receipt",
                            "reason": "same_scoped_key_and_payload",
                            "receipt": {
                                "state": "settled",
                                "outcome": "applied",
                                "message": "Approved on apollo",
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(attention, "build_federation_facade", Facade)
    with pytest.raises(attention.RemoteDispatchAttentionError, match="uncertain"):
        attention.submit_remote_attention_answer(
            "apollo",
            _gate_intent(machine.pinned_installation_id),
            operation_id="op-lost",
        )
    result = attention.submit_remote_attention_answer(
        "apollo",
        _gate_intent(machine.pinned_installation_id),
        operation_id="op-lost",
    )
    assert result.decision == "return_original_receipt"
    assert result.outcome == "applied"
    assert keys[0] == keys[1]


def test_fetch_remote_attention_skips_read_when_no_logical_keys() -> None:
    result = attention.fetch_remote_attention([])
    assert result["disabled"] is True
    assert result["hosts"] == []
