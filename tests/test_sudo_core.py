"""Coverage for sudo core handshake validation."""

from __future__ import annotations

from typing import Any

import pytest

from sase.notification_gates.models import GateError
from sase.sudo.core import _RustSudoCoreBinding


def test_validate_handshake_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    def fake_require(name: str) -> Any:
        assert name == "sudo_validate_handshake"

        def binding(
            handshake: dict[str, Any],
            manifest: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            calls.append((handshake, manifest))
            return {"kind": "sudo_exec_started", **handshake}

        return binding

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)
    handshake = {"kind": "sudo_exec_started", "executor_pid": 9}
    manifest = {"request_id": "sudo-1"}

    result = _RustSudoCoreBinding().validate_handshake(handshake, manifest)

    assert calls == [(handshake, manifest)]
    assert result["executor_pid"] == 9


def test_validate_handshake_translates_binding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(_name: str) -> Any:
        def binding(
            handshake: dict[str, Any],
            manifest: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            del handshake, manifest
            raise RuntimeError("SHA-256 mismatch")

        return binding

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)

    with pytest.raises(GateError) as excinfo:
        _RustSudoCoreBinding().validate_handshake({"kind": "sudo_exec_started"})

    assert excinfo.value.code == "invalid_sudo_handshake"
    assert excinfo.value.target == "handshake"
    assert "SHA-256 mismatch" in str(excinfo.value)


def test_validate_handshake_rejects_non_object_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.sudo.core.require_rust_binding",
        lambda _name: lambda handshake, manifest=None: ["nope"],
    )

    with pytest.raises(GateError) as excinfo:
        _RustSudoCoreBinding().validate_handshake({"kind": "sudo_exec_started"})

    assert excinfo.value.code == "invalid_sudo_handshake"
    assert "non-object" in str(excinfo.value)


def test_classify_attempt_liveness_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def fake_require(name: str) -> Any:
        assert name == "sudo_classify_attempt_liveness"

        def binding(
            attempt: dict[str, Any],
            facts: dict[str, Any],
        ) -> dict[str, Any]:
            calls.append((attempt, facts))
            return {
                "schema_version": 1,
                "classification": "unknown",
                "reason": "remote",
            }

        return binding

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)

    result = _RustSudoCoreBinding().classify_attempt_liveness(
        {"gate_id": "sudo-1"}, {"finalize_proc_live": None}
    )

    assert calls == [({"gate_id": "sudo-1"}, {"finalize_proc_live": None})]
    assert result["classification"] == "unknown"


def test_authorize_settlement_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(name: str) -> Any:
        assert name == "sudo_authorize_settlement"
        return lambda request: {"authorized": True, **request}

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)

    result = _RustSudoCoreBinding().authorize_settlement({"gate_id": "sudo-1"})

    assert result["authorized"] is True
    assert result["gate_id"] == "sudo-1"


def test_fit_ledger_calls_rust_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[dict[str, Any], int]] = []

    def fake_require(name: str) -> Any:
        assert name == "sudo_fit_ledger"

        def binding(ledger: dict[str, Any], max_json_bytes: int) -> dict[str, Any]:
            calls.append((ledger, max_json_bytes))
            return {**ledger, "fitted": True}

        return binding

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)
    ledger = {"schema_version": 1, "entries": []}

    result = _RustSudoCoreBinding().fit_ledger(ledger, 1024)

    assert calls == [(ledger, 1024)]
    assert result["fitted"] is True


def test_fit_ledger_translates_binding_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require(_name: str) -> Any:
        def binding(ledger: dict[str, Any], max_json_bytes: int) -> dict[str, Any]:
            del ledger, max_json_bytes
            raise RuntimeError("cannot fit within 8 bytes")

        return binding

    monkeypatch.setattr("sase.sudo.core.require_rust_binding", fake_require)

    with pytest.raises(GateError) as excinfo:
        _RustSudoCoreBinding().fit_ledger({"schema_version": 1}, 8)

    assert excinfo.value.code == "invalid_sudo_ledger"
    assert excinfo.value.target == "ledger"
    assert "cannot fit" in str(excinfo.value)


def test_fit_ledger_rejects_non_object_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.sudo.core.require_rust_binding",
        lambda _name: lambda ledger, max_json_bytes: ["nope"],
    )

    with pytest.raises(GateError) as excinfo:
        _RustSudoCoreBinding().fit_ledger({"schema_version": 1}, 1024)

    assert excinfo.value.code == "invalid_sudo_ledger"
    assert "non-object" in str(excinfo.value)
