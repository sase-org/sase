"""Shared helpers for trusted EpicResume gate tests."""

from __future__ import annotations

from typing import Any

from sase.bead.epic_resume_gate import build_epic_resume_gate_spec
from sase.bead.epic_resume_launch import build_epic_resume_argv

DEFAULT_STALLED_SINCE = "2026-08-17T12:00:00-04:00"


def epic_resume_member(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "agent_name": "sase-p4.1",
        "bead_id": "sase-p4.1",
        "finished_at": "2026-08-17T11:45:00-04:00",
    }
    fields.update(overrides)
    return fields


def epic_resume_spec(
    *, request_id: str = "epic-resume-1", **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "request_id": request_id,
        "project": "sase",
        "epic_id": "sase-p4",
        "epic_title": "Raise an EpicResume gate when a failed phase agent stalls an epic",
        "clan_generation": 1,
        "failed_members": [epic_resume_member()],
        "waiting_members": [
            epic_resume_member(
                agent_name="sase-p4.3",
                bead_id="sase-p4.3",
                finished_at=None,
            ),
            epic_resume_member(
                agent_name="sase-p4.land",
                bead_id="sase-p4.land",
                finished_at=None,
            ),
        ],
        "remaining_phase_count": 2,
        "stalled_since": DEFAULT_STALLED_SINCE,
        "producer": {"chop": "epic_resume"},
    }
    fields.update(overrides)
    return build_epic_resume_gate_spec(**fields)


def expected_resume_argv(epic_id: str = "sase-p4") -> list[str]:
    return build_epic_resume_argv(epic_id)
