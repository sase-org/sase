"""Tests for the ``wait_checks`` heartbeat stamp and where the chop writes it."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.axe.wait_checks_heartbeat import (
    stamp_wait_checks_heartbeat,
    wait_checks_heartbeat_path,
)
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


@pytest.fixture(autouse=True)
def _home_under_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def _stamp_epoch() -> float:
    return float(wait_checks_heartbeat_path().read_text(encoding="utf-8").strip())


def test_heartbeat_lives_under_the_axe_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert wait_checks_heartbeat_path() == tmp_path / ".sase" / "axe" / (
        "wait_checks_heartbeat"
    )

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "elsewhere"))

    assert wait_checks_heartbeat_path() == (
        tmp_path / "elsewhere" / "axe" / "wait_checks_heartbeat"
    )


def test_stamp_writes_the_current_epoch_atomically() -> None:
    before = time.time()

    stamp_wait_checks_heartbeat()

    assert before <= _stamp_epoch() <= time.time()
    assert list(wait_checks_heartbeat_path().parent.glob(".*tmp")) == []


def test_stamp_overwrites_the_previous_epoch() -> None:
    path = wait_checks_heartbeat_path()
    path.parent.mkdir(parents=True)
    path.write_text("1.0\n", encoding="utf-8")

    stamp_wait_checks_heartbeat()

    assert _stamp_epoch() > 1.0


def test_stamp_never_raises_when_the_state_dir_is_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(blocker))

    stamp_wait_checks_heartbeat()

    assert blocker.read_text(encoding="utf-8") == "file"


def test_stamp_never_raises_when_the_path_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode() -> Path:
        raise RuntimeError("no home")

    monkeypatch.setattr(
        "sase.axe.wait_checks_heartbeat.wait_checks_heartbeat_path", explode
    )

    stamp_wait_checks_heartbeat()


def test_wait_checks_stamps_the_heartbeat_on_a_no_op_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No projects dir at all: the chop takes its early no-op exit.
    assert not (tmp_path / ".sase" / "projects").exists()
    before = time.time()

    run_wait_checks(tmp_path, monkeypatch)

    assert before <= _stamp_epoch() <= time.time()


def test_wait_checks_stamps_the_heartbeat_on_a_normal_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_waiting_agent(tmp_path, "foo")
    before = time.time()

    run_wait_checks(tmp_path, monkeypatch)

    assert before <= _stamp_epoch() <= time.time()


def test_wait_checks_does_not_stamp_when_the_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> Path:
        raise RuntimeError("projects dir exploded")

    monkeypatch.setattr("sase.scripts._chop_wait_checks_run.sase_projects_dir", explode)

    with pytest.raises(RuntimeError, match="projects dir exploded"):
        run_wait_checks(tmp_path, monkeypatch)

    assert not wait_checks_heartbeat_path().exists()
