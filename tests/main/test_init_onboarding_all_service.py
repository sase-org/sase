"""Service-scoped batch tests for ``sase init --all``.

Covers the service offer: it is planned and applied once across projects
on ``--yes``, a decline prompts once and records the marker, check mode
plans once, and machine/service scopes stay independent of each other.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import init_onboarding
from sase.main.init_onboarding import run_init_onboarding_all
from sase.main.init_plan import InitAction, InitPlan
from sase.main.init_project_scope import InitProjectInventory
from sase.main.init_registry import InitCommandSpec
from tests.main.init_onboarding_helpers import (
    _TtyStringIO,
    _args,
    _batch_target,
    _reject_prompt,
)


def test_batch_service_yes_is_planned_and_applied_once(
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
    planned: list[str] = []
    calls: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: calls.append(Path.cwd().name) or 0,
        scope="machine",
    )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert planned == ["alpha"]
    assert calls == ["alpha"]


def test_batch_service_decline_prompts_once_and_records_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.init_service_handler import decline_init_service
    from sase.service.platform import DECLINED_MARKER
    from sase.service.state import read_service_state

    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    targets = tuple(
        _batch_target(tmp_path, name) for name in ("alpha", "beta", "gamma")
    )
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    planned: list[str] = []
    declined: list[str] = []
    prompts: list[str] = []
    calls: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    def decline(args: argparse.Namespace) -> None:
        declined.append(Path.cwd().name)
        decline_init_service(args)

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: calls.append(Path.cwd().name) or 0,
        scope="machine",
        decline=decline,
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
    assert planned == ["alpha"]
    assert declined == ["alpha"]
    assert len(prompts) == 1
    assert "sase service init" in prompts[0]
    assert "sase init service" not in prompts[0]
    assert "1 needs attention" in capsys.readouterr().out
    snapshot = read_service_state(sase_home=tmp_path / ".sase")
    assert DECLINED_MARKER in snapshot.state.markers


def test_batch_service_check_plans_once_across_projects(
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
    planned: list[str] = []

    def plan(args: argparse.Namespace) -> InitPlan:
        del args
        planned.append(Path.cwd().name)
        return InitPlan(
            command="service",
            label="Service",
            summary="install service host",
            actions=(InitAction(Path("sase.service"), "create"),),
        )

    spec = InitCommandSpec(
        name="service",
        label="Service",
        plan=plan,
        run=lambda args: 0,
        scope="machine",
    )

    exit_code = run_init_onboarding_all(
        _args(check=True, all_projects=True),
        specs=(spec,),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 1
    assert planned == ["alpha"]


def test_batch_machine_and_service_scopes_are_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    monkeypatch.chdir(original)
    targets = tuple(_batch_target(tmp_path, name) for name in ("alpha", "beta"))
    monkeypatch.setattr(
        init_onboarding,
        "resolve_init_project_inventory",
        lambda: InitProjectInventory(targets),
    )
    calls: list[str] = []

    def _spec(name: str) -> InitCommandSpec:
        return InitCommandSpec(
            name=name,
            label=name.title(),
            plan=lambda args: InitPlan(
                command=name,
                label=name.title(),
                summary=f"offer {name}",
                actions=(InitAction(Path(name), "create"),),
            ),
            run=lambda args, n=name: calls.append(f"{n}:{Path.cwd().name}") or 0,
            scope="machine",
        )

    exit_code = run_init_onboarding_all(
        _args(yes=True, all_projects=True),
        specs=(_spec("machine"), _spec("service")),
        stdin=_TtyStringIO(),
        input_func=_reject_prompt,
    )

    assert exit_code == 0
    assert calls == ["machine:alpha", "service:alpha"]
