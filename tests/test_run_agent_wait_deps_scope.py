"""Runner startup/fallback wait views stay scoped for named waits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.axe.run_agent_wait_deps import (
    _release_satisfied_at,
    resolve_initial_wait_release,
    waiting_marker_dependencies_resolved,
)
from sase.core.agent_tribe_evidence import stored_tribe_names_for_resolution
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    marker_needs_global_tribes,
    resolve_wait_release,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._monitor_wait_dependency_helpers import (
    monitor_handoff_agent_session,
    write_completed_workflow_state,
)


def _full_runner_decision(
    marker: dict[str, object],
    waiter_dir: Path,
    *,
    project_name: str = "proj",
) -> object:
    def build_index() -> WaitDependencyIndex:
        return build_wait_dependency_index(project_name)

    return resolve_wait_release(
        build_index(),
        marker,
        waiter_dir=waiter_dir,
        closed_bead_ids=frozenset(),
        now=1_800_000_000.0,
        fresh_index=build_index,
    )


def _assert_scoped_matches_full(
    wait_names: list[str],
    waiter_dir: Path,
) -> None:
    marker: dict[str, object] = {"waiting_for": wait_names}
    scoped = resolve_initial_wait_release(
        wait_names,
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    full = _full_runner_decision(marker, waiter_dir)
    assert (
        scoped.status.resolved,
        scoped.status.blocked_on,
        scoped.releasable,
        scoped.confirmation_failed,
    ) == (
        full.status.resolved,
        full.status.blocked_on,
        full.releasable,
        full.confirmation_failed,
    )


_TRIBE_SCAN = "sase.axe.run_agent_wait_deps.stored_tribe_names_for_resolution"
_TRIBE_PREDICATE = "sase.axe.run_agent_wait_deps.marker_needs_global_tribes"


def _forbid_tribe_scan(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Make the global tribe scan raise and record every attempted call."""
    calls: list[object] = []

    def _scan(*args: object, **kwargs: object) -> tuple[str, ...]:
        calls.append((args, kwargs))
        raise AssertionError("scoped waits must not scan stored tribes")

    monkeypatch.setattr(_TRIBE_SCAN, _scan)
    return calls


