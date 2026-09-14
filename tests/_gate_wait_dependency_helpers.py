"""Shared helpers for gate wait-dependency tests."""

from __future__ import annotations

import json
from pathlib import Path

from tests._agent_names_fixtures import make_agent

_MISSING = object()


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _family_fork_source(root_dir: Path, *, name: str) -> dict[str, str]:
    return {**_identity_dep(root_dir, name=name), "kind": "family"}


def _update_meta(artifact_dir: Path, **updates: object) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_gate_done(
    artifact_dir: Path,
    *,
    gate_state: object = "answered",
    followup_outcome: str | None = None,
    followup_agent: str | None = None,
) -> None:
    done: dict[str, object] = {"outcome": "gated"}
    if gate_state is not _MISSING:
        done["gate_state"] = gate_state
    if followup_outcome is not None:
        done["gate_followup_outcome"] = followup_outcome
    if followup_agent is not None:
        done["gate_followup_agent"] = followup_agent
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _gate_member(
    tmp_path: Path,
    gate_state: object,
    *,
    with_done_marker: bool = True,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate",
        extra_meta={
            "agent_family_role": "gate",
            "agent_clan": "gate-clan",
            "agent_clan_generation": "20260827085900",
            "gate_id": "gate-1",
            "gate_state": "pending",
        },
    )
    if with_done_marker:
        _write_gate_done(artifact_dir, gate_state=gate_state)
    return artifact_dir


def _write_completed_workflow_state(artifact_dir: Path) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "gate-lane",
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


def _gate_handoff_family(
    tmp_path: Path,
    *,
    gate_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "gate-lane--1",
    successor_outcome: str | None | bool = "completed",
) -> tuple[Path, Path, Path | None]:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_family_role": "gate",
            "gate_id": "gate-1",
            "gate_state": gate_state,
            "gate_followup_outcome": followup_outcome,
            "gate_followup_agent": followup_agent,
        },
    )
    _write_gate_done(
        gate_dir,
        gate_state=gate_state,
        followup_outcome=followup_outcome,
        followup_agent=None,
    )

    successor_dir: Path | None = None
    if successor_outcome is not None:
        successor_dir = make_agent(
            tmp_path,
            "proj",
            "20260827090100",
            followup_agent or "gate-lane--1",
            workflow_name="gate-lane",
            agent_family="gate-lane",
            role_suffix="--1",
            parent_timestamp=gate_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    return root_dir, gate_dir, successor_dir
