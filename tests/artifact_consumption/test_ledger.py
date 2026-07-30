"""Tests for artifact-consumption event construction and persistence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.core import artifact_consumption
from sase.core.artifact_consumption import (
    ARTIFACT_CONSUMPTION_LOG_SCHEMA_VERSION,
    ArtifactConsumptionEvent,
    append_artifact_consumption_events,
    artifact_consumption_role,
    build_artifact_consumption_event,
)
from sase.core.rust import require_rust_binding


@pytest.mark.parametrize(
    ("kind_type", "kind", "path", "expected"),
    (
        ("chat", "chat", Path("chat.json"), "report"),
        ("document", "research", Path("report.data"), "report"),
        ("file", "file", Path("report.md"), "report"),
        ("file", "file", Path("notes.txt"), "report"),
        ("file", "file", Path("paper.pdf"), "report"),
        ("file", "file", Path("figure.png"), "image"),
        ("file", "file", Path("recording.webm"), "image"),
        ("file", "file", Path("results.json"), "source"),
        ("bead", "bead", Path("README.md"), "source"),
        ("bug", "bug", None, "source"),
    ),
)
def test_artifact_consumption_role_derivation(
    kind_type: str,
    kind: str,
    path: Path | None,
    expected: str,
) -> None:
    assert artifact_consumption_role(kind_type, kind, path) == expected


def test_build_event_from_agent_environment() -> None:
    artifacts_dir = (
        "/home/user/.sase/projects/gh_sase-org__sase/artifacts/ace-run/20260730134501"
    )
    event = build_artifact_consumption_event(
        ref="file:default:abc",
        ref_kind="file",
        fragment=None,
        role="image",
        artifact_id="default:abc",
        resolved_path=Path("/tmp/figure.png"),
        resolution_status="exact",
        now=datetime(2026, 7, 30, 14, 2, 11, 481293, tzinfo=UTC),
        consumption_id="3f0a91c2d4e5",
        env={
            "SASE_AGENT_NAME": "sase-b8.2",
            "SASE_ARTIFACTS_DIR": artifacts_dir,
        },
    )

    assert event == ArtifactConsumptionEvent(
        id="3f0a91c2d4e5",
        timestamp="2026-07-30T14:02:11.481293+00:00",
        ref="file:default:abc",
        ref_kind="file",
        fragment=None,
        role="image",
        artifact_id="default:abc",
        resolved_path="/tmp/figure.png",
        resolution_status="exact",
        agent_name="sase-b8.2",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir=artifacts_dir,
        project="gh_sase-org__sase",
    )


def test_build_event_uses_interactive_fallback() -> None:
    event = build_artifact_consumption_event(
        ref="bug:sase#42",
        ref_kind="bug",
        fragment=None,
        role="source",
        artifact_id=None,
        resolved_path=None,
        resolution_status="exact",
        env={},
        login_user="bryan",
        consumption_id="event-id",
        now=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert event.agent_name == "bryan"
    assert event.agent_source == "interactive"
    assert event.artifacts_dir is None
    assert event.project is None


def test_append_round_trips_envelope_shape(tmp_path: Path) -> None:
    log_path = tmp_path / "consumption.jsonl"
    event = _event("event-a", "file:default:abc")

    append_artifact_consumption_events((event,), log_path=log_path)

    envelope = json.loads(log_path.read_text(encoding="utf-8"))
    assert envelope == {
        "schema_version": ARTIFACT_CONSUMPTION_LOG_SCHEMA_VERSION,
        "consumption": {
            "agent_name": "agent-a",
            "agent_source": "SASE_AGENT_NAME",
            "artifact_id": "default:abc",
            "artifacts_dir": "/artifacts",
            "fragment": None,
            "id": "event-a",
            "project": None,
            "ref": "file:default:abc",
            "ref_kind": "file",
            "resolution_status": "exact",
            "resolved_path": "/tmp/report.md",
            "role": "report",
            "timestamp": "2026-07-30T14:00:00+00:00",
        },
    }
    assert ArtifactConsumptionEvent(**envelope["consumption"]) == event
    summarize = require_rust_binding("artifact_consumption_summary")
    assert summarize(str(log_path), None) == {
        "file:default:abc": {
            "agent_names": ["agent-a"],
            "consumption_count": 1,
            "distinct_agent_count": 1,
            "first_consumed_at": "2026-07-30T14:00:00+00:00",
            "last_consumed_at": "2026-07-30T14:00:00+00:00",
            "roles": ["report"],
        }
    }


def test_batch_append_uses_one_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "consumption.jsonl"
    lock_calls: list[tuple[Path, int]] = []

    @contextmanager
    def record_lock(path: Path, flags: int) -> Iterator[None]:
        lock_calls.append((path, flags))
        yield

    monkeypatch.setattr(artifact_consumption, "locked_file", record_lock)

    append_artifact_consumption_events(
        (
            _event("event-a", "file:default:abc"),
            _event("event-b", "plans:202607/report.md"),
        ),
        log_path=log_path,
    )

    assert len(lock_calls) == 1
    assert lock_calls[0][0] == tmp_path / "consumption.lock"
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2


def _event(event_id: str, reference: str) -> ArtifactConsumptionEvent:
    return ArtifactConsumptionEvent(
        id=event_id,
        timestamp="2026-07-30T14:00:00+00:00",
        ref=reference,
        ref_kind="file" if reference.startswith("file:") else "plans",
        fragment=None,
        role="report",
        artifact_id=(
            reference.removeprefix("file:") if reference.startswith("file:") else None
        ),
        resolved_path="/tmp/report.md",
        resolution_status="exact",
        agent_name="agent-a",
        agent_source="SASE_AGENT_NAME",
        artifacts_dir="/artifacts",
        project=None,
    )
