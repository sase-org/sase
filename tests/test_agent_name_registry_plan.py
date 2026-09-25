"""Plan-only registry reservations must match mutate blocked-ness."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    RegisteredNameReservation,
    RegisteredNameReservationBatchError,
    claim_registered_name,
    mutate_registered_name_reservations,
    plan_registered_name_reservations,
    reserve_registered_clan_name,
    reserve_registered_name,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

from tests._agent_names_fixtures import make_agent as _make_agent


def _configure_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda _cls: identity),
    )


def _planned(name: str, artifact_dir: Path) -> RegisteredNameReservation:
    return RegisteredNameReservation(
        request_id="parity",
        operation="reserve_planned",
        name=name,
        artifact_dir=artifact_dir,
    )


def _assert_plan_matches_mutate(
    reservations: list[RegisteredNameReservation],
) -> None:
    planned = plan_registered_name_reservations(reservations)
    blocked = bool(planned.blocked)
    if blocked:
        with pytest.raises(RegisteredNameReservationBatchError):
            mutate_registered_name_reservations(reservations)
        return
    mutate_registered_name_reservations(reservations)


def test_plan_matches_mutate_for_free_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/free"
    with patch.object(Path, "home", return_value=tmp_path):
        _assert_plan_matches_mutate([_planned("free-name", candidate)])


def test_plan_matches_mutate_for_live_claimed_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    live_dir = _make_agent(tmp_path, "proj", "live", "taken-live", pid=os.getpid())
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/candidate"
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("taken-live", live_dir)
        _assert_plan_matches_mutate([_planned("taken-live", candidate)])


def test_plan_matches_mutate_for_done_claimed_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    done_dir = _make_agent(
        tmp_path, "proj", "done", "taken-done", done=True, outcome="failed"
    )
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/candidate"
    with patch.object(Path, "home", return_value=tmp_path):
        claim_registered_name("taken-done", done_dir)
        _assert_plan_matches_mutate([_planned("taken-done", candidate)])


def test_plan_matches_mutate_for_stale_planned_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    missing_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/missing"
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/candidate"
    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_name("stale-planned", missing_dir)
        assert not missing_dir.exists()
        _assert_plan_matches_mutate([_planned("stale-planned", candidate)])


def test_plan_matches_mutate_for_clan_container_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    clan_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/clan"
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/candidate"
    with patch.object(Path, "home", return_value=tmp_path):
        reserve_registered_clan_name("clan-name", "run0", clan_dir)
        _assert_plan_matches_mutate([_planned("clan-name", candidate)])


def test_plan_does_not_apply_blocked_or_accepted_reservations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_machine(monkeypatch)
    candidate = tmp_path / ".sase/projects/proj/artifacts/ace-run/free"
    with patch.object(Path, "home", return_value=tmp_path):
        from sase.agent.names import lookup_registered_name

        result = plan_registered_name_reservations([_planned("plan-only", candidate)])
        assert result.blocked == ()
        assert lookup_registered_name("plan-only") is None
