from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.agent.identity import AgentIdentity
from sase.artifact_read_log import (
    ArtifactReadError,
    append_artifact_read_event,
    artifact_read_log_path,
    build_artifact_read_event,
    read_artifact_read_events,
)
from tests._conftest_environment import redirect_sase_home


def _event(**overrides: object) -> object:
    values: dict[str, object] = {
        "ref": "plan:202608/report.md",
        "reason": "need the design of record",
        "recorded_link": False,
        "project": "gh_sase-org__sase",
        "cwd": Path("/work/sase_10"),
        "now": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        "read_id": "read-1",
        "agent": AgentIdentity("alice.athena.worker", "SASE_AGENT_NAME", "/artifacts"),
    }
    values.update(overrides)
    return build_artifact_read_event(**values)  # type: ignore[arg-type]


def test_normalize_read_reason_rejects_blank() -> None:
    event = _event(reason="  Need context  ")
    assert event.reason == "Need context"
    with pytest.raises(ArtifactReadError, match="must not be empty"):
        _event(reason="   ")


def test_append_and_read_skip_malformed_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    event = _event()

    append_artifact_read_event(event, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write(json.dumps({"schema_version": 99}) + "\n")

    assert read_artifact_read_events(log_path=log_path) == (event,)


def test_interactive_identity_is_recorded_without_a_link() -> None:
    event = build_artifact_read_event(
        ref="research:202608/report.md",
        reason="skim the report",
        recorded_link=False,
        project="gh_sase-org__sase",
        cwd=Path("/work"),
        env={},
        now=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        read_id="read-2",
    )

    assert event.agent_source == "interactive"
    assert event.recorded_link is False
    assert event.reason == "skim the report"


def test_artifact_read_log_path_uses_project_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    path = artifact_read_log_path("gh_sase-org__sase")
    assert path == tmp_path / ".sase" / "projects" / "gh_sase-org__sase" / (
        "artifact_reads.jsonl"
    )
