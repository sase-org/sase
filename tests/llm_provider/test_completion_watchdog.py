"""Tests for the post-declaration provider teardown watchdog."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from sase.finalizers.declaration_manifest import FINAL_SUBMISSION_FILENAME
from sase.llm_provider import _subprocess_plain as plain
from sase.llm_provider._subprocess import start_completion_watchdog
from sase.llm_provider._subprocess_reap import TeardownStall, teardown_stall_for

_POLL = 0.005
_LEAKED_ARGV = "python3 /tmp/muse_usage_listen_a.py"


class _FakeProcess:
    """Popen stand-in that stays alive until terminated or *exit_after_polls*."""

    pid = 4242

    def __init__(self, *, exit_after_polls: int | None = None) -> None:
        self.returncode: int | None = None
        self.polls = 0
        self.terminations = 0
        self._exit_after_polls = exit_after_polls

    def poll(self) -> int | None:
        self.polls += 1
        if self._exit_after_polls is not None and self.polls >= self._exit_after_polls:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminations += 1
        self.returncode = -15


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv(plain.TEARDOWN_GRACE_ENV, raising=False)
    return tmp_path


@pytest.fixture
def terminated_trees(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace the real reaper with one that only records and terminates."""
    terminated: list[int] = []

    def fake_terminate(process: Any, stall: TeardownStall, *, timeout: float) -> None:
        terminated.append(process.pid)
        process.terminate()
        stall.descendants = [{"pid": 701, "ppid": process.pid, "argv": _LEAKED_ARGV}]

    monkeypatch.setattr(plain, "terminate_process_tree", fake_terminate)
    return terminated


def _accept_declaration(artifacts_dir: Path) -> None:
    (artifacts_dir / FINAL_SUBMISSION_FILENAME).write_text(
        json.dumps({"accepted_at": "2026-09-20T15:41:51Z"}), encoding="utf-8"
    )


def _start(process: _FakeProcess, *, grace: float, **kwargs: Any) -> threading.Thread:
    thread = start_completion_watchdog(
        cast(Any, process),
        runtime="muse",
        grace_seconds=grace,
        poll_seconds=_POLL,
        **kwargs,
    )
    assert thread is not None
    return thread


def test_watchdog_never_fires_without_a_declaration(
    artifacts_dir: Path, terminated_trees: list[int]
) -> None:
    # 60 polls at >= 5ms each outlasts the 20ms grace many times over.
    process = _FakeProcess(exit_after_polls=60)

    _start(process, grace=0.02).join(timeout=10)

    assert process.terminations == 0
    assert terminated_trees == []
    assert not (artifacts_dir / plain.TEARDOWN_STALL_FILENAME).exists()


def test_watchdog_stays_quiet_when_the_provider_exits_inside_the_grace(
    artifacts_dir: Path, terminated_trees: list[int]
) -> None:
    process = _FakeProcess(exit_after_polls=5)
    thread = _start(process, grace=60)
    _accept_declaration(artifacts_dir)

    thread.join(timeout=10)

    assert process.terminations == 0
    assert terminated_trees == []
    assert not (artifacts_dir / plain.TEARDOWN_STALL_FILENAME).exists()


def test_watchdog_reaps_a_provider_that_outlives_the_grace(
    artifacts_dir: Path,
    terminated_trees: list[int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    process = _FakeProcess()
    stalls: list[TeardownStall] = []
    thread = _start(process, grace=0.02, on_stall=stalls.append)
    _accept_declaration(artifacts_dir)

    thread.join(timeout=10)

    assert not thread.is_alive()
    assert terminated_trees == [4242]
    assert process.terminations == 1

    artifact = json.loads(
        (artifacts_dir / plain.TEARDOWN_STALL_FILENAME).read_text(encoding="utf-8")
    )
    assert artifact["runtime"] == "muse"
    assert artifact["provider_pid"] == 4242
    assert artifact["grace_seconds"] == 0.02
    assert artifact["waited_seconds"] >= 0.02
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT.*\+00:00", artifact["declared_at"])
    assert artifact["reaped_descendants"] == [
        {"pid": 701, "ppid": 4242, "argv": _LEAKED_ARGV}
    ]

    assert len(stalls) == 1
    assert teardown_stall_for(cast(Any, process)) is stalls[0]
    assert stalls[0].settled.is_set()
    assert _LEAKED_ARGV in capsys.readouterr().err


def test_watchdog_ignores_a_declaration_left_by_an_earlier_provider_run(
    artifacts_dir: Path, terminated_trees: list[int]
) -> None:
    _accept_declaration(artifacts_dir)
    process = _FakeProcess(exit_after_polls=60)

    _start(process, grace=0.02).join(timeout=10)

    assert process.terminations == 0
    assert terminated_trees == []


def test_watchdog_treats_a_fresh_acceptance_as_the_trigger_even_if_the_file_exists(
    artifacts_dir: Path, terminated_trees: list[int]
) -> None:
    _accept_declaration(artifacts_dir)
    process = _FakeProcess()
    thread = _start(process, grace=0.02)

    # A later acceptance atomically replaces the stale file.
    replacement = artifacts_dir / "replacement.json"
    replacement.write_text("{}", encoding="utf-8")
    replacement.replace(artifacts_dir / FINAL_SUBMISSION_FILENAME)
    thread.join(timeout=10)

    assert terminated_trees == [4242]


def test_watchdog_reports_a_failing_teardown_and_still_settles(
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(process: Any, stall: TeardownStall, *, timeout: float) -> None:
        raise RuntimeError("ps exploded")

    monkeypatch.setattr(plain, "terminate_process_tree", broken)
    process = _FakeProcess()
    thread = _start(process, grace=0.02)
    _accept_declaration(artifacts_dir)

    thread.join(timeout=10)

    stall = teardown_stall_for(cast(Any, process))
    assert stall is not None
    assert stall.settled.is_set()
    assert "ps exploded" in capsys.readouterr().err


def test_watchdog_is_a_no_op_without_an_artifacts_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    assert start_completion_watchdog(cast(Any, _FakeProcess())) is None


def test_watchdog_grace_of_zero_disables_it(
    artifacts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(plain.TEARDOWN_GRACE_ENV, "0")

    assert start_completion_watchdog(cast(Any, _FakeProcess())) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 120.0),
        ("", 120.0),
        ("45", 45.0),
        ("0.5", 0.5),
        ("0", 0.0),
        ("soon", 120.0),
        ("-3", 120.0),
        ("nan", 120.0),
        ("inf", 120.0),
    ],
)
def test_teardown_grace_seconds_parsing(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float
) -> None:
    if raw is None:
        monkeypatch.delenv(plain.TEARDOWN_GRACE_ENV, raising=False)
    else:
        monkeypatch.setenv(plain.TEARDOWN_GRACE_ENV, raw)

    assert plain._teardown_grace_seconds() == expected


def test_every_interrupt_monitor_call_site_also_starts_the_watchdog() -> None:
    """The two share preconditions and lifetime; one without the other is a bug."""
    provider_dir = Path(plain.__file__).parent
    call = re.compile(r"^\s*start_interrupt_monitor\(", re.MULTILINE)
    watchdog = re.compile(r"^\s*start_completion_watchdog\(", re.MULTILINE)

    missing = [
        path.name
        for path in sorted(provider_dir.glob("*.py"))
        if path.name != "fakey.py"
        and (text := path.read_text(encoding="utf-8"))
        and len(call.findall(text)) != len(watchdog.findall(text))
    ]

    assert missing == []
