"""Provider hook, discovery, and credential-layer tests for remote dispatch.

Recreates the dispatch-plugins verification suite that was lost when the
sase-xe.7 workspace was reaped before its commit landed (see the epic notes
on bead sase-xe).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import (
    CredentialStoreError,
    LocalCredentialStore,
)
from sase.dispatch.models import CredentialRecord
from sase.dispatch.providers import (
    collect_dispatch_providers,
    discover_dispatch_candidates,
    hookimpl,
)
from tests.conftest import redirect_sase_home


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
                "ref": "fake@lab",
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
        if provider_ref != "fake@lab":
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


class _DuplicateAndInvalidSpecProvider:
    @hookimpl
    def dispatch_provider_specs(self) -> tuple[dict[str, object], ...]:
        return (
            {"ref": "builtin@https", "display_name": "impostor"},
            {"display_name": "spec without a ref"},
        )


def _lab_config(*, enabled: bool) -> Any:
    return load_dispatch_config(
        {
            "dispatch": {
                "providers": {"fake@lab": enabled},
                "discovery": {"enabled_providers": ["fake@lab"]},
            }
        }
    )


def test_collect_includes_builtin_providers_without_entry_points() -> None:
    inventory = collect_dispatch_providers(entry_points_fn=_entry_points_fn())

    refs = [spec.ref for spec in inventory.specs]
    assert refs == ["builtin@https", "builtin@tailnet"]
    assert all(spec.builtin for spec in inventory.specs)
    assert all(spec.package == "sase" for spec in inventory.specs)
    assert inventory.diagnostics == ()


def test_collect_includes_third_party_provider_specs() -> None:
    inventory = collect_dispatch_providers(
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", _FakeProvider()))
    )

    by_ref = inventory.by_ref()
    assert set(by_ref) == {"builtin@https", "builtin@tailnet", "fake@lab"}
    lab = by_ref["fake@lab"]
    assert lab.display_name == "Lab Fleet Gateway"
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


def test_collect_records_load_failure_and_keeps_builtins() -> None:
    inventory = collect_dispatch_providers(
        entry_points_fn=_entry_points_fn(
            _FakeEntryPoint("broken", object(), error=RuntimeError("boom"))
        )
    )

    assert [spec.ref for spec in inventory.specs] == [
        "builtin@https",
        "builtin@tailnet",
    ]
    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_load_failed" in codes


def test_collect_reports_duplicate_and_invalid_specs() -> None:
    inventory = collect_dispatch_providers(
        entry_points_fn=_entry_points_fn(
            _FakeEntryPoint("impostor", _DuplicateAndInvalidSpecProvider())
        )
    )

    codes = [diagnostic.code for diagnostic in inventory.diagnostics]
    assert "dispatch_provider_duplicate" in codes
    assert "dispatch_provider_spec_invalid" in codes
    # First registration wins: the builtin spec is kept, the impostor dropped.
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
    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=True),
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", _FakeProvider())),
    )

    assert [candidate.endpoint for candidate in candidates] == [
        "https://lab.example.test"
    ]
    assert candidates[0].provider_ref == "fake@lab"
    assert candidates[0].machine_selector == "lab"


def test_discover_skips_disabled_provider() -> None:
    candidates = discover_dispatch_candidates(
        config=_lab_config(enabled=False),
        entry_points_fn=_entry_points_fn(_FakeEntryPoint("lab", _FakeProvider())),
    )

    assert candidates == ()


def test_discover_without_selected_providers_does_no_work() -> None:
    lab_ep = _FakeEntryPoint("lab", _FakeProvider())

    candidates = discover_dispatch_candidates(
        config=load_dispatch_config({"dispatch": {}}),
        entry_points_fn=_entry_points_fn(lab_ep),
    )

    assert candidates == ()
    assert lab_ep.load_calls == 0


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
