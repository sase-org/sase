from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.dispatch.mutations as mutations
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


def _locator(
    install: str,
    agent: str = "worker",
    *,
    run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logical": {
            "schema_version": 1,
            "project": {
                "schema_version": 1,
                "origin": {"schema_version": 1, "installation_id": install},
                "project_id": "proj",
            },
            "agent_id": agent,
            "family_id": None,
        },
        "shell_id": "ace-run",
        "run_id": run_id,
        "attempt_id": "attempt-0",
    }


def _snapshot(machine: MachineRecord, agent: str = "worker") -> dict[str, Any]:
    locator = _locator(machine.pinned_installation_id, agent)
    return {
        "alias": machine.alias,
        "origin_installation_id": machine.pinned_installation_id,
        "exact_locator": locator,
        "row_revision": {
            "schema_version": 1,
            "logical_key": "logical-key",
            "revision": 3,
        },
        "capabilities": {"resource": ["lifecycle.stop"]},
    }


def _rust_binding(name: str) -> Any:
    if name == "fleet_installation_identity_ensure":
        return lambda _home: {"record": {"installation_id": "source-install"}}
    if name == "fleet_mutation_payload_fingerprint":
        return lambda _intent: {"schema_version": 1, "sha256": "a" * 64}
    if name == "fleet_validate_mutation_request":
        return lambda request: request
    if name == "fleet_partition_bulk_targets":
        return lambda targets: {
            "schema_version": 1,
            "groups": [
                {
                    "origin_installation_id": item.get("origin_installation_id"),
                    "alias": item.get("alias"),
                    "targets": [item],
                }
                for item in targets
                if item.get("origin_installation_id")
            ],
            "unattributed": [
                item for item in targets if not item.get("origin_installation_id")
            ],
        }
    if name == "fleet_logical_locator_key":
        return lambda locator: str(
            locator.get("agent_id") or locator["logical"]["agent_id"]
        )
    raise AssertionError(f"unexpected binding: {name}")


def test_remote_mutation_submits_and_replays_same_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    calls: list[dict[str, Any]] = []

    class Facade:
        def mutate_sync(
            self, target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            calls.append(request)
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new"
                            if len(calls) == 1
                            else "return_original_receipt",
                            "reason": "unseen_in_window"
                            if len(calls) == 1
                            else "same_scoped_key_and_payload",
                            "receipt": {
                                "state": "settled",
                                "message": "killed",
                                "logical_locator": request["intent"]["target"][
                                    "logical"
                                ],
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    first = mutations._submit_remote_mutation(
        alias="apollo",
        kind="stop",
        snapshot=_snapshot(machine),
        operation_id="op-1",
    )
    second = mutations._submit_remote_mutation(
        alias="apollo",
        kind="stop",
        snapshot=_snapshot(machine),
        operation_id="op-1",
    )
    assert first.outcome == "applied"
    assert "apollo" in first.message
    assert second.outcome == "already_settled"
    assert len(calls) == 1


def test_remote_mutation_unsent_when_worker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)

    class Facade:
        def mutate_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise mutations.FederationWorkerUnavailable(
                "no configured dispatch machines"
            )

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    with pytest.raises(mutations.RemoteDispatchMutationError, match="was not sent"):
        mutations._submit_remote_mutation(
            alias="apollo",
            kind="stop",
            snapshot=_snapshot(machine),
        )


def test_bulk_partition_reports_per_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    apollo = _machine("apollo", "a")
    bravo = _machine("bravo", "b")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(
        mutations, "load_dispatch_config", lambda: _config(apollo, bravo)
    )
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    submitted: list[str] = []

    class Facade:
        def mutate_sync(
            self, target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            submitted.append(target)
            if target == "bravo":
                raise mutations.FederationWorkerUnavailable("offline")
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new",
                            "reason": "unseen_in_window",
                            "receipt": {"state": "settled", "message": "ok"},
                        }
                    }
                ]
            }

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    results = mutations.submit_remote_mutations(
        [_snapshot(apollo), _snapshot(bravo, "other")],
        kind="stop",
    )
    assert {item.alias for item in results} == {"apollo", "bravo"}
    assert any(item.outcome == "applied" for item in results)
    assert any(item.outcome == "unsent" for item in results)


