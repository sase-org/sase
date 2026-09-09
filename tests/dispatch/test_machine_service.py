from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_service import MachineService, _parse_enrollment_bundle
from sase.dispatch.models import CredentialRecord
from tests.conftest import redirect_sase_home


def _pin(hex_char: str = "a") -> str:
    return "sase_inst_v1_" + hex_char * 64


def _bundle(pin: str) -> str:
    return json.dumps(
        {
            "bootstrap_id": "boot-1",
            "bootstrap_secret": "one-time-secret",
            "pinned_installation_id": pin,
            "supported_protocol_versions": [1],
        }
    )


class _FakeGateway:
    def __init__(self, pin: str) -> None:
        self.pin = pin
        self.enroll_calls = 0
        self.hello_payload: dict[str, Any] = {
            "schema_version": 1,
            "installation": {"schema_version": 1, "installation_id": pin},
            "credential": {
                "schema_version": 1,
                "credential_id": "cred-1",
                "scopes": ["fleet.hello"],
                "issued_at_unix": 1.0,
                "expires_at_unix": None,
            },
            "capabilities": {
                "schema_version": 1,
                "host": ["fleet.hello"],
                "protocol": ["fleet.v1"],
                "resource": [],
            },
            "machine_selector": "athena",
            "outcome": "enrolled",
            "protocol_version": 1,
            "quarantine": None,
            "token": "stored-token",
            "token_type": "bearer",
        }

    def enroll(self, **kwargs: object) -> dict[str, Any]:
        self.enroll_calls += 1
        assert kwargs["endpoint"] == "https://fleet.example.test"
        return self.hello_payload

    def hello(self, **kwargs: object) -> dict[str, Any]:
        assert kwargs["endpoint"] == "https://fleet.example.test"
        return self.hello_payload


@pytest.fixture
def isolated_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    from sase.config import core as config_core

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    config_core.clear_config_cache()
    return config_dir, tmp_path / "credentials.json"


