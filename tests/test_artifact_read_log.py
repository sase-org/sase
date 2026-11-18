from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from sase.agent.identity import AgentIdentity
from sase.artifact_read_log import (
    ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION,
    ARTIFACT_READ_LOG_SCHEMA_VERSION,
    ArtifactReadAuditRow,
    ArtifactReadError,
    ArtifactReadEvent,
    append_artifact_read_event,
    artifact_read_log_path,
    build_artifact_read_event,
    query_artifact_read_events,
    read_artifact_read_events,
)
from tests._conftest_environment import redirect_sase_home


def _event(**overrides: object) -> ArtifactReadEvent:
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


def test_read_skips_non_integer_and_wrong_schema_versions(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    valid = _event()
    rows = [asdict(valid)]
    for schema_version in (True, 1.0, 2):
        invalid = asdict(valid)
        invalid["schema_version"] = schema_version
        rows.append(invalid)
    log_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    assert read_artifact_read_events(log_path=log_path) == (valid,)


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


@pytest.mark.parametrize("project", ["../evil", "/tmp/pwn", "..", ".hidden"])
def test_artifact_read_log_path_rejects_traversal_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with pytest.raises(ValueError, match="invalid SASE project name"):
        artifact_read_log_path(project)
    event = _event(project=project)
    with pytest.raises(ValueError, match="invalid SASE project name"):
        append_artifact_read_event(event)
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "pwn").exists()


def test_resolved_path_round_trips(tmp_path: Path) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    event = _event(resolved_path=tmp_path / "materialized.md")
    assert event.resolved_path == str(tmp_path / "materialized.md")
    append_artifact_read_event(event, log_path=log_path)
    assert read_artifact_read_events(log_path=log_path) == (event,)


def test_legacy_rows_without_resolved_path_still_parse(tmp_path: Path) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    payload = {
        "schema_version": ARTIFACT_READ_LOG_SCHEMA_VERSION,
        "id": "legacy-1",
        "timestamp": "2026-08-20T12:00:00+00:00",
        "project": "gh_sase-org__sase",
        "cwd": "/work",
        "ref": "plan:doc.md",
        "reason": "need the design of record",
        "agent_name": "alice.athena.worker",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": "/artifacts",
        "recorded_link": False,
    }
    log_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    logged = read_artifact_read_events(log_path=log_path)
    assert len(logged) == 1
    assert logged[0].ref == "plan:doc.md"
    assert logged[0].resolved_path is None


def test_null_and_empty_resolved_path_parse_as_none(tmp_path: Path) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    rows = [
        {
            "schema_version": ARTIFACT_READ_LOG_SCHEMA_VERSION,
            "id": "null-path",
            "timestamp": "2026-08-20T12:00:00+00:00",
            "project": "gh_sase-org__sase",
            "cwd": "/work",
            "ref": "plan:null.md",
            "reason": "null path",
            "agent_name": "alice",
            "agent_source": "interactive",
            "artifacts_dir": None,
            "recorded_link": False,
            "resolved_path": None,
        },
        {
            "schema_version": ARTIFACT_READ_LOG_SCHEMA_VERSION,
            "id": "empty-path",
            "timestamp": "2026-08-20T12:01:00+00:00",
            "project": "gh_sase-org__sase",
            "cwd": "/work",
            "ref": "plan:empty.md",
            "reason": "empty path",
            "agent_name": "alice",
            "agent_source": "interactive",
            "artifacts_dir": None,
            "recorded_link": False,
            "resolved_path": "  ",
        },
    ]
    log_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    logged = read_artifact_read_events(log_path=log_path)
    assert [event.resolved_path for event in logged] == [None, None]


def test_invalid_resolved_path_type_is_skipped(tmp_path: Path) -> None:
    log_path = tmp_path / "artifact_reads.jsonl"
    valid = _event()
    append_artifact_read_event(valid, log_path=log_path)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": ARTIFACT_READ_LOG_SCHEMA_VERSION,
                    "id": "bad-path",
                    "timestamp": "2026-08-20T12:00:00+00:00",
                    "project": "gh_sase-org__sase",
                    "cwd": "/work",
                    "ref": "plan:bad.md",
                    "reason": "bad type",
                    "agent_name": "alice",
                    "agent_source": "interactive",
                    "artifacts_dir": None,
                    "recorded_link": False,
                    "resolved_path": 123,
                }
            )
            + "\n"
        )
    assert read_artifact_read_events(log_path=log_path) == (valid,)


def test_targeted_query_decodes_rows_and_returns_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = _event(resolved_path="/work/materialized.md")
    calls: list[tuple[str, str, dict[str, object]]] = []

    def require_binding(name: str):
        if name == "artifact_read_audit_query_wire_schema_version":
            return lambda: ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION
        assert name == "artifact_read_audit_query"

        def run(path: str, query: dict[str, object]):
            calls.append((name, path, query))
            return {
                "rows": [{"event": asdict(event), "member_index": 0}],
                "source": {
                    "missing": False,
                    "size": 123,
                    "mtime_ns": 456,
                    "dev": 7,
                    "ino": 8,
                },
            }

        return run

    monkeypatch.setattr("sase.core.rust.require_rust_binding", require_binding)
    log_path = tmp_path / "artifact_reads.jsonl"
    rows, source = query_artifact_read_events(
        log_path,
        members=[{"artifacts_dir": "/runs/a", "agent_name": "alice"}],
        limit=50,
        deduplicate=True,
    )

    assert rows == [ArtifactReadAuditRow(event=event, member_index=0)]
    assert source.missing is False
    assert (source.size, source.mtime_ns, source.dev, source.ino) == (
        123,
        456,
        7,
        8,
    )
    assert calls == [
        (
            "artifact_read_audit_query",
            str(log_path),
            {
                "members": [{"artifacts_dir": "/runs/a", "agent_name": "alice"}],
                "limit": 50,
                "deduplicate": True,
            },
        )
    ]


def test_targeted_query_rejects_out_of_range_member_ordinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def require_binding(name: str):
        if name == "artifact_read_audit_query_wire_schema_version":
            return lambda: ARTIFACT_READ_AUDIT_QUERY_WIRE_SCHEMA_VERSION
        assert name == "artifact_read_audit_query"
        return lambda _path, _query: {
            "rows": [{"event": asdict(_event()), "member_index": 1}],
            "source": {
                "missing": False,
                "size": 1,
                "mtime_ns": 1,
                "dev": 1,
                "ino": 1,
            },
        }

    monkeypatch.setattr("sase.core.rust.require_rust_binding", require_binding)
    with pytest.raises(RuntimeError, match="member_index out of range"):
        query_artifact_read_events(
            tmp_path / "artifact_reads.jsonl",
            members=[{"artifacts_dir": "/runs/a", "agent_name": "alice"}],
        )
