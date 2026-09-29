"""Unit coverage for the shared gate-turn lane lock."""

from __future__ import annotations

from contextlib import nullcontext
from hashlib import sha256
from pathlib import Path

import pytest

from sase.core.paths import sase_projects_dir
from sase.gate_turn import transaction as transaction_module
from sase.gate_turn.lane_lock import gate_lane_lock, try_gate_lane_lock
from tests.gate_turn._cli_fixtures import gate_turn_home
from tests.gate_turn.test_transaction_gate_intent import (
    _install_transaction_fakes,
    _set_agent_env,
    _shell_gate_spec,
)

__all__ = ["gate_turn_home"]


def _expected_flock_path(project: str, lane: str) -> Path:
    key = sha256(f"{project}\0{lane}".encode()).hexdigest()[:32]
    base = sase_projects_dir() / project / "artifacts" / "ace-run" / f".gate-turn-{key}"
    assert len(key) == 32 and all(c in "0123456789abcdef" for c in key)
    return base.with_name(f".{base.name}.lock")


def test_lane_lock_uses_the_historical_flock_file(
    gate_turn_home: Path,
) -> None:
    """The shared lock must flock the same file the old transaction locked."""
    del gate_turn_home
    expected = _expected_flock_path("proj", "lane")
    assert expected.name.startswith("..gate-turn-")
    assert expected.name.endswith(".lock")

    with try_gate_lane_lock("proj", "lane") as acquired:
        assert acquired is True
        # The non-blocking attempt creates the flock file at the pinned path.
        assert expected.is_file()


def test_try_lock_defers_while_the_blocking_lock_is_held(
    gate_turn_home: Path,
) -> None:
    """flock belongs to open file descriptions, so the try fails in-process."""
    del gate_turn_home
    with gate_lane_lock("proj", "lane"):
        with try_gate_lane_lock("proj", "lane") as acquired:
            assert acquired is False

    with try_gate_lane_lock("proj", "lane") as acquired:
        assert acquired is True


def test_try_lock_is_per_lane(gate_turn_home: Path) -> None:
    """Holding one lane's lock must not block an unrelated lane."""
    del gate_turn_home
    with gate_lane_lock("proj", "lane-a"):
        with try_gate_lane_lock("proj", "lane-b") as acquired:
            assert acquired is True
        with try_gate_lane_lock("proj", "lane-a") as acquired:
            assert acquired is False


def test_creation_transaction_holds_the_shared_lane_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The creation transaction must lock (project, lane) via the helper."""
    _set_agent_env(tmp_path, monkeypatch)
    _install_transaction_fakes(tmp_path, monkeypatch)
    held: list[tuple[str, str]] = []

    def recording_lock(project_name: str, lane: str):
        held.append((project_name, lane))
        return nullcontext()

    monkeypatch.setattr(transaction_module, "gate_lane_lock", recording_lock)

    from sase.gate_turn.transaction import create_gate_turn

    create_gate_turn(_shell_gate_spec())

    assert held == [("proj", "agent")]
