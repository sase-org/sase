"""Provider hook, discovery, and credential-layer tests for remote dispatch.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

from collections.abc import Mapping
import importlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import (
    CredentialStoreError,
    LocalCredentialStore,
)
from sase.dispatch.models import CredentialRecord, MachineRecord
from sase.dispatch.providers import (
    _DispatchProviderExecutionError,
    _run_dispatch_provider_operation,
    connection_plan_for_machine,
    collect_dispatch_providers,
    discover_dispatch_candidates,
    discover_dispatch_result,
    hookimpl,
)
from sase.dispatch.worker_entry import main as dispatch_worker_main
from sase.finalizers.bounded_subprocess import BoundedCompletedProcess
from tests.conftest import redirect_sase_home

LAB_REF = "fake-dispatch-plugin@lab"
OTHER_REF = "fake-dispatch-plugin@other"
MIXED_REF = "mixed-case-dispatch@lab"


class _FakeDist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name}
        self.version = version


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


def test_collect_includes_builtin_providers_without_entry_points() -> None:
    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn())

    refs = [spec.ref for spec in inventory.specs]
    assert refs == ["builtin@https", "builtin@tailnet"]
    assert all(spec.builtin for spec in inventory.specs)
    assert all(spec.package == "sase" for spec in inventory.specs)
    assert inventory.diagnostics == ()


def test_collect_includes_third_party_provider_specs() -> None:
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(lab_ep))

    by_ref = inventory.by_ref()
    assert set(by_ref) == {"builtin@https", "builtin@tailnet", LAB_REF}
    assert lab_ep.load_calls == 0
    lab = by_ref[LAB_REF]
    assert lab.display_name == "lab"
    assert lab.supports_discovery is True
    assert lab.package == "fake-dispatch-plugin"
    assert lab.version == "1.0.0"
    assert lab.builtin is False


def test_collect_skips_the_builtin_entry_point() -> None:
    # The sase package registers its builtin providers both in code and as a
    # pyproject entry point for inventory visibility; collection must not load
    # or register the entry point a second time.
    builtin_ep = _FakeEntryPoint(
        "builtin",
        object(),
        package="sase",
        error=AssertionError("builtin entry point must not be loaded"),
    )

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(builtin_ep))

    assert builtin_ep.load_calls == 0
    assert [spec.ref for spec in inventory.specs] == [
        "builtin@https",
        "builtin@tailnet",
    ]
    assert not any(
        diagnostic.code == "dispatch_provider_duplicate"
        for diagnostic in inventory.diagnostics
    )


def test_collect_does_not_load_failing_third_party_entry_point() -> None:
    broken = _FakeEntryPoint("broken", object(), error=RuntimeError("boom"))

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(broken))

    assert broken.load_calls == 0
    assert "fake-dispatch-plugin@broken" in inventory.by_ref()
    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_load_failed" not in codes


def test_collect_reports_duplicate_and_invalid_metadata_refs() -> None:
    inventory = collect_dispatch_providers(
        entry_points_fn=_entry_points_fn(
            _FakeEntryPoint(
                "lab",
                object(),
                package="Fake.Dispatch_Plugin",
            ),
            _FakeEntryPoint("lab", object()),
            _FakeEntryPoint("BadName", object()),
        )
    )

    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_duplicate" in codes
    assert "dispatch_provider_ref_invalid" in codes
    # First registration wins: the builtin spec is kept.
    assert inventory.by_ref()["builtin@https"].builtin is True


@pytest.mark.parametrize(
    "env_key",
    ["SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_DISPATCH"],
)
def test_disable_env_skips_third_party_providers(
    env_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(env_key, "1")
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn(lab_ep))

    assert lab_ep.load_calls == 0
    assert [spec.ref for spec in inventory.specs] == [
        "builtin@https",
        "builtin@tailnet",
    ]
    disabled = [
        diagnostic
        for diagnostic in inventory.diagnostics
        if diagnostic.code == "dispatch_plugins_disabled"
    ]
    assert len(disabled) == 1
    assert env_key in disabled[0].message

    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(lab_ep),
    )
    assert candidates == ()
    assert lab_ep.load_calls == 0


def test_importing_sase_never_imports_dispatch_providers() -> None:
    # Provider modules load only during explicit discovery, never as an
    # import side effect of the sase package or the dispatch package.
    code = "\n".join(
        [
            "import sys",
            "import sase",
            "assert 'sase.dispatch' not in sys.modules, 'sase.dispatch imported'",
            "import sase.dispatch",
            "assert 'sase.dispatch.providers' not in sys.modules, (",
            "    'sase.dispatch.providers imported'",
            ")",
        ]
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)


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
            raise _DispatchProviderExecutionError("boom")
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

    with pytest.raises(_DispatchProviderExecutionError, match="timed out"):
        _run_dispatch_provider_operation(
            provider,
            "discover",
            {"config": {}, "provider_ref": LAB_REF},
            0.01,
        )


def _install_dispatch_site(monkeypatch: pytest.MonkeyPatch, site: Path) -> None:
    site.mkdir(parents=True)
    (site / "mixed_case_dispatch.py").write_text(
        """
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.dispatch.providers import hookimpl

CALLS = []


