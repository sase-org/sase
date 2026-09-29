"""Gate follow-up tests for gateless ``sase plan approve`` runs.

Split from ``tests.test_plan_direct_approval_recovery``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.plan_direct_approval_recovery import (
    PriorCoder,
    _gate_followup_coder,
    prior_coder_word,
)
from tests._plan_direct_approval_recovery_helpers import (
    no_color,  # noqa: F401 (registers the autouse fixture)
)

__all__ = [
    "test_gate_followup_falls_back_to_registered_code",
    "test_gate_followup_prefers_verified_shell",
    "test_prior_coder_words",
]


def test_gate_followup_prefers_verified_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.paths import sase_projects_dir  # noqa: F401

    shell_dir = tmp_path / "shell"
    shell_dir.mkdir()
    (shell_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_notification_id": "gate123",
                "gate_followup_agent": "0sk--code",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
        lambda project, workflow, suffix: shell_dir,
    )
    entry: dict[str, object] = {
        "notification_id": "gate123",
        "action_data": {"raw_suffix": "20260925000000", "agent_name": "0sk"},
    }

    assert _gate_followup_coder(entry, "demo") == "0sk--code"


def test_gate_followup_falls_back_to_registered_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.names.lookup_registered_name",
        lambda name: (
            {"artifacts_dir": "/x", "state": "reserved"}
            if name == "0sk--code"
            else None
        ),
    )
    entry: dict[str, object] = {
        "notification_id": "gate123",
        "action_data": {"agent_name": "0sk"},
    }

    assert _gate_followup_coder(entry, "demo") == "0sk--code"


def test_prior_coder_words() -> None:
    assert (
        prior_coder_word(PriorCoder(name="c", state="live", outcome="running"))
        == "running"
    )
    assert (
        prior_coder_word(
            PriorCoder(name="c", state="ended", outcome="failed", age="14m ago")
        )
        == "failed 14m ago"
    )
    assert (
        prior_coder_word(
            PriorCoder(name="c", state="succeeded", outcome="completed", age="2h ago")
        )
        == "completed 2h ago"
    )
    assert prior_coder_word(PriorCoder(name="c", state="missing")) == "not found"
