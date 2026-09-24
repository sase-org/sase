"""Fault-isolation tests for the wait_checks chop script.

One waiter whose resolution raises must park only itself: healthy waiters in
the same tick are still released, the tick summary counts ``waiter_errors``,
and the structured result status is ``check_error``.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.wait_dependency_resolution import WaitDependencyIndex
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._monitor_wait_dependency_helpers import _update_meta, _write_monitor_done


def test_one_bad_waiter_parks_only_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    bad_waiter_dir = make_waiting_agent(tmp_path, "foo", suffix="waiter-1")
    good_waiter_dir = make_waiting_agent(tmp_path, "foo", suffix="waiter-2")

    original_member_dirs = WaitDependencyIndex.dependency_member_dirs

    def flaky_member_dirs(
        self: WaitDependencyIndex, *args: Any, **kwargs: Any
    ) -> frozenset[str]:
        self_dir = kwargs.get("self_artifact_dir")
        if self_dir is not None and str(self_dir) == str(bad_waiter_dir):
            raise RuntimeError("boom")
        return original_member_dirs(self, *args, **kwargs)

    monkeypatch.setattr(
        WaitDependencyIndex, "dependency_member_dirs", flaky_member_dirs
    )
    result_path = tmp_path / "result.json"
    monkeypatch.setenv("SASE_CHOP_RESULT_FILE", str(result_path))

    run_wait_checks(tmp_path, monkeypatch)

    assert (good_waiter_dir / "ready.json").exists()
    assert not (bad_waiter_dir / "ready.json").exists()
    out = capsys.readouterr().out
    assert "waiter_errors=1" in out
    assert "failed: boom" in out
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "check_error"
    assert result["counters"]["waiter_errors"] == 1


def test_monitor_followup_waiter_with_code_fork_source_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the fork-source path that crashed production for ``0r2--1``.

    A live ``--1`` waiter on a completed ``--code`` dependency, with a
    ``kind: "agent"`` fork-source entry pointing at the ``--code`` artifact
    dir, must resolve even though its ``--mon`` predecessor failed with a
    launched monitor followup.
    """
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090000",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090100",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090200",
        "lane--mon",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state="failed",
        monitor_followup_outcome="launched",
        monitor_followup_agent="lane--1",
    )
    _write_monitor_done(
        monitor_dir,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent="lane--1",
    )
    waiter_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090300",
        "lane--1",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--1",
        parent_timestamp=root_dir.name,
    )
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["lane--code"],
                "wait_for_fork_sources": [
                    {
                        "kind": "agent",
                        "name": "lane--code",
                        "project_name": "proj",
                        "timestamp": code_dir.name,
                        "artifact_dir": str(code_dir),
                    }
                ],
                "cl_name": "lane--1",
                "timestamp": waiter_dir.name,
            }
        ),
        encoding="utf-8",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["lane--code"]}
