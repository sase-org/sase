from __future__ import annotations

import argparse
from collections.abc import Iterator
from io import StringIO
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from sase.config import core as config_core
from sase.dispatch.config import load_dispatch_config
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_init import MachineInitService
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    CredentialRecord,
    DispatchConfig,
    DiscoveryCandidate,
    DiscoveryResult,
    MachineDiagnostic,
    MachineRecord,
    ProviderSettings,
)
from sase.main.init_machine_handler import plan_init_machine, run_init_machine
from tests.conftest import redirect_sase_home
from tests.main.parser_help_helpers import TtyStringIO


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


def _candidate(
    *,
    endpoint: str = "https://fleet.example.test",
    pin: str = "",
    display_name: str = "fleet",
    selector: str = "fleet",
    provider_ref: str = "builtin@https",
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        provider_ref=provider_ref,
        endpoint=endpoint,
        display_name=display_name,
        machine_selector=selector,
        installation_pin=pin,
    )


def _record(
    *,
    alias: str = "apollo",
    endpoint: str = "https://apollo.example.test",
    pin: str = "",
    provider_ref: str = "builtin@https",
) -> MachineRecord:
    return MachineRecord(
        alias=alias,
        provider_ref=provider_ref,
        endpoint=endpoint,
        credential_ref=f"fleet:{alias}",
        pinned_installation_id=pin or _pin("a"),
    )


def _config(
    *,
    machines: tuple[MachineRecord, ...] = (),
    discovery: tuple[str, ...] = ("builtin@tailnet",),
) -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True),
            "builtin@tailnet": ProviderSettings(ref="builtin@tailnet", enabled=True),
        },
        machines=machines,
        discovery_enabled_provider_refs=discovery,
    )


class _FakeGateway:
    def __init__(
        self, pin: str, *, endpoint: str = "https://fleet.example.test"
    ) -> None:
        self.pin = pin
        self.endpoint = endpoint
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
            "machine_selector": "fleet",
            "outcome": "enrolled",
            "protocol_version": 1,
            "quarantine": None,
            "token": "stored-token",
            "token_type": "bearer",
        }

    def enroll(self, **kwargs: object) -> dict[str, Any]:
        self.enroll_calls += 1
        assert kwargs["endpoint"] == self.endpoint
        return self.hello_payload

    def hello(self, **kwargs: object) -> dict[str, Any]:
        assert kwargs["endpoint"] == self.endpoint
        return self.hello_payload


@pytest.fixture
def isolated_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(config_core, "CONFIG_DIR", config_dir)
    config_core.clear_config_cache()
    monkeypatch.setattr(
        "sase.dispatch.machine_service.validate_connection_plan",
        lambda record, **kwargs: (),
    )
    return config_dir, tmp_path / "credentials.json"


def _service(
    isolated_dispatch: tuple[Path, Path],
    *,
    pin: str,
    candidates: tuple[DiscoveryCandidate, ...] = (),
    apply_fn: Any | None = None,
    use_chezmoi: bool = False,
    registry_target: Path | None = None,
) -> tuple[MachineInitService, _FakeGateway]:
    _config_dir, credential_path = isolated_dispatch
    fake = _FakeGateway(pin)
    machine = MachineService(
        credential_store=LocalCredentialStore(credential_path),
        gateway_client=fake,  # type: ignore[arg-type]
        discover_fn=lambda **_kwargs: candidates,
        discover_result_fn=lambda **_kwargs: DiscoveryResult(candidates=candidates),
    )
    service = MachineInitService(
        machine_service=machine,
        apply_chezmoi_fn=apply_fn,
        use_chezmoi_fn=lambda: use_chezmoi,
        registry_target_fn=(lambda: registry_target)
        if registry_target is not None
        else None,
    )
    return service, fake


def test_plan_is_offline_and_not_perpetual_drift() -> None:
    calls = {"discover": 0}

    def load() -> DispatchConfig:
        return _config()

    class _Boom(MachineService):
        def discover(self, **kwargs: object) -> tuple[DiscoveryCandidate, ...]:
            calls["discover"] += 1
            raise AssertionError("planner must not discover")

    service = MachineInitService(machine_service=_Boom(), load_config_fn=load)
    check = service.plan(check_mode=True, is_tty=True)
    quiet = service.plan(check_mode=False, is_tty=False)
    offer = service.plan(check_mode=False, is_tty=True)

    assert calls["discover"] == 0
    assert check.offer_enrollment is False
    assert check.summary == "remote machine enrollment is optional"
    assert quiet.offer_enrollment is False
    assert offer.offer_enrollment is True


