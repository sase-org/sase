"""Machine-scoped batch tests for ``sase init --all``.

Covers the machine offer: it is prompted once across projects, runs once
on ``--yes``, stays quiet when a completed review is recorded, and a
machine failure consumes the offer without stopping later projects. Also
covers the single-project config-then-machine refresh ordering.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.dispatch._machine_init_review import MachineInitReviewStore
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import DiscoveryResult, MachineDiagnostic
from sase.main import init_onboarding
from sase.main.init_machine_handler import plan_init_machine
from sase.main.init_onboarding import run_init_onboarding, run_init_onboarding_all
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory
from sase.main.init_registry import InitCommandSpec
from tests.dispatch.machine_init_helpers import _candidate, _config, _pin
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _batch_target,
    _reject_prompt,
)


def test_batch_machine_offer_decline_prompts_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(
        _batch_target(tmp_path, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    prompts: list[str] = []
    calls: list[str] = []
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 0,
    )

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "no"

    exit_code = run_init_onboarding_all(
        _args(all_projects=True),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=answer,
    )

    assert exit_code == 1
    assert calls == []
    assert len(prompts) == 1
    assert "sase machine init" in prompts[0]
    assert "sase init machine" not in prompts[0]
    assert "1 needs attention" in capsys.readouterr().out


def test_batch_machine_yes_runs_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(
        _batch_target(tmp_path, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    calls: list[str] = []
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 0,
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["alpha"]


def test_batch_completed_machine_review_stays_quiet_across_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(
        _batch_target(tmp_path, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    monkeypatch.setattr(
        "sase.dispatch.machine_init.load_dispatch_config",
        lambda: _config(),
    )
    review_store = MachineInitReviewStore(tmp_path / "review.json")
    assert (
        review_store.record_completed_review(
            (_candidate(endpoint="https://fleet.example.test", pin=_pin("a")),)
        )
        is None
    )
    diagnostic = MachineDiagnostic(
        code="tailnet_probe_timeout",
        severity="warning",
        message="tailnet health probe timed out",
    )
    calls = {"discover": 0}

    def discover_result(**_kwargs: object) -> DiscoveryResult:
        calls["discover"] += 1
        return DiscoveryResult(diagnostics=(diagnostic,))

    args = _args(all_projects=True)
    args._init_machine_service = MachineService(discover_result_fn=discover_result)
    args._init_review_store = review_store
    run_calls: list[str] = []

    exit_code = run_init_onboarding_all(
        args,
        specs=(
            InitCommandSpec(
                name="machine",
                label="Machine",
                plan=plan_init_machine,
                run=lambda args: run_calls.append(Path.cwd().name) or 0,
            ),
        ),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert calls["discover"] == 0
    assert run_calls == []
    assert out.count("Project:") == 3
    assert "tailnet health probe timed out" not in out


def test_batch_machine_failure_consumes_offer_but_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(
        _batch_target(tmp_path, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    calls: list[str] = []
    spec = InitCommandSpec(
        name="machine",
        label="Machine",
        plan=lambda args: InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(InitAction(Path("remote machine enrollment"), "validate"),),
        ),
        run=lambda args: calls.append(Path.cwd().name) or 5,
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert calls == ["alpha"]
    out = capsys.readouterr().out
    assert "init machine failed with exit code 5" in out


def test_config_apply_refreshes_empty_machine_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "project"
    original.mkdir()
    monkeypatch.chdir(original)
    discovery_enabled = False
    calls: list[str] = []

    def config_run(args: argparse.Namespace) -> int:
        del args
        nonlocal discovery_enabled
        discovery_enabled = True
        calls.append("config")
        return 0

    def machine_plan(args: argparse.Namespace) -> InitPlan:
        del args
        return InitPlan(
            command="machine",
            label="Machine",
            summary="review machines",
            actions=(
                (InitAction(Path("remote machine enrollment"), "validate"),)
                if discovery_enabled
                else ()
            ),
        )

    specs = (
        InitCommandSpec(
            name="config",
            label="Config",
            plan=lambda args: InitPlan(
                command="config",
                label="Config",
                summary="configure identity",
                actions=(InitAction(Path(".sase/machine_name"), "update"),),
            ),
            run=config_run,
        ),
        InitCommandSpec(
            name="machine",
            label="Machine",
            plan=machine_plan,
            run=lambda args: calls.append("machine") or 0,
        ),
    )

    exit_code = run_init_onboarding(
        _args(yes=True),
        specs=specs,
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["config", "machine"]
