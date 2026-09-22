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
    snapshot: Any = None

    def __post_init__(self) -> None:
        if self.snapshot is None:
            object.__setattr__(
                self,
                "snapshot",
                SimpleNamespace(
                    state=SimpleNamespace(
                        requests={
                            "scheduler": SimpleNamespace(generation=7, completed=False)
                        }
                    )
                ),
            )


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


def test_start_service_proc_requests_start_and_nudges_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "request_service_proc",
        lambda name, action, actor, reason=None: (
            calls.append(("request", (name, action, actor, reason))) or _Mutation()
        ),
    )
    monkeypatch.setattr(
        actions, "nudge_service_host", lambda: calls.append(("nudge", None)) or True
    )

    outcome = actions.start_service_proc("scheduler", actor="cli")

    assert outcome.changed is True
    assert outcome.nudged is True
    assert outcome.generation == 7
    assert outcome.message == "requested service proc scheduler start"
    assert calls == [
        (("request", ("scheduler", "start", "cli", None))),
        ("nudge", None),
    ]


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


def test_restart_service_proc_requests_restart_with_one_nudge_and_no_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    _patch_config(monkeypatch, _entry())
    monkeypatch.setattr(
        actions,
        "request_service_proc",
        lambda name, action, actor, reason=None: (
            calls.append(("request", (name, action, actor, reason))) or _Mutation()
        ),
    )
    monkeypatch.setattr(
        actions, "nudge_service_host", lambda: calls.append(("nudge", None)) or True
    )
    monkeypatch.setattr(
        actions.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("restart must not sleep")),
    )

    outcome = actions.restart_service_proc(
        "scheduler",
        actor="cli",
        reason="restart",
    )

    assert outcome.message == "requested service proc scheduler restart"
    assert outcome.generation == 7
    assert calls == [
        ("request", ("scheduler", "restart", "cli", "restart")),
        ("nudge", None),
    ]


def test_wait_for_service_proc_request_returns_completed_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = SimpleNamespace(generation=3, completed=False)
    done = SimpleNamespace(generation=3, completed=True)
    reads = [
        SimpleNamespace(state=SimpleNamespace(requests={"scheduler": pending})),
        SimpleNamespace(state=SimpleNamespace(requests={"scheduler": done})),
    ]
    monkeypatch.setattr(actions, "read_service_state", lambda: reads.pop(0))

    assert (
        actions.wait_for_service_proc_request("scheduler", 3, timeout=5.0, poll=0)
        is done
    )


def test_wait_for_service_proc_request_times_out_without_a_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = SimpleNamespace(generation=3, completed=False)
    monkeypatch.setattr(
        actions,
        "read_service_state",
        lambda: SimpleNamespace(state=SimpleNamespace(requests={"scheduler": pending})),
    )

    assert (
        actions.wait_for_service_proc_request("scheduler", 3, timeout=0, poll=0) is None
    )


def test_wait_for_service_proc_request_survives_transient_read_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = SimpleNamespace(generation=3, completed=True)
    calls = {"count": 0}

    def _read() -> Any:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("transient state read failure")
        return SimpleNamespace(state=SimpleNamespace(requests={"scheduler": done}))

    monkeypatch.setattr(actions, "read_service_state", _read)

    assert (
        actions.wait_for_service_proc_request("scheduler", 3, timeout=5.0, poll=0)
        is done
    )
    assert calls["count"] == 2


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
        action("scheduler", actor="cli")
