"""Chezmoi activation tests for machine init."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tests.dispatch.machine_init_helpers import _bundle, _candidate, _pin, _service
from tests.main.parser_help_helpers import TtyStringIO

pytest_plugins = ["tests.dispatch.machine_init_fixtures"]


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
