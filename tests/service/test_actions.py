"""Tests for shared service-proc action adapter."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from sase.service import actions


@dataclass(frozen=True)
class _Mutation:
    changed: bool = True


class _Config:
    def __init__(self, entries: dict[str, Any]) -> None:
        self._entries = entries

    def get(self, name: str) -> Any | None:
        return self._entries.get(name)


def _entry(
    name: str = "scheduler",
    *,
    available: bool = True,
    reasons: tuple[str, ...] = (),
) -> Any:
    return SimpleNamespace(
        name=name,
        available=available,
        unavailable_reasons=reasons,
    )


def _patch_config(monkeypatch: pytest.MonkeyPatch, entry: Any | None) -> None:
    entries = {} if entry is None else {entry.name: entry}
    monkeypatch.setattr(actions, "load_service_config", lambda: _Config(entries))


def test_start_service_proc_clears_stop_and_nudges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "clear_service_stop",
        lambda name: calls.append(("clear", name)) or _Mutation(),
    )
    monkeypatch.setattr(
        actions, "nudge_service_host", lambda: calls.append(("nudge", None)) or True
    )

    outcome = actions.start_service_proc("scheduler", actor="cli")

    assert outcome.changed is True
    assert outcome.nudged is True
    assert outcome.message == "requested service proc scheduler start"
    assert calls == [("clear", "scheduler"), ("nudge", None)]


def test_stop_service_proc_records_stop_and_nudges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "record_service_stop",
        lambda name, actor, reason=None: (
            calls.append(("record", (name, actor, reason))) or _Mutation()
        ),
    )
    monkeypatch.setattr(
        actions, "nudge_service_host", lambda: calls.append(("nudge", None)) or True
    )

    outcome = actions.stop_service_proc("scheduler", actor="cli", reason="cli")

    assert outcome.message == "requested service proc scheduler stop until next boot"
    assert calls == [("record", ("scheduler", "cli", "cli")), ("nudge", None)]


def test_restart_service_proc_records_then_clears_with_two_nudges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "record_service_stop",
        lambda name, actor, reason=None: (
            calls.append(("record", (name, actor, reason))) or _Mutation()
        ),
    )
    monkeypatch.setattr(
        actions,
        "clear_service_stop",
        lambda name: calls.append(("clear", name)) or _Mutation(),
    )
    monkeypatch.setattr(
        actions, "nudge_service_host", lambda: calls.append(("nudge", None)) or True
    )
    monkeypatch.setattr(
        actions.time, "sleep", lambda seconds: calls.append(("sleep", seconds))
    )

    outcome = actions.restart_service_proc(
        "scheduler",
        actor="cli",
        reason="restart",
        delay=0.25,
    )

    assert outcome.message == "requested service proc scheduler restart"
    assert calls == [
        ("record", ("scheduler", "cli", "restart")),
        ("nudge", None),
        ("sleep", 0.25),
        ("clear", "scheduler"),
        ("nudge", None),
    ]


def test_enable_and_disable_service_proc_set_machine_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "set_service_enablement",
        lambda name, enabled, actor: (
            calls.append((name, enabled, actor)) or _Mutation()
        ),
    )
    monkeypatch.setattr(actions, "nudge_service_host", lambda: True)

    enabled = actions.enable_service_proc("scheduler", actor="cli")
    disabled = actions.disable_service_proc("scheduler", actor="tui")

    assert enabled.message == "enabled service proc scheduler for this machine"
    assert disabled.message == "disabled service proc scheduler for this machine"
    assert calls == [("scheduler", True, "cli"), ("scheduler", False, "tui")]


def test_unknown_service_proc_raises_action_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch, None)

    with pytest.raises(actions.ServiceProcActionError, match="unknown service proc"):
        actions.start_service_proc("missing", actor="cli")


@pytest.mark.parametrize("action_name", ["start_service_proc", "restart_service_proc"])
def test_unavailable_proc_rejects_starting_actions(
    monkeypatch: pytest.MonkeyPatch,
    action_name: str,
) -> None:
    _patch_config(monkeypatch, _entry(available=False, reasons=("missing binary",)))
    monkeypatch.setattr(actions, "nudge_service_host", lambda: True)

    action = getattr(actions, action_name)
    with pytest.raises(actions.ServiceProcActionError, match="missing binary"):
        action("scheduler", actor="cli", delay=0.0) if action_name.startswith(
            "restart"
        ) else action("scheduler", actor="cli")
