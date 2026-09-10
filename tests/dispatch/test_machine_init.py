"""Offline plan and reconcile tests for machine init."""

from __future__ import annotations

import argparse
from io import StringIO

import pytest

from sase.dispatch.machine_init import MachineInitService
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import DiscoveryCandidate, DispatchConfig
from sase.main.init_machine_handler import plan_init_machine
from tests.dispatch.machine_init_helpers import (
    _candidate,
    _config,
    _pin,
    _record,
)
from tests.main.parser_help_helpers import TtyStringIO


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
