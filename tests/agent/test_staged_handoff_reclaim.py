"""Dead-owner staging reservations are reclaimed; fail-closed ones keep occupying."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.agent.pending_handoff_write import PendingHandoffError, handoff_guard
from sase.agent.staged_handoff import (
    STAGING_RESERVATION_FILENAME,
    occupying_handoff_names,
)
from sase.core.process_identity import process_identity_token
from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV

_DEAD_PID = 2**30
_STALE_GLOB = ".sase_handoff_staging.stale-*.json"


def _agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)


def _write_reservation(
    root: Path,
    *,
    pid: int | None,
    process_identity: str | None = None,
    extra: str | None = None,
) -> None:
    path = root / STAGING_RESERVATION_FILENAME
    if extra is not None:
        path.write_text(extra, encoding="utf-8")
        return
    payload: dict[str, object] = {"reservation_id": "dead-owner-reservation"}
    if pid is not None:
        payload["pid"] = pid
    if process_identity is not None:
        payload["process_identity"] = process_identity
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stale_evidence(root: Path) -> list[Path]:
    return sorted(root.glob(_STALE_GLOB))


def test_dead_pid_reservation_is_reclaimed_and_writes_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_env(monkeypatch, tmp_path)
    _write_reservation(tmp_path, pid=_DEAD_PID, process_identity="dead-boot:1")

    assert occupying_handoff_names(str(tmp_path)) == ()
    assert not (tmp_path / STAGING_RESERVATION_FILENAME).exists()
    evidence = _stale_evidence(tmp_path)
    assert len(evidence) == 1
    payload = json.loads(evidence[0].read_text(encoding="utf-8"))
    assert payload["pid"] == _DEAD_PID
    assert handoff_guard() == str(tmp_path)


def test_live_pid_reservation_keeps_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_env(monkeypatch, tmp_path)
    pid = os.getpid()
    _write_reservation(tmp_path, pid=pid, process_identity=process_identity_token(pid))

    occupying = occupying_handoff_names(str(tmp_path))
    assert occupying == (f"{STAGING_RESERVATION_FILENAME} (owner pid {pid}, alive)",)
    assert (tmp_path / STAGING_RESERVATION_FILENAME).is_file()
    assert _stale_evidence(tmp_path) == []
    with pytest.raises(
        PendingHandoffError,
        match=rf"pending handoff already exists: .*\(owner pid {pid}, alive\)",
    ):
        handoff_guard()


def test_identity_mismatch_reservation_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_env(monkeypatch, tmp_path)
    _write_reservation(
        tmp_path,
        pid=os.getpid(),
        process_identity="ffffffff-ffff-ffff-ffff-ffffffffffff:1",
    )
    monkeypatch.setattr(
        "sase.agent._staged_handoff_admission.process_identity_matches",
        lambda _pid, _recorded: False,
    )

    assert occupying_handoff_names(str(tmp_path)) == ()
    assert not (tmp_path / STAGING_RESERVATION_FILENAME).exists()
    assert len(_stale_evidence(tmp_path)) == 1
    assert handoff_guard() == str(tmp_path)


def test_malformed_reservation_keeps_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_env(monkeypatch, tmp_path)
    _write_reservation(tmp_path, pid=None, extra="{")

    occupying = occupying_handoff_names(str(tmp_path))
    assert occupying == (f"{STAGING_RESERVATION_FILENAME} (unreadable)",)
    assert (tmp_path / STAGING_RESERVATION_FILENAME).is_file()
    assert _stale_evidence(tmp_path) == []
    with pytest.raises(PendingHandoffError, match=r"unreadable"):
        handoff_guard()


def test_no_pid_reservation_keeps_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _agent_env(monkeypatch, tmp_path)
    _write_reservation(tmp_path, pid=None)

    occupying = occupying_handoff_names(str(tmp_path))
    assert occupying == (f"{STAGING_RESERVATION_FILENAME} (no owner pid)",)
    assert (tmp_path / STAGING_RESERVATION_FILENAME).is_file()
    assert _stale_evidence(tmp_path) == []
    with pytest.raises(PendingHandoffError, match=r"no owner pid"):
        handoff_guard()