class Provider:
    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {
                "ref": "mixed-case-dispatch@lab",
                "display_name": "Mixed Lab",
                "supports_discovery": True,
            },
        )

    @hookimpl
    def dispatch_discover(
        self,
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> tuple[dict[str, object], ...]:
        CALLS.append(("discover", provider_ref, timeout_seconds))
        return (
            {
                "endpoint": config["endpoint"],
                "machine_selector": provider_ref,
            },
        )

    @hookimpl
    def dispatch_connection_plan(
        self,
        provider_ref: str,
        machine: Mapping[str, Any],
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> dict[str, object]:
        CALLS.append(("connection_plan", provider_ref, timeout_seconds))
        return {
            "schema_version": 1,
            "provider_ref": provider_ref,
            "endpoint": str(machine["endpoint"]) + "/" + str(config["suffix"]),
            "credential_ref": machine["credential_ref"],
            "pinned_installation_id": machine["pinned_installation_id"],
            "connection_kind": "gateway",
            "tls": machine["tls"],
        }
""".lstrip(),
        encoding="utf-8",
    )
    dist = site / "Mixed.Case_Dispatch-1.0.0.dist-info"
    dist.mkdir()
    dist.joinpath("METADATA").write_text(
        "Metadata-Version: 2.1\nName: Mixed.Case_Dispatch\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    dist.joinpath("entry_points.txt").write_text(
        "[sase_dispatch]\nlab = mixed_case_dispatch:Provider\n",
        encoding="utf-8",
    )
    sys.modules.pop("mixed_case_dispatch", None)
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()


def _run_dispatch_worker(
    monkeypatch: pytest.MonkeyPatch,
    provider_ref: str,
    request: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(dict(request))))
    monkeypatch.setattr(sys, "stdout", stdout)
    returncode = dispatch_worker_main(
        ["--provider-ref", provider_ref, "--operation", str(request["operation"])]
    )
    return returncode, json.loads(stdout.getvalue())


def test_dispatch_worker_loads_selected_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_dispatch_site(monkeypatch, tmp_path / "site")

    returncode, payload = _run_dispatch_worker(
        monkeypatch,
        "Mixed.Case_Dispatch@lab",
        {
            "operation": "discover",
            "config": {"endpoint": "https://lab.example.test"},
            "timeout_seconds": 2,
        },
    )

    assert returncode == 0
    assert payload["provider_ref"] == MIXED_REF
    assert payload["candidates"] == [
        {
            "endpoint": "https://lab.example.test",
            "machine_selector": MIXED_REF,
        }
    ]


def test_dispatch_worker_runs_connection_plan_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_dispatch_site(monkeypatch, tmp_path / "site")

    returncode, payload = _run_dispatch_worker(
        monkeypatch,
        MIXED_REF,
        {
            "operation": "connection_plan",
            "config": {"suffix": "provider"},
            "machine": {
                "endpoint": "https://lab.example.test",
                "credential_ref": "fleet:lab",
                "pinned_installation_id": "sase_inst_v1_" + "a" * 64,
                "tls": {"schema_version": 1, "mode": "system_roots"},
            },
            "timeout_seconds": 2,
        },
    )

    assert returncode == 0
    assert payload["plan"]["endpoint"] == "https://lab.example.test/provider"


def test_discover_reports_provider_hook_exception() -> None:
    def run_provider(
        provider: Any,
        operation: str,
        request: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        del provider, operation, request, timeout_seconds
        raise _DispatchProviderExecutionError("boom")

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


def _credential(
    ref: str = "fleet:alpha",
    *,
    token: str = "secret-token",
) -> CredentialRecord:
    return CredentialRecord(
        ref=ref,
        token=token,
        token_type="bearer",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        installation_id="sase_inst_v1_" + "a" * 64,
    )


def test_credential_store_round_trip_uses_restrictive_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = LocalCredentialStore()

    store.put(_credential())

    assert store.path.stat().st_mode & 0o777 == 0o600
    loaded = store.get("fleet:alpha")
    assert loaded is not None
    assert loaded.token == "secret-token"
    assert store.has("fleet:alpha")
    assert store.delete("fleet:alpha") is True
    assert store.delete("fleet:alpha") is False


def test_credential_metadata_never_exposes_tokens(tmp_path: Path) -> None:
    store = LocalCredentialStore(tmp_path / "credentials.json")
    store.put(_credential())

    rows = store.metadata()

    assert len(rows) == 1
    assert "token" not in rows[0]
    assert "secret-token" not in json.dumps(rows)


def test_credential_store_rejects_invalid_records(tmp_path: Path) -> None:
    store = LocalCredentialStore(tmp_path / "credentials.json")

    with pytest.raises(CredentialStoreError):
        store.put(_credential(ref="not a reference id"))
    with pytest.raises(CredentialStoreError):
        store.put(_credential(token=""))


def test_credential_store_rejects_corrupt_payloads(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(CredentialStoreError):
        LocalCredentialStore(path).get("fleet:alpha")

    path.write_text(
        json.dumps({"schema_version": 999, "records": {}}),
        encoding="utf-8",
    )
    with pytest.raises(CredentialStoreError):
        LocalCredentialStore(path).get("fleet:alpha")
