"""Shared helpers for monitor wait-dependency tests."""

from __future__ import annotations

import json
from pathlib import Path

from tests._agent_names_fixtures import make_agent


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _family_fork_source(root_dir: Path, *, name: str) -> dict[str, str]:
    return {**_identity_dep(root_dir, name=name), "kind": "family"}


def _monitor_member(
    tmp_path: Path,
    monitor_state: object,
    *,
    with_done_marker: bool = True,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "agent_clan": "monitor-clan",
            "agent_clan_generation": "20260813085900",
            "monitor_state": "running",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if with_done_marker:
        done: dict[str, object] = {"outcome": "monitored"}
        if monitor_state is not None:
            done["monitor_state"] = monitor_state
        (artifact_dir / "done.json").write_text(
            json.dumps(done),
            encoding="utf-8",
        )
    return artifact_dir


def _update_meta(artifact_dir: Path, **updates: object) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_monitor_done(
    artifact_dir: Path,
    *,
    monitor_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "monitor-lane--1",
) -> None:
    done: dict[str, object] = {
        "outcome": "monitored",
        "monitor_state": monitor_state,
    }
    if followup_outcome is not None:
        done["monitor_followup_outcome"] = followup_outcome
    if followup_agent is not None:
        done["monitor_followup_agent"] = followup_agent
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _write_completed_workflow_state(artifact_dir: Path) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "monitor-lane",
                "status": "completed",
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "main",
                        "status": "completed",
                        "error": None,
                        "traceback": None,
                    }
                ],
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "completed",
                "error": None,
                "traceback": None,
            }
        ),
        encoding="utf-8",
    )


def _monitor_handoff_family(
    tmp_path: Path,
    *,
    monitor_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "monitor-lane--1",
    successor_outcome: str | None | bool = "completed",
) -> tuple[Path, Path, Path | None]:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "monitor-lane--plan",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state=monitor_state,
        monitor_followup_outcome=followup_outcome,
        monitor_followup_agent=followup_agent,
    )
    _write_monitor_done(
        monitor_dir,
        monitor_state=monitor_state,
        followup_outcome=followup_outcome,
        followup_agent=None,
    )

    successor_dir: Path | None = None
    if successor_outcome is not None:
        successor_dir = make_agent(
            tmp_path,
            "proj",
            "20260813090100",
            followup_agent or "monitor-lane--1",
            workflow_name="monitor-lane",
            agent_family="monitor-lane",
            role_suffix="--1",
            parent_timestamp=root_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    return root_dir, monitor_dir, successor_dir
