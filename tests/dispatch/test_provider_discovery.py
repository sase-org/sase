"""Dispatch discovery, connection-plan, and provider-operation tests.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.models import MachineRecord
from sase.dispatch.provider_runtime import (
    DispatchProviderExecutionError,
    run_dispatch_provider_operation,
)
from sase.dispatch.providers import (
    connection_plan_for_machine,
    discover_dispatch_candidates,
    discover_dispatch_result,
    hookimpl,
)
from sase.finalizers.bounded_subprocess import BoundedCompletedProcess

LAB_REF = "fake-dispatch-plugin@lab"
OTHER_REF = "fake-dispatch-plugin@other"


class _FakeEntryPoint:
    def __init__(
        self,
        name: str,
        plugin: object,
        *,
        package: str = "fake-dispatch-plugin",
        version: str = "1.0.0",
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = f"fake_dispatch_plugin:{name}"
        self.dist = _FakeDist(package, version)
        self.load_calls = 0
        self._plugin = plugin
        self._error = error

    def load(self) -> object:
        self.load_calls += 1
        if self._error is not None:
            raise self._error
        return self._plugin


class _FakeDist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name}
        self.version = version


def _entry_points_fn(*entry_points: _FakeEntryPoint) -> Any:
    def fake_entry_points(*, group: str) -> tuple[_FakeEntryPoint, ...]:
        assert group == "sase_dispatch"
        return entry_points

    return fake_entry_points


class _FakeProvider:
    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": LAB_REF,
                "display_name": "Lab Fleet Gateway",
                "supports_discovery": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, Any], ...]:
        del config, timeout_seconds
        if provider_ref != LAB_REF:
            return ()
        return (
            {
                "endpoint": "https://lab.example.test",
                "display_name": "Lab Box",
                "machine_selector": "lab",
            },
            # Duplicate of the first candidate; discovery must dedupe it.
            {
                "endpoint": "https://lab.example.test",
                "display_name": "Lab Box",
                "machine_selector": "lab",
            },
            # Candidates without an endpoint are dropped, not fatal.
            {"display_name": "no endpoint"},
        )


def _lab_config(*, enabled: bool) -> Any:
    return load_dispatch_config(
        {
            "dispatch": {
                "providers": {LAB_REF: enabled},
                "discovery": {"enabled_providers": [LAB_REF]},
            }
        }
    )


def _ok_result(
    provider_ref: str,
    operation: str,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "operation": operation,
        "provider_ref": provider_ref,
        "status": "ok",
    }
    payload.update(extra)
    return payload


def test_discover_returns_candidates_from_enabled_provider() -> None:
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())
    calls: list[str] = []

    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del timeout_seconds
        provider_ref = str(provider.provider_ref)
        calls.append(provider_ref)
        assert operation == "discover"
        assert request["provider_ref"] == LAB_REF
        return _ok_result(
            provider_ref,
            operation,
            candidates=[
                {
                    "endpoint": "https://lab.example.test",
                    "display_name": "Lab Box",
                    "machine_selector": "lab",
                },
                {
                    "endpoint": "https://lab.example.test",
                    "display_name": "Lab Box",
                    "machine_selector": "lab",
                },
                {"display_name": "no endpoint"},
            ],
        )

    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(lab_ep),
        operation_runner=run_provider,
    )

    assert [candidate.endpoint for candidate in candidates] == [
        "https://lab.example.test"
    ]
    assert candidates[0].provider_ref == LAB_REF
    assert candidates[0].machine_selector == "lab"
    assert calls == [LAB_REF]
    assert lab_ep.load_calls == 0


def test_dispatch_defaults_enable_tailnet_discovery() -> None:
    config = load_dispatch_config({"dispatch": {}})

    assert config.provider_enabled("builtin@tailnet") is True
    assert config.discovery_enabled_provider_refs == ("builtin@tailnet",)


def test_discover_skips_disabled_provider() -> None:
    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del provider, operation, request, timeout_seconds
        raise AssertionError("disabled provider must not run")

    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=False),
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", _FakeProvider())),
        operation_runner=run_provider,
    )

    assert candidates == ()


def test_discover_reports_disabled_selected_provider() -> None:
    result = discover_dispatch_result(
        config=load_dispatch_config(
            {
                "dispatch": {
                    "providers": {LAB_REF: False},
                    "discovery": {"enabled_providers": [LAB_REF]},
                }
            }
        ),
        entry_points_fn=_entry_points_fn(),
    )

    assert result.candidates == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "dispatch_provider_disabled"
    ]


def test_discover_without_selected_providers_does_no_work() -> None:
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    candidates = discover_dispatch_candidates(
        config=load_dispatch_config(
            {"dispatch": {"discovery": {"enabled_providers": []}}}
        ),
        entry_points_fn=_entry_points_fn(lab_ep),
    )

    assert candidates == ()
    assert lab_ep.load_calls == 0


def test_discover_failure_isolated_to_selected_provider() -> None:
    config = load_dispatch_config(
        {
            "dispatch": {
                "providers": {LAB_REF: True, OTHER_REF: True},
                "discovery": {"enabled_providers": [LAB_REF, OTHER_REF]},
            }
        }
    )

    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del request, timeout_seconds
        provider_ref = str(provider.provider_ref)
        if provider_ref == LAB_REF:
            raise DispatchProviderExecutionError("boom")
        assert operation == "discover"
        return _ok_result(
            provider_ref,
            operation,
            candidates=[{"endpoint": "https://other.example.test"}],
        )

    candidates = discover_dispatch_candidates(
        config=config,
        entry_points_fn=_entry_points_fn(
            _FakeEntryPoint("lab", object()),
            _FakeEntryPoint("other", object()),
        ),
        operation_runner=run_provider,
    )

    assert [candidate.endpoint for candidate in candidates] == [
        "https://other.example.test"
    ]


def test_connection_plan_for_third_party_uses_isolated_runner() -> None:
    machine = MachineRecord(
        alias="lab",
        provider_ref=LAB_REF,
        endpoint="https://lab.example.test",
        credential_ref="fleet:lab",
        pinned_installation_id="sase_inst_v1_" + "a" * 64,
    )
    lab_ep = _FakeEntryPoint("lab", object())

    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del timeout_seconds
        assert str(provider.provider_ref) == LAB_REF
        assert operation == "connection_plan"
        assert request["machine"]["alias"] == "lab"
        return _ok_result(
            LAB_REF,
            operation,
            plan={
                "schema_version": 1,
                "provider_ref": LAB_REF,
                "endpoint": "https://lab.example.test/tunnel",
                "credential_ref": "fleet:lab",
                "pinned_installation_id": "sase_inst_v1_" + "a" * 64,
                "connection_kind": "gateway",
                "tls": request["machine"]["tls"],
            },
        )

    plan = connection_plan_for_machine(
        machine,
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(lab_ep),
        operation_runner=run_provider,
    )

    assert plan["endpoint"] == "https://lab.example.test/tunnel"
    assert lab_ep.load_calls == 0


def test_run_dispatch_provider_operation_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    def capture_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del operation, request, timeout_seconds
        captured.append(provider)
        return _ok_result(str(provider.provider_ref), "discover")

    discover_dispatch_candidates(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", object())),
        operation_runner=capture_provider,
    )
    provider = captured[0]

    def run_timeout(*args: object, **kwargs: object) -> BoundedCompletedProcess:
        del args
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["SASE_DISPATCH_PROVIDER_SUBPROCESS"] == "1"
        return BoundedCompletedProcess(
            returncode=-15,
            stdout=b"",
            stderr=b"",
            duration_seconds=0.01,
            timed_out=True,
        )

    monkeypatch.setattr(
        "sase.dispatch.provider_runtime.run_bounded_subprocess", run_timeout
    )

    with pytest.raises(DispatchProviderExecutionError, match="timed out"):
        run_dispatch_provider_operation(
            provider,
            "discover",
            {"config": {}, "provider_ref": LAB_REF},
            0.01,
        )


def test_discover_reports_provider_hook_exception() -> None:
    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del provider, operation, request, timeout_seconds
        raise DispatchProviderExecutionError("boom")

    result = discover_dispatch_result(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", object())),
        operation_runner=run_provider,
    )

    assert result.candidates == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "dispatch_provider_discovery_failed"
    ]


def test_discover_reports_provider_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_timeout(*args: object, **kwargs: object) -> BoundedCompletedProcess:
        del args, kwargs
        return BoundedCompletedProcess(
            returncode=-15,
            stdout=b"",
            stderr=b"",
            duration_seconds=0.01,
            timed_out=True,
        )

    monkeypatch.setattr(
        "sase.dispatch.provider_runtime.run_bounded_subprocess", run_timeout
    )
    started = time.monotonic()

    result = discover_dispatch_result(
        config=_lab_config(enabled=True),
        timeout_seconds=0.01,
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", object())),
    )

    elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert result.candidates == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "dispatch_provider_discovery_failed"
    ]
    assert "timed out" in result.diagnostics[0].message