def test_plan_all_enrolled_is_not_check_drift() -> None:
    enrolled = (_record(pin=_pin("a")),)
    service = MachineInitService(
        machine_service=MachineService(discover_fn=lambda **_k: ()),
        load_config_fn=lambda: _config(machines=enrolled),
    )
    plan = service.plan(check_mode=True, is_tty=True)
    assert plan.offer_enrollment is False
    assert "apollo" in plan.summary


def test_plan_init_machine_adapter_uses_tty_gated_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.dispatch.machine_init.load_dispatch_config",
        lambda: _config(),
    )
    check_args = argparse.Namespace(check=True, _init_stdin=TtyStringIO())
    offer_args = argparse.Namespace(check=False, _init_stdin=TtyStringIO())
    quiet_args = argparse.Namespace(check=False, _init_stdin=StringIO())

    check = plan_init_machine(check_args)
    offer = plan_init_machine(offer_args)
    quiet = plan_init_machine(quiet_args)

    assert check.has_changes is False
    assert offer.has_changes is True
    assert offer.requires_tty is True
    assert quiet.has_changes is False


def test_reconcile_skips_enrolled_and_routes_pin_change_to_repair() -> None:
    pin_a = _pin("a")
    pin_b = _pin("b")
    enrolled = (
        _record(alias="apollo", endpoint="https://apollo.example.test", pin=pin_a),
    )
    candidates = (
        _candidate(
            endpoint="https://apollo.example.test",
            pin=pin_a,
            display_name="apollo",
            selector="apollo",
        ),
        _candidate(
            endpoint="https://apollo.example.test",
            pin=pin_b,
            display_name="apollo-new",
            selector="apollo",
        ),
        _candidate(pin=pin_b, display_name="fleet", selector="fleet"),
    )
    service = MachineInitService(
        machine_service=MachineService(discover_fn=lambda **_k: candidates),
        load_config_fn=lambda: _config(machines=enrolled),
    )
    rows = service.reconcile(candidates, enrolled)
    assert [row.status for row in rows] == ["enrolled", "repair", "new"]
    assert rows[0].alias == "apollo"
    assert rows[1].alias == "apollo"
    assert "sase machine repair apollo" in rows[1].reason
    assert rows[2].status == "new"


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


