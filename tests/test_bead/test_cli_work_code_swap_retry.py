"""``sase bead work`` waits out a code swap and reruns instead of failing."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import pytest

from sase.bead import cli_work_entry


class _FakeLock:
    def __init__(self, *, acquired: bool, blocked_by: str | None = None) -> None:
        self.acquired = acquired
        self.blocked_by = blocked_by
        self.active = False

    def __enter__(self) -> _FakeLock:
        self.active = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.active = False


def _timer_factory(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("dispatch is stubbed")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lock: _FakeLock,
    swapped_since_boot: bool,
) -> tuple[list[str], list[dict[str, Any]]]:
    dispatched: list[str] = []
    reexecs: list[dict[str, Any]] = []
    monkeypatch.setattr(sys, "argv", ["sase", "bead", "work", "sase-1"])
    monkeypatch.setattr(
        "sase.dev_update.code_swap_lock.code_swap_reader_lock",
        lambda **_kwargs: lock,
    )
    monkeypatch.setattr(
        "sase.core.code_swap_epoch.code_swap_since_boot",
        lambda: swapped_since_boot,
    )

    def fake_reexec(argv: list[str], *, reason: str) -> None:
        reexecs.append({"argv": argv, "reason": reason, "locked": lock.active})

    monkeypatch.setattr(
        "sase.agent.launch_swap_retry.reexec_after_code_swap", fake_reexec
    )
    monkeypatch.setattr(
        cli_work_entry,
        "_handle_bead_work_locked",
        lambda _args, **kwargs: dispatched.append(kwargs["target"]),
    )
    return dispatched, reexecs


def _run() -> None:
    cli_work_entry.handle_bead_work(
        argparse.Namespace(target=["sase-1"], json=True),
        timer_factory=_timer_factory,
    )


def test_refused_by_a_live_writer_retries_after_releasing_the_lock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = _FakeLock(acquired=False, blocked_by="sase dev update (pid 7)")
    dispatched, reexecs = _install(monkeypatch, lock=lock, swapped_since_boot=False)

    with pytest.raises(SystemExit) as exc_info:
        _run()

    assert dispatched == []
    assert reexecs == [
        {
            "argv": [sys.executable, "-m", "sase", "bead", "work", "sase-1"],
            "reason": "a code swap is in progress",
            "locked": False,
        }
    ]
    # Without an armed retry (or once it is spent) it fails exactly as before.
    assert exc_info.value.code == 1
    assert "sase dev update (pid 7)" in json.loads(capsys.readouterr().out)["error"]


def test_swap_since_boot_starts_no_work_and_reruns_fresh(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = _FakeLock(acquired=True)
    dispatched, reexecs = _install(monkeypatch, lock=lock, swapped_since_boot=True)

    with pytest.raises(SystemExit) as exc_info:
        _run()

    assert dispatched == []
    assert [entry["reason"] for entry in reexecs] == [
        "a code swap completed after this command started"
    ]
    assert reexecs[0]["locked"] is False
    assert exc_info.value.code == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert "No work was started" in error


def test_no_swap_runs_the_work_under_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = _FakeLock(acquired=True)
    dispatched, reexecs = _install(monkeypatch, lock=lock, swapped_since_boot=False)

    _run()

    assert dispatched == ["sase-1"]
    assert reexecs == []
