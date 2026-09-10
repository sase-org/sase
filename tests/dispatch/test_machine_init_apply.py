"""Enrollment apply tests for machine init."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from sase.config import core as config_core
from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_init import MachineInitService
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import DiscoveryResult, MachineDiagnostic
from tests.dispatch.machine_init_helpers import (
    _FakeGateway,
    _bundle,
    _candidate,
    _config,
    _pin,
    _service,
)
from tests.main.parser_help_helpers import TtyStringIO

pytest_plugins = ["tests.dispatch.machine_init_fixtures"]


def test_apply_enrolls_new_candidate_beside_existing(
    isolated_dispatch: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pin_existing = _pin("a")
    pin_new = _pin("b")
    config_dir, _credential_path = isolated_dispatch
    (config_dir / "sase.yml").write_text(
        "\n".join(
            [
                "dispatch:",
                "  machines:",
                "    apollo:",
                "      provider: builtin@https",
                "      endpoint: https://apollo.example.test",
                "      credential_ref: fleet:apollo",
                f"      installation_pin: {pin_existing}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config_core.clear_config_cache()
    candidates = (
        _candidate(
            endpoint="https://apollo.example.test",
            pin=pin_existing,
            display_name="apollo",
            selector="apollo",
        ),
        _candidate(pin=pin_new),
    )
    service, fake = _service(isolated_dispatch, pin=pin_new, candidates=candidates)
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin_new),
        stdin=TtyStringIO(),
    )
    captured = capsys.readouterr()
    assert result.exit_code == 0
    assert fake.enroll_calls == 1
    assert [item.alias for item in result.enrollments] == ["fleet"]
    assert [item.status for item in result.skipped] == ["enrolled"]
    listing = captured.err
    assert "already enrolled as apollo" in listing
    assert "fleet" in listing
    machines = load_dispatch_config().machine_by_alias()
    assert "apollo" in machines
    assert machines["fleet"].pinned_installation_id == pin_new


def test_apply_quarantine_exits_nonzero(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    service, fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))
    fake.hello_payload["outcome"] = "quarantined"
    fake.hello_payload["quarantine"] = {"reason": "bootstrap replayed"}
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert result.enrollments[0].quarantined is True
    assert result.enrollments[0].quarantine_reason == "bootstrap replayed"


def test_hidden_prompt_is_getpass_not_input(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin, selector="")
    service, _fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))
    input_prompts: list[str] = []
    answers = iter(["1", "fleet"])

    def input_func(prompt: str) -> str:
        input_prompts.append(prompt)
        return next(answers)

    result = service.apply(
        input_func=input_func,
        getpass_func=lambda prompt: _bundle(pin) if "bundle" in prompt.lower() else "",
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 0
    assert all("bundle" not in prompt.lower() for prompt in input_prompts)
    assert all("secret" not in prompt.lower() for prompt in input_prompts)


def test_file_and_stdin_bundle_inputs(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    service, fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(_bundle(pin), encoding="utf-8")
    answers = iter(["1", "fleet"])
    file_result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: (_ for _ in ()).throw(AssertionError("getpass")),
        stdin=TtyStringIO(),
        bundle_text=bundle_path.read_text(encoding="utf-8"),
    )
    assert file_result.exit_code == 0
    assert fake.enroll_calls == 1

    pin2 = _pin("b")
    fake.pin = pin2
    fake.hello_payload["installation"]["installation_id"] = pin2
    stdin = StringIO(_bundle(pin2))
    answers2 = iter(["1", "other"])
    service2, _fake2 = _service(
        isolated_dispatch,
        pin=pin2,
        candidates=(_candidate(pin=pin2, selector="other"),),
    )
    stdin_result = service2.apply(
        input_func=lambda _prompt: next(answers2),
        getpass_func=lambda _prompt: (_ for _ in ()).throw(AssertionError("getpass")),
        stdin=stdin,
        bundle_text=stdin.read(),
    )
    assert stdin_result.exit_code == 0


def test_hello_failure_prints_repair_recovery(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    service, fake = _service(isolated_dispatch, pin=pin, candidates=(candidate,))

    def hello(**kwargs: object) -> dict[str, Any]:
        from sase.dispatch.fleet_client import FleetGatewayError

        raise FleetGatewayError("unavailable", code="timeout")

    fake.hello = hello  # type: ignore[method-assign]
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert result.recovery_messages
    assert "sase machine repair fleet" in result.recovery_messages[0]
    assert "consumed" in result.recovery_messages[0]


def test_apply_preserves_discovery_diagnostics_and_fails_empty_tooling(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    diagnostic = MachineDiagnostic(
        code="tailnet_status_unavailable",
        severity="error",
        message="tailscale CLI is not installed or not on PATH",
    )
    machine = MachineService(
        credential_store=LocalCredentialStore(isolated_dispatch[1]),
        gateway_client=_FakeGateway(_pin()),  # type: ignore[arg-type]
        discover_result_fn=lambda **_kwargs: DiscoveryResult(diagnostics=(diagnostic,)),
    )
    service = MachineInitService(
        machine_service=machine,
        load_config_fn=lambda: _config(),
        use_chezmoi_fn=lambda: False,
    )
    result = service.apply(
        input_func=lambda _prompt: "1",
        getpass_func=lambda _prompt: _bundle(_pin()),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert result.nothing_to_enroll is False
    assert result.diagnostics == (diagnostic,)
    assert "tailscale CLI is not installed" in result.errors[0]


def test_apply_keeps_working_candidates_beside_discovery_diagnostics(
    isolated_dispatch: tuple[Path, Path],
) -> None:
    pin = _pin()
    diagnostic = MachineDiagnostic(
        code="dispatch_provider_not_installed",
        severity="error",
        message="dispatch provider plugin@example is selected but is not installed",
    )
    candidate = _candidate(pin=pin)
    machine = MachineService(
        credential_store=LocalCredentialStore(isolated_dispatch[1]),
        gateway_client=_FakeGateway(pin),  # type: ignore[arg-type]
        discover_result_fn=lambda **_kwargs: DiscoveryResult(
            candidates=(candidate,),
            diagnostics=(diagnostic,),
        ),
    )
    service = MachineInitService(
        machine_service=machine,
        use_chezmoi_fn=lambda: False,
    )
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 0
    assert [item.alias for item in result.enrollments] == ["fleet"]
    assert result.diagnostics == (diagnostic,)
