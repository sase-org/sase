"""Connect-leg tests for the sidecar auto-sync chop.

The leg gives an enabled project that is registered on this machine but never
connected (no materialized SDD store record) the same connect-only first-use
connection its first agent launch would. Every test fakes
``auto_connect_sdd_store``; nothing clones or touches the network.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import sase._sidecar_auto_connect as sidecar_auto_connect
from sase._sidecar_auto_sync import SidecarSyncResult
import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase.sdd.store import SddMaterializationError
from tests._axe_chop_sidecar_auto_sync_support import (
    configure_sidecar_sync,
    enable_connect_leg,
    make_project,
    make_runtime,
)

_CONNECT_KEY = "proj:__connect__"


def _connecting(connected: set[str], calls: list[str]) -> Callable[[str, int], bool]:
    def fake_connect(primary: str, workspace_num: int) -> bool:
        assert workspace_num == 1
        name = Path(primary).name
        calls.append(name)
        connected.add(name)
        return True

    return fake_connect


def _read_state(tmp_path: Path) -> dict[str, dict[str, object]]:
    state_path = tmp_path / "state" / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    return json.loads(state_path.read_text(encoding="utf-8"))


def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    current_time = [datetime(2026, 11, 7, 12, tzinfo=UTC)]
    monkeypatch.setattr(sidecar_sync_chop, "_utc_now", lambda: current_time[0])
    return current_time


def test_unconnected_project_is_connected_once_even_without_auto_sync_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No auto_sync roles: the leg must run before the no-targets return.
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
    )
    connected: set[str] = set()
    calls: list[str] = []
    enable_connect_leg(
        monkeypatch,
        connected_projects=connected,
        auto_connect=_connecting(connected, calls),
    )
    stdout = StringIO()
    runtime = make_runtime(tmp_path, stdout=stdout)

    first = sidecar_sync_chop._run(runtime)
    second = sidecar_sync_chop._run(runtime)

    assert calls == ["proj"]
    assert first.reason == "no_auto_sync_roles"
    assert first.counters["connected"] == 1
    assert first.counters["connect_failed"] == 0
    assert second.counters["connected"] == 0
    assert "Connected existing SDD sidecars for proj" in stdout.getvalue()
    assert _CONNECT_KEY not in _read_state(tmp_path)


def test_connected_or_missing_primaries_are_never_connected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = SimpleNamespace(
        is_project=True,
        workspace_dir=str(tmp_path / "projects" / "gone"),
        project_name="gone",
        project_file=None,
    )
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path), missing],
        roles_by_project={},
    )
    enable_connect_leg(
        monkeypatch,
        connected_projects={"proj"},
        auto_connect=lambda *_a: pytest.fail("connected an ineligible project"),
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.counters["connected"] == 0
    assert result.counters["connect_failed"] == 0


def test_connect_failure_backs_off_without_changing_status_or_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda project, role, **_kw: SidecarSyncResult(
            project, role, "up_to_date", "already fresh"
        ),
    )
    calls: list[str] = []

    def failing_connect(primary: str, _workspace_num: int) -> bool:
        calls.append(Path(primary).name)
        raise SddMaterializationError(
            "github sidecar repository proj--beads does not exist; "
            "run `sase repo init` to create it"
        )

    enable_connect_leg(
        monkeypatch, connected_projects=set(), auto_connect=failing_connect
    )
    current_time = _freeze_clock(monkeypatch)
    stderr = StringIO()
    runtime = make_runtime(tmp_path, stderr=stderr)

    first = sidecar_sync_chop._run(runtime)
    current_time[0] += timedelta(minutes=9)
    within_backoff = sidecar_sync_chop._run(runtime)
    current_time[0] += timedelta(minutes=2)
    after_backoff = sidecar_sync_chop._run(runtime)

    assert first.counters["connect_failed"] == 1
    assert first.counters["up_to_date"] == 1
    assert first.status == "ok"
    assert first.reason is None
    assert "proj--beads does not exist" in stderr.getvalue()
    assert within_backoff.counters["connect_failed"] == 0
    assert after_backoff.counters["connect_failed"] == 1
    assert calls == ["proj", "proj"]
    assert _read_state(tmp_path)[_CONNECT_KEY]["failures"] == 2


def test_only_one_project_connects_per_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[
            make_project(tmp_path, name="gamma"),
            make_project(tmp_path, name="alpha"),
            make_project(tmp_path, name="beta"),
        ],
        roles_by_project={},
    )
    connected: set[str] = set()
    calls: list[str] = []
    enable_connect_leg(
        monkeypatch,
        connected_projects=connected,
        auto_connect=_connecting(connected, calls),
    )
    runtime = make_runtime(tmp_path)

    counts = [sidecar_sync_chop._run(runtime).counters["connected"] for _ in range(4)]

    assert calls == ["alpha", "beta", "gamma"]
    assert counts == [1, 1, 1, 0]


def test_not_applicable_projects_do_not_use_up_the_ticks_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[
            make_project(tmp_path, name="alpha"),
            make_project(tmp_path, name="beta"),
        ],
        roles_by_project={},
    )
    connected: set[str] = set()
    calls: list[str] = []

    def connect(primary: str, _workspace_num: int) -> bool:
        name = Path(primary).name
        calls.append(name)
        if name == "alpha":
            return False  # Unmanaged: a cheap no-op.
        connected.add(name)
        return True

    enable_connect_leg(monkeypatch, connected_projects=connected, auto_connect=connect)
    _freeze_clock(monkeypatch)
    runtime = make_runtime(tmp_path)

    first = sidecar_sync_chop._run(runtime)
    second = sidecar_sync_chop._run(runtime)

    assert calls == ["alpha", "beta"]
    assert first.counters["connected"] == 1
    assert second.counters["connected"] == 0
    # The unmanaged project is rechecked at the backstop interval.
    assert _read_state(tmp_path)["alpha:__connect__"]["failures"] == 0


def test_connect_defers_when_too_little_work_budget_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
    )
    enable_connect_leg(
        monkeypatch,
        connected_projects=set(),
        auto_connect=lambda *_a: pytest.fail("connected without enough budget"),
    )
    monkeypatch.setattr(
        sidecar_sync_chop, "time", SimpleNamespace(monotonic=lambda: 0.0)
    )
    spent = (
        sidecar_sync_chop._WORK_BUDGET_SECONDS
        - sidecar_auto_connect.CONNECT_MIN_REMAINING_SECONDS
        + 1.0
    )
    monkeypatch.setattr(
        sidecar_auto_connect, "time", SimpleNamespace(monotonic=lambda: spent)
    )

    result = sidecar_sync_chop._run(make_runtime(tmp_path))

    assert result.counters["connected"] == 0
    assert result.counters["deferred"] == 1


def test_connect_entries_survive_the_role_target_stale_prune(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={"proj": ("plans",)},
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "sync_primary_sidecar_role",
        lambda project, role, **_kw: SidecarSyncResult(
            project, role, "up_to_date", "already fresh"
        ),
    )

    def failing_connect(_primary: str, _workspace_num: int) -> bool:
        raise SddMaterializationError("sidecar repository does not exist")

    enable_connect_leg(
        monkeypatch, connected_projects=set(), auto_connect=failing_connect
    )
    current_time = _freeze_clock(monkeypatch)
    runtime = make_runtime(tmp_path)
    state_path = tmp_path / "state" / sidecar_sync_chop._BACKOFF_STATE_FILENAME
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "gone:__connect__": {
                    "failures": 2,
                    "next_attempt_at": "2099-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    sidecar_sync_chop._run(runtime)
    current_time[0] += timedelta(minutes=1)
    sidecar_sync_chop._run(runtime)

    state = _read_state(tmp_path)
    assert state[_CONNECT_KEY]["failures"] == 1
    assert "proj:plans" in state
    assert "gone:__connect__" not in state


def test_connect_stderr_is_routed_into_the_chop_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_sidecar_sync(
        monkeypatch,
        tmp_path,
        records=[make_project(tmp_path)],
        roles_by_project={},
    )
    connected: set[str] = set()

    def noisy_connect(primary: str, _workspace_num: int) -> bool:
        print(
            "warning: github sidecar repository proj--agents is missing",
            file=sys.stderr,
        )
        connected.add(Path(primary).name)
        return True

    enable_connect_leg(
        monkeypatch, connected_projects=connected, auto_connect=noisy_connect
    )
    stderr = StringIO()

    result = sidecar_sync_chop._run(make_runtime(tmp_path, stderr=stderr))

    assert result.counters["connected"] == 1
    assert "proj--agents is missing" in stderr.getvalue()
    assert "proj--agents" not in capsys.readouterr().err
