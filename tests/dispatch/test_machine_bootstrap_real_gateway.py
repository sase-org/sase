"""Real bootstrap-to-gateway round trip through the actual Rust binding and a real
``sase_gateway`` process, over a genuinely trusted (self-signed, loopback-only) HTTPS
connection.

Unlike ``test_machine_service.py``'s ``_FakeGateway``-backed tests, nothing here
stubs the gateway's decision: ``fleet_issue_bootstrap`` is the real exported Rust
binding, the bundle text is the real ``sase machine bootstrap --json`` wire shape
parsed by the real ``_parse_enrollment_bundle``, and enrollment/hello go out over a
real HTTP connection to a real ``sase_gateway`` subprocess enforcing real one-time-use,
expiry, and installation-pin checks.
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from sase.config import core as config_core
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.fleet_client import FleetGatewayError
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import MachineRegistryError
from tests.conftest import redirect_sase_home
from tests.dispatch.real_gateway_fixture import RealGateway, real_gateway


@pytest.fixture
def gateway(tmp_path: Path) -> Generator[RealGateway]:
    with real_gateway(tmp_path / "gw") as running:
        yield running


def _client_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    gateway: RealGateway,
) -> tuple[MachineService, Path]:
    """An isolated machine-registry identity: its own SASE_HOME, config dir, and
    credential store, matching ``test_machine_service.py``'s ``isolated_dispatch``
    pattern so ``load_dispatch_config``/``write_machine_record`` never touch the
    real host's ``~/.config/sase``.
    """

    redirect_sase_home(monkeypatch, tmp_path / name / ".sase")
    config_dir = tmp_path / name / "config"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    config_core.clear_config_cache()
    service = MachineService(
        credential_store=LocalCredentialStore(tmp_path / name / "credentials.json"),
        gateway_client=gateway.trusted_gateway_client(),
    )
    return service, config_dir


def test_bootstrap_issue_enroll_hello_round_trip_through_real_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gateway: RealGateway,
) -> None:
    redirect_sase_home(monkeypatch, gateway.home)
    issued = MachineService().issue_bootstrap()
    bundle_text = json.dumps(issued.bundle, sort_keys=True)
    bootstrap_secret = str(issued.bundle["bootstrap_secret"])
    assert bootstrap_secret not in repr(issued)

    client, config_dir = _client_service(monkeypatch, tmp_path, "client", gateway)
    result = client.add_machine(
        alias="apollo",
        endpoint=gateway.https_endpoint,
        provider_ref="builtin@https",
        bundle_text=bundle_text,
    )

    assert result.quarantined is False
    assert result.installation_id == issued.pinned_installation_id

    credential = client.credential_store.get(result.credential_ref)
    assert credential is not None
    assert credential.token

    config_text = (config_dir / "sase.yml").read_text(encoding="utf-8")
    assert credential.token not in config_text
    assert bootstrap_secret not in config_text

    (status,) = client.status(("apollo",))
    assert status.state == "ok"
    assert status.installation_id == issued.pinned_installation_id


def test_bootstrap_replay_is_rejected_by_real_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gateway: RealGateway,
) -> None:
    redirect_sase_home(monkeypatch, gateway.home)
    issued = MachineService().issue_bootstrap()
    bundle_text = json.dumps(issued.bundle, sort_keys=True)

    first_client, _first_config = _client_service(
        monkeypatch, tmp_path, "first", gateway
    )
    first = first_client.add_machine(
        alias="apollo",
        endpoint=gateway.https_endpoint,
        provider_ref="builtin@https",
        bundle_text=bundle_text,
    )
    assert first.quarantined is False

    second_client, _second_config = _client_service(
        monkeypatch, tmp_path, "second", gateway
    )
    with pytest.raises(FleetGatewayError) as excinfo:
        second_client.add_machine(
            alias="apollo",
            endpoint=gateway.https_endpoint,
            provider_ref="builtin@https",
            bundle_text=bundle_text,
        )
    assert excinfo.value.code == "bootstrap_consumed"
    assert excinfo.value.status == 409
    assert second_client.list_machines() == ()


def test_bootstrap_wrong_pin_is_rejected_by_real_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gateway: RealGateway,
) -> None:
    redirect_sase_home(monkeypatch, gateway.home)
    issued = MachineService().issue_bootstrap()
    tampered = dict(issued.bundle)
    wrong_pin = "sase_inst_v1_" + ("f" * 64)
    assert wrong_pin != issued.pinned_installation_id
    tampered["pinned_installation_id"] = wrong_pin
    bundle_text = json.dumps(tampered, sort_keys=True)

    client, _config_dir = _client_service(monkeypatch, tmp_path, "client", gateway)
    with pytest.raises(MachineRegistryError, match="installation identity"):
        client.add_machine(
            alias="apollo",
            endpoint=gateway.https_endpoint,
            provider_ref="builtin@https",
            bundle_text=bundle_text,
        )


def test_bootstrap_expiry_is_rejected_by_real_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    gateway: RealGateway,
) -> None:
    redirect_sase_home(monkeypatch, gateway.home)
    issued = MachineService().issue_bootstrap(expires_seconds=1.0)
    bundle_text = json.dumps(issued.bundle, sort_keys=True)
    time.sleep(1.5)  # sase-test-wait: real wall-clock TTL expiry, no event to await

    client, _config_dir = _client_service(monkeypatch, tmp_path, "client", gateway)
    with pytest.raises(FleetGatewayError) as excinfo:
        client.add_machine(
            alias="apollo",
            endpoint=gateway.https_endpoint,
            provider_ref="builtin@https",
            bundle_text=bundle_text,
        )
    assert excinfo.value.code == "bootstrap_expired"
    assert excinfo.value.status == 400