def test_chezmoi_source_vs_applied_activation(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    config_dir, _credential_path = isolated_dispatch
    applied = config_dir / "sase.yml"
    source = tmp_path / "chezmoi" / "dot_config" / "sase" / "sase.yml"
    source.parent.mkdir(parents=True)
    probes: dict[str, bool] = {}

    def resolve(file: str, *, use_chezmoi: bool) -> Path:
        target = Path(file)
        return source if use_chezmoi else target

    monkeypatch.setattr("sase.dispatch.config.resolve_write_path", resolve)
    monkeypatch.setattr("sase.dispatch.machine_init.resolve_write_path", resolve)
    monkeypatch.setattr(
        "sase.dispatch.config.config_core.get_use_chezmoi", lambda: True
    )
    monkeypatch.setattr("sase.dispatch.config._registry_target_path", lambda: applied)

    def apply_fn(target: Path | str) -> subprocess.CompletedProcess[str]:
        probes["source_has_probe"] = source.exists() and "fleet" in source.read_text(
            encoding="utf-8"
        )
        probes["applied_has_probe_before"] = (
            applied.exists() and "fleet" in applied.read_text(encoding="utf-8")
        )
        applied.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return subprocess.CompletedProcess(
            ["chezmoi", "apply", "--force", str(target)], 0, "", ""
        )

    candidate = _candidate(pin=pin)
    service, _fake = _service(
        isolated_dispatch,
        pin=pin,
        candidates=(candidate,),
        apply_fn=apply_fn,
        use_chezmoi=True,
        registry_target=applied,
    )
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 0
    assert probes["source_has_probe"] is True
    assert probes["applied_has_probe_before"] is False
    assert "fleet" in applied.read_text(encoding="utf-8")


def test_apply_failure_prints_recovery(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    candidate = _candidate(pin=pin)
    applied = isolated_dispatch[0] / "sase.yml"
    source = tmp_path / "chezmoi-source.yml"

    def resolve(file: str, *, use_chezmoi: bool) -> Path:
        return source if use_chezmoi else Path(file)

    monkeypatch.setattr("sase.dispatch.machine_init.resolve_write_path", resolve)

    def apply_fn(_target: Path | str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["chezmoi", "apply", "--force"], 1, "", "chezmoi boom"
        )

    service, _fake = _service(
        isolated_dispatch,
        pin=pin,
        candidates=(candidate,),
        apply_fn=apply_fn,
        use_chezmoi=True,
        registry_target=applied,
    )
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert result.recovery_messages
    assert "sase machine repair fleet" in result.recovery_messages[0]
    assert "Retry the apply" in result.recovery_messages[0]


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


def test_chezmoi_submit_failure_does_not_untracked_apply(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    applied = isolated_dispatch[0] / "sase.yml"
    source = tmp_path / "chezmoi-source.yml"

    def resolve(file: str, *, use_chezmoi: bool) -> Path:
        return source if use_chezmoi else Path(file)

    monkeypatch.setattr("sase.dispatch.machine_init.resolve_write_path", resolve)

    def boom_submit(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("supervisor down")

    monkeypatch.setattr("sase.procs.submit_proc", boom_submit)
    untracked = {"called": False}

    def untracked_apply(_target: Path | str) -> subprocess.CompletedProcess[str]:
        untracked["called"] = True
        return subprocess.CompletedProcess(["chezmoi", "apply"], 0, "", "")

    monkeypatch.setattr("sase.config.targets.apply_chezmoi", untracked_apply)
    service, _fake = _service(
        isolated_dispatch,
        pin=pin,
        candidates=(_candidate(pin=pin),),
        use_chezmoi=True,
        registry_target=applied,
    )
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert untracked["called"] is False
    assert "could not submit chezmoi apply" in result.errors[0]
    assert "sase machine repair fleet" in result.recovery_messages[0]


def test_chezmoi_wait_failure_retains_proc_and_does_not_reapply(
    isolated_dispatch: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _pin()
    applied = isolated_dispatch[0] / "sase.yml"
    source = tmp_path / "chezmoi-source.yml"

    def resolve(file: str, *, use_chezmoi: bool) -> Path:
        return source if use_chezmoi else Path(file)

    monkeypatch.setattr("sase.dispatch.machine_init.resolve_write_path", resolve)

    class _Proc:
        proc_id = "proc-chezmoi-1"

    submits = {"count": 0}

    def submit(*_args: object, **_kwargs: object) -> _Proc:
        submits["count"] += 1
        return _Proc()

    def boom_wait(proc_id: str, **_kwargs: object) -> object:
        raise TimeoutError(f"timed out waiting for proc {proc_id}")

    monkeypatch.setattr("sase.procs.submit_proc", submit)
    monkeypatch.setattr("sase.procs.wait_for_proc", boom_wait)
    untracked = {"called": False}

    def untracked_apply(_target: Path | str) -> subprocess.CompletedProcess[str]:
        untracked["called"] = True
        return subprocess.CompletedProcess(["chezmoi", "apply"], 0, "", "")

    monkeypatch.setattr("sase.config.targets.apply_chezmoi", untracked_apply)
    service, _fake = _service(
        isolated_dispatch,
        pin=pin,
        candidates=(_candidate(pin=pin),),
        use_chezmoi=True,
        registry_target=applied,
    )
    answers = iter(["1", "fleet"])
    result = service.apply(
        input_func=lambda _prompt: next(answers),
        getpass_func=lambda _prompt: _bundle(pin),
        stdin=TtyStringIO(),
    )
    assert result.exit_code == 1
    assert submits["count"] == 1
    assert untracked["called"] is False
    assert result.chezmoi_in_progress is True
    assert result.chezmoi_proc_id == "proc-chezmoi-1"
    assert "proc-chezmoi-1" in result.errors[0]


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
