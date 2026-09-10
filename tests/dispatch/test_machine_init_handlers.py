"""CLI handler tests for machine init, add, and repair."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from io import StringIO
import json
from pathlib import Path

import pytest

from sase.config import core as config_core
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import CredentialRecord
from sase.main.init_machine_handler import run_init_machine
from tests.dispatch.machine_init_helpers import (
    _FakeGateway,
    _bundle,
    _candidate,
    _pin,
    _service,
)
from tests.main.parser_help_helpers import TtyStringIO

pytest_plugins = ["tests.dispatch.machine_init_fixtures"]


def test_handler_reuses_enrollment_json_and_hidden_bundle(
    isolated_dispatch: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    service, _fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))
    answers: Iterator[str] = iter(["1", "fleet"])
    args = argparse.Namespace(
        check=False,
        json=True,
        timeout=None,
        bootstrap_file=None,
        provider=None,
        _init_input_func=lambda _prompt: next(answers),
        _init_stdin=TtyStringIO(),
        _init_getpass_func=lambda _prompt: _bundle(pin),
        _init_machine_service=service.machine_service,
        _init_apply_chezmoi_fn=None,
        _init_use_chezmoi_fn=lambda: False,
        _init_registry_target_fn=None,
    )
    code = run_init_machine(args)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == 1
    assert payload["command"] == "machine"
    assert payload["subcommand"] == "init"
    assert payload["ok"] is True
    assert payload["results"][0]["alias"] == "fleet"
    assert payload["results"][0]["quarantined"] is False
    assert "credential_ref" in payload["results"][0]
    assert "installation_id" in payload["results"][0]


def test_handler_quarantine_is_honest(
    isolated_dispatch: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    service, fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))
    fake.hello_payload["outcome"] = "quarantined"
    fake.hello_payload["quarantine"] = {"reason": "expired bootstrap"}
    answers: Iterator[str] = iter(["1", "fleet"])
    args = argparse.Namespace(
        check=False,
        json=False,
        timeout=None,
        bootstrap_file=None,
        provider=None,
        _init_input_func=lambda _prompt: next(answers),
        _init_stdin=TtyStringIO(),
        _init_getpass_func=lambda _prompt: _bundle(pin),
        _init_machine_service=service.machine_service,
        _init_apply_chezmoi_fn=None,
        _init_use_chezmoi_fn=lambda: False,
        _init_registry_target_fn=None,
    )
    code = run_init_machine(args)
    captured = capsys.readouterr()
    assert code == 1
    assert "Enrolled fleet" not in captured.out
    assert "quarantined" in captured.out
    assert "expired bootstrap" in captured.out


def test_read_enrollment_bundle_file_stdin_and_getpass(tmp_path: Path) -> None:
    from sase.main.machine_handler import read_enrollment_bundle

    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("from-file", encoding="utf-8")
    file_text = read_enrollment_bundle(
        argparse.Namespace(bootstrap_file=str(bundle_path))
    )
    assert file_text == "from-file"

    stdin = StringIO("from-stdin")
    stdin_text = read_enrollment_bundle(
        argparse.Namespace(bootstrap_file=None),
        stdin=stdin,
        getpass_func=lambda _prompt: "from-getpass",
    )
    assert stdin_text == "from-stdin"

    tty = TtyStringIO()
    hidden = read_enrollment_bundle(
        argparse.Namespace(bootstrap_file=None),
        stdin=tty,
        getpass_func=lambda prompt: f"hidden:{prompt}",
    )
    assert hidden.startswith("hidden:")
    assert "bundle" in hidden.lower()


def test_handle_add_activates_authenticated_hello(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.machine_handler import _handle_add

    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: False)
    pin = _pin()
    service, fake = _service(isolated_dispatch, pin=pin)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(_bundle(pin), encoding="utf-8")
    args = argparse.Namespace(
        alias="fleet",
        endpoint="https://fleet.example.test",
        provider="builtin@https",
        candidate=None,
        json=True,
        timeout=None,
        bootstrap_file=str(bundle_path),
    )
    code = _handle_add(args, service.machine_service)
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert fake.enroll_calls == 1
    assert payload["activated"] is True
    assert payload["result"]["alias"] == "fleet"
    assert payload["errors"] == []


def test_handle_repair_retires_old_credential_only_after_activation(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.machine_handler import _handle_repair

    monkeypatch.setattr(config_core, "get_use_chezmoi", lambda: False)
    old_pin = _pin("a")
    new_pin = _pin("b")
    config_dir, credential_path = isolated_dispatch
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    apollo:",
                "      provider: builtin@https",
                "      endpoint: https://fleet.example.test",
                "      credential_ref: fleet:apollo",
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
            ref="fleet:apollo",
            token="old-token",
            token_type="bearer",
            provider_ref="builtin@https",
            endpoint="https://fleet.example.test",
            installation_id=old_pin,
        )
    )
    fake = _FakeGateway(new_pin)
    service = MachineService(
        credential_store=store,
        gateway_client=fake,  # type: ignore[arg-type]
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(_bundle(new_pin), encoding="utf-8")
    args = argparse.Namespace(
        alias="apollo",
        json=False,
        timeout=None,
        bootstrap_file=str(bundle_path),
    )
    code = _handle_repair(args, service)
    assert code == 0
    assert store.get("fleet:apollo") is None
    assert any(
        str(row.get("ref", "")).startswith("fleet:apollo:") for row in store.metadata()
    )