def test_add_machine_stores_only_credential_ref_in_config(
    isolated_dispatch: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir, credential_path = isolated_dispatch
    pin = _pin()
    fake_gateway = _FakeGateway(pin)
    monkeypatch.setattr(
        "sase.dispatch.machine_service.validate_connection_plan",
        lambda record, **kwargs: (),
    )

    result = MachineService(
        credential_store=LocalCredentialStore(credential_path),
        gateway_client=fake_gateway,  # type: ignore[arg-type]
    ).add_machine(
        alias="alpha",
        endpoint="https://fleet.example.test",
        provider_ref="builtin@https",
        bundle_text=_bundle(pin),
    )

    assert result.quarantined is False
    config_text = (config_dir / "sase.yml").read_text(encoding="utf-8")
    assert "one-time-secret" not in config_text
    assert "stored-token" not in config_text
    assert "credential_ref: fleet:alpha" in config_text

    credential = LocalCredentialStore(credential_path).get("fleet:alpha")
    assert credential is not None
    assert credential.token == "stored-token"
    machines = load_dispatch_config().machine_by_alias()
    assert machines["alpha"].pinned_installation_id == pin


def test_list_machines_is_offline(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    config_dir, credential_path = isolated_dispatch
    pin = _pin()
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    alpha:",
                "      provider: builtin@https",
                "      endpoint: https://fleet.example.test",
                "      credential_ref: fleet:alpha",
                f"      installation_pin: {pin}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    service = MachineService(
        credential_store=LocalCredentialStore(credential_path),
        gateway_client=object(),  # type: ignore[arg-type]
    )

    assert [machine.alias for machine in service.list_machines()] == ["alpha"]


def test_issue_bootstrap_builds_parseable_bundle_with_injected_binding(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    _config_dir, credential_path = isolated_dispatch
    pin = _pin()
    calls: list[tuple[str, dict[str, object]]] = []

    def issue(home: str, request: Mapping[str, object]) -> Mapping[str, object]:
        calls.append((home, dict(request)))
        return {
            "schema_version": 1,
            "bootstrap_id": "boot_1",
            "bootstrap_secret": "one-time-secret",
            "expires_at_unix": 1_060.0,
            "allowed_scopes": ["fleet.hello"],
            "pinned_installation_id": pin,
            "protocol_versions": [1],
        }

    result = MachineService(
        credential_store=LocalCredentialStore(credential_path),
        bootstrap_issuer=issue,
        time_fn=lambda: 1_000.0,
    ).issue_bootstrap(
        expires_seconds=60,
        scopes=("fleet.summary.read",),
    )

    assert calls == [
        (
            str(credential_path.parent / ".sase"),
            {
                "schema_version": 1,
                "requested_scopes": ["fleet.summary.read"],
                "supported_protocol_versions": [1],
                "expires_at_unix": 1_060.0,
                "installation_pin": None,
            },
        )
    ]
    parsed = _parse_enrollment_bundle(json.dumps(result.bundle))
    assert parsed.bootstrap_id == "boot_1"
    assert parsed.bootstrap_secret == "one-time-secret"
    assert parsed.pinned_installation_id == pin
    assert parsed.requested_scopes == ("fleet.hello",)
    assert result.bundle["requested_scopes"] == ["fleet.hello"]
    assert "allowed_scopes" not in result.bundle


def test_issue_bootstrap_omits_expiry_for_store_default(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    _config_dir, credential_path = isolated_dispatch
    pin = _pin()
    observed_request: dict[str, object] = {}

    def issue(_home: str, request: Mapping[str, object]) -> Mapping[str, object]:
        observed_request.update(request)
        return {
            "schema_version": 1,
            "bootstrap_id": "boot_1",
            "bootstrap_secret": "one-time-secret",
            "expires_at_unix": 1_600.0,
            "allowed_scopes": [],
            "pinned_installation_id": pin,
            "protocol_versions": [1],
        }

    MachineService(
        credential_store=LocalCredentialStore(credential_path),
        bootstrap_issuer=issue,
    ).issue_bootstrap()

    assert observed_request["expires_at_unix"] is None
    assert observed_request["requested_scopes"] == []


def test_status_quarantines_installation_mismatch(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    config_dir, credential_path = isolated_dispatch
    good_pin = _pin("a")
    bad_pin = _pin("b")
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    alpha:",
                "      provider: builtin@https",
                "      endpoint: https://fleet.example.test",
                "      credential_ref: fleet:alpha",
                f"      installation_pin: {good_pin}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    store = LocalCredentialStore(credential_path)
    store.put(
        CredentialRecord(
            ref="fleet:alpha",
            token="stored-token",
            token_type="bearer",
            provider_ref="builtin@https",
            endpoint="https://fleet.example.test",
            installation_id=good_pin,
        )
    )
    fake_gateway = _FakeGateway(bad_pin)

    statuses = MachineService(
        credential_store=store,
        gateway_client=fake_gateway,  # type: ignore[arg-type]
    ).status()

    assert statuses[0].state == "quarantined"
    reloaded = load_dispatch_config().machine_by_alias()["alpha"]
    assert reloaded.quarantined is True
    assert reloaded.quarantine_reason == "hello installation identity mismatch"


def test_add_machine_rejects_disabled_provider(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    from sase.dispatch.models import MachineRegistryError

    config_dir, credential_path = isolated_dispatch
    pin = _pin()
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  providers:",
                "    builtin@tailnet:",
                "      enabled: false",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(MachineRegistryError, match="provider is not enabled"):
        MachineService(
            credential_store=LocalCredentialStore(credential_path),
            gateway_client=_FakeGateway(pin),  # type: ignore[arg-type]
        ).add_machine(
            alias="alpha",
            endpoint="https://fleet.example.test",
            provider_ref="builtin@tailnet",
            bundle_text=_bundle(pin),
        )


def test_repair_machine_keeps_previous_credential(
    isolated_dispatch: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.config import core as config_core

    config_dir, credential_path = isolated_dispatch
    old_pin = _pin("a")
    new_pin = _pin("b")
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    alpha:",
                "      provider: builtin@https",
                "      endpoint: https://fleet.example.test",
                "      credential_ref: fleet:alpha",
                f"      installation_pin: {old_pin}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config_core.clear_config_cache()
    store = LocalCredentialStore(credential_path)
    store.put(
        CredentialRecord(
            ref="fleet:alpha",
            token="old-token",
            token_type="bearer",
            provider_ref="builtin@https",
            endpoint="https://fleet.example.test",
            installation_id=old_pin,
        )
    )
    monkeypatch.setattr(
        "sase.dispatch.machine_service.validate_connection_plan",
        lambda record, **kwargs: (),
    )
    fake = _FakeGateway(new_pin)
    result = MachineService(
        credential_store=store,
        gateway_client=fake,  # type: ignore[arg-type]
    ).repair_machine(
        alias="alpha",
        bundle_text=_bundle(new_pin),
    )

    assert result.quarantined is False
    assert store.get("fleet:alpha") is not None
    assert store.get("fleet:alpha").token == "old-token"
    assert result.credential_ref != "fleet:alpha"
    assert store.get(result.credential_ref) is not None