def test_capability_missing_refuses_without_remote_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    snapshot = _snapshot(machine)
    snapshot["capabilities"] = {"resource": ["lifecycle.retry"]}

    class Facade:
        def mutate_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("capability-missing mutations must not be sent")

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    with pytest.raises(
        mutations.RemoteDispatchMutationError, match="capability_missing"
    ):
        mutations._submit_remote_mutation(
            alias="apollo",
            kind="stop",
            snapshot=snapshot,
        )


def test_precondition_mismatch_and_stale_revision_are_typed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)

    class Facade:
        def mutate_sync(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "precondition_mismatch",
                            "reason": "stale_revision",
                            "receipt": {"state": "failed", "message": "stale"},
                        }
                    }
                ]
            }

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    with pytest.raises(
        mutations.RemoteDispatchMutationError, match="stale_revision"
    ) as exc:
        mutations._submit_remote_mutation(
            alias="apollo",
            kind="stop",
            snapshot=_snapshot(machine),
            operation_id="op-stale",
        )
    assert exc.value.outcome == "precondition_failed"


def test_replaced_same_logical_agent_rejects_old_exact_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    old_snapshot = _snapshot(machine, "worker")
    replacement_exact = _locator(
        machine.pinned_installation_id,
        "worker",
        run_id="run-2",
    )
    submitted: list[dict[str, Any]] = []

    class Facade:
        def mutate_sync(
            self,
            target: str,
            request: dict[str, Any],
            **_kwargs: Any,
        ) -> dict[str, Any]:
            submitted.append({"target": target, "request": request})
            assert request["intent"]["target"] == old_snapshot["exact_locator"]
            assert request["intent"]["target"] != replacement_exact
            assert request["intent"]["row_revision"] == old_snapshot["row_revision"]
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "precondition_mismatch",
                            "reason": "exact_instance_replaced",
                            "receipt": {
                                "state": "failed",
                                "message": "old worker instance was replaced",
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)

    (result,) = mutations.submit_remote_mutations([old_snapshot], kind="stop")

    assert submitted[0]["target"] == "apollo"
    assert result.outcome == "precondition_failed"
    assert result.message == (
        "stop on apollo precondition_failed: exact_instance_replaced"
    )


def test_lost_reply_reconciles_under_the_same_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    keys: list[dict[str, Any]] = []

    class Facade:
        def mutate_sync(
            self, _target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            keys.append(request["key"])
            if len(keys) == 1:
                raise mutations.FederationWorkerResponseError({"message": "lost reply"})
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "return_original_receipt",
                            "reason": "same_scoped_key_and_payload",
                            "receipt": {
                                "state": "settled",
                                "message": "Stop requested on apollo",
                            },
                        }
                    }
                ]
            }

    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    with pytest.raises(mutations.RemoteDispatchMutationError, match="uncertain"):
        mutations._submit_remote_mutation(
            alias="apollo",
            kind="stop",
            snapshot=_snapshot(machine),
            operation_id="op-lost",
        )
    result = mutations._submit_remote_mutation(
        alias="apollo",
        kind="stop",
        snapshot=_snapshot(machine),
        operation_id="op-lost",
    )
    assert result.outcome == "already_settled"
    assert keys[0] == keys[1]


def test_fork_follow_honors_unfollow_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(mutations, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(mutations, "require_rust_binding", _rust_binding)
    activated: list[dict[str, Any]] = []

    class Facade:
        def mutate_sync(
            self, _target: str, request: dict[str, Any], **_kwargs: Any
        ) -> dict[str, Any]:
            return {
                "hosts": [
                    {
                        "payload": {
                            "decision": "accept_new",
                            "reason": "unseen_in_window",
                            "receipt": {
                                "state": "settled",
                                "message": "Fork requested on apollo",
                                "logical_locator": request["intent"]["target"][
                                    "logical"
                                ],
                            },
                        }
                    }
                ]
            }

    snapshot = _snapshot(machine)
    snapshot["capabilities"] = {"resource": ["lifecycle.fork"]}
    monkeypatch.setattr(mutations, "build_federation_facade", Facade)
    monkeypatch.setattr(
        mutations,
        "load_follow_snapshot",
        lambda: type("Snap", (), {"tombstones": ({"logical_key": "worker"},)})(),
    )
    monkeypatch.setattr(
        mutations,
        "activate_dispatch_follow",
        lambda *args, **kwargs: activated.append({"args": args, "kwargs": kwargs}),
    )
    result = mutations._submit_remote_mutation(
        alias="apollo",
        kind="fork",
        snapshot=snapshot,
        fork_prompt="continue",
        operation_id="op-fork",
    )
    assert result.outcome == "applied"
    assert activated == []