def _observe_runner_wait(waiter_dir: Path, wait_names: list[str]) -> tuple[object, ...]:
    """Return the runner's startup decision plus its fallback release values."""
    decision = resolve_initial_wait_release(
        wait_names,
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    fallback = waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    return (
        decision.status.resolved,
        decision.status.blocked_on,
        decision.releasable,
        decision.confirmation_failed,
        fallback.resolved,
        fallback.satisfied_at,
    )


def _assert_tribe_scan_is_irrelevant(
    monkeypatch: pytest.MonkeyPatch,
    waiter_dir: Path,
    wait_names: list[str],
) -> tuple[object, ...]:
    """Scoped decisions match a forced global tribe scan, which they skip."""
    calls: list[object] = []

    def _counting_scan(**kwargs: object) -> tuple[str, ...]:
        calls.append(kwargs)
        return stored_tribe_names_for_resolution()

    monkeypatch.setattr(_TRIBE_SCAN, _counting_scan)
    skipped = _observe_runner_wait(waiter_dir, wait_names)
    assert calls == []

    monkeypatch.setattr(_TRIBE_PREDICATE, lambda _marker: True)
    try:
        scanned = _observe_runner_wait(waiter_dir, wait_names)
    finally:
        monkeypatch.setattr(_TRIBE_PREDICATE, marker_needs_global_tribes)
    assert calls
    assert skipped == scanned
    return skipped


def _write_tribe_evidence(tmp_path: Path, tribe: str) -> None:
    """Give the cross-project tribe scan real evidence that names *tribe*."""
    make_agent(
        tmp_path,
        "other-project",
        "20260506005959",
        f"{tribe}-member",
        done=True,
        outcome="completed",
        extra_meta={"tribe": tribe},
    )
    tribes_path = tmp_path / ".sase" / "agent_tribes.json"
    tribes_path.write_text(
        json.dumps(
            [{"id": ["run", f"{tribe}-member", "20260506005959"], "tribe": tribe}]
        ),
        encoding="utf-8",
    )


def test_runner_scoped_named_wait_matches_full_handoff_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
    root_dir, monitor_dir, handoff_dir = monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )
    assert handoff_dir is not None
    write_completed_workflow_state(handoff_dir)
    next_monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090200",
        "monitor-lane--mon-0",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=handoff_dir.name,
    )
    make_agent(tmp_path, "proj", "20261011010101", "unrelated")
    _write_tribe_evidence(tmp_path, "monitor-lane")

    _assert_scoped_matches_full(["monitor-lane"], waiter_dir)
    assert not _assert_tribe_scan_is_irrelevant(
        monkeypatch, waiter_dir, ["monitor-lane"]
    )[2]
    assert not resolve_initial_wait_release(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable

    (next_monitor_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )
    _assert_scoped_matches_full(["monitor-lane"], waiter_dir)
    assert _assert_tribe_scan_is_irrelevant(monkeypatch, waiter_dir, ["monitor-lane"])[
        2
    ]
    assert resolve_initial_wait_release(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable
    assert root_dir.exists() and monitor_dir.exists()


def test_runner_scoped_named_wait_matches_full_newer_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "newer-failure")
    make_agent(
        tmp_path,
        "proj",
        "20261011020701",
        "newer-failure",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20261011020702",
        "newer-failure",
        done=True,
        outcome="failed",
    )
    make_agent(tmp_path, "proj", "20261011020703", "unrelated")
    _write_tribe_evidence(tmp_path, "newer-failure")

    _assert_scoped_matches_full(["newer-failure"], waiter_dir)
    assert not _assert_tribe_scan_is_irrelevant(
        monkeypatch, waiter_dir, ["newer-failure"]
    )[2]
    assert not resolve_initial_wait_release(
        ["newer-failure"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable


def test_runner_unscopable_marker_calls_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "@job")
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    resolve_initial_wait_release(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert spy.call_args_list
    assert all(call.args == ("proj",) for call in spy.call_args_list)


def test_runner_scopable_named_wait_skips_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    assert resolve_initial_wait_release(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable
    spy.assert_not_called()


def test_runner_identity_dep_keeps_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    resolve_initial_wait_release(
        [],
        [
            {
                "name": "foo",
                "project_name": "proj",
                "timestamp": "20260506010101",
                "artifact_dir": str(tmp_path / "missing"),
            }
        ],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    spy.assert_called()


def test_waiting_marker_fallback_scopes_satisfied_at_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    assert waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    spy.assert_not_called()


def test_runner_scoped_named_wait_skips_global_tribe_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo", "bar")
    for suffix, name in (("20260506010101", "foo"), ("20260506010102", "bar")):
        make_agent(tmp_path, "proj", suffix, name, done=True, outcome="completed")
    calls = _forbid_tribe_scan(monkeypatch)

    assert resolve_initial_wait_release(
        ["foo", "bar"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable
    assert waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert calls == []
    assert "Wait dependency check failed" not in capsys.readouterr().out


def test_runner_scoped_satisfied_at_matches_forced_tribe_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    dep_dir = make_agent(tmp_path, "proj", "20260506010101", "foo")
    (dep_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "finished_at": 1_800_000_000.5}),
        encoding="utf-8",
    )
    make_agent(tmp_path, "proj", "20260506010102", "unrelated")
    _write_tribe_evidence(tmp_path, "foo")

    observed = _assert_tribe_scan_is_irrelevant(monkeypatch, waiter_dir, ["foo"])

    assert observed[2] is True
    assert observed[4:] == (True, 1_800_000_000.5)


@pytest.mark.parametrize(
    "wait_kwargs",
    [
        pytest.param({"wait_names": ["@job"]}, id="tribe"),
        pytest.param({"wait_names": ["foo"], "wait_hoods": ["team"]}, id="hood"),
        pytest.param(
            {
                "wait_names": [],
                "wait_identity_deps": [
                    {
                        "name": "foo",
                        "project_name": "proj",
                        "timestamp": "20260506010101",
                    }
                ],
            },
            id="artifact",
        ),
        pytest.param(
            {
                "wait_names": [],
                "wait_fork_sources": [{"name": "foo", "timestamp": "20260506010101"}],
            },
            id="fork-source",
        ),
        pytest.param(
            {"wait_names": ["planner"], "wait_for_epics_of": ["planner"]},
            id="epics-of",
        ),
        pytest.param(
            {
                "wait_names": ["planner"],
                "wait_epic_follows": [{"target": "planner", "state": "following"}],
            },
            id="armed-follow",
        ),
    ],
)
def test_runner_unscopable_marker_keeps_global_tribe_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    wait_kwargs: dict[str, Any],
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    scan = MagicMock(return_value=())
    monkeypatch.setattr(_TRIBE_SCAN, scan)
    kwargs = dict(wait_kwargs)
    wait_names = kwargs.pop("wait_names")
    wait_identity_deps = kwargs.pop("wait_identity_deps", [])

    resolve_initial_wait_release(
        wait_names,
        wait_identity_deps,
        project_name="proj",
        artifacts_dir=str(waiter_dir),
        **kwargs,
    )

    scan.assert_called()


def test_runner_satisfied_at_scans_tribes_only_for_unscopable_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    calls = _forbid_tribe_scan(monkeypatch)

    _release_satisfied_at(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert calls == []

    scan = MagicMock(return_value=())
    monkeypatch.setattr(_TRIBE_SCAN, scan)
    _release_satisfied_at(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    scan.assert_called_once_with()
