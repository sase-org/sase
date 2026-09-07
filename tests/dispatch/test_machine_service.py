from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import CredentialRecord
from sase.feature_flags import override_flags
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
        lambda record: (),
    )

    with override_flags(remote_dispatch=True):
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

    with override_flags(remote_dispatch=True):
        statuses = MachineService(
            credential_store=store,
            gateway_client=fake_gateway,  # type: ignore[arg-type]
        ).status()

    assert statuses[0].state == "quarantined"
    reloaded = load_dispatch_config().machine_by_alias()["alpha"]
    assert reloaded.quarantined is True
    assert reloaded.quarantine_reason == "hello installation identity mismatch"
