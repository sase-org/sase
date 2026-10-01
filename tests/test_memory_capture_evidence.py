"""As-seen evidence: blob OIDs, read-log v3, and launch snapshot fields."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sase.agent.identity import AgentIdentity
from sase.axe.launch_evidence import (
    capture_instruction_snapshot,
    capture_launch_evidence,
    capture_workspace_head,
)
from sase.memory.blob_oid import git_blob_oid
from sase.memory.read_log import (
    append_memory_read_event,
    build_memory_read_batch_event,
    build_memory_read_event,
    read_memory_content,
    read_memory_read_events,
    validate_memory_read_path,
)


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _long_note(body: str = "# Foo\n") -> str:
    return f"---\ntype: reference\nparent: AGENTS.md\ndescription: Foo.\n---\n{body}"


def test_git_blob_oid_matches_hash_object(tmp_path: Path) -> None:
    data = b"# Hello\n\nSome body.\n"
    (tmp_path / "data.md").write_bytes(data)

    expected = subprocess.run(
        ["git", "hash-object", str(tmp_path / "data.md")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert git_blob_oid(data) == expected


def test_single_read_event_records_blob_oid(tmp_path: Path) -> None:
    _write(tmp_path / "sase" / "memory" / "foo.md", _long_note())
    validated = validate_memory_read_path("foo.md", project_root=tmp_path)
    content = read_memory_content(validated)
    event = build_memory_read_event(
        content,
        reason="Need foo",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-oid",
    )

    assert event.blob_oid == git_blob_oid(content.raw_text.encode("utf-8"))

    log_path = tmp_path / "reads.jsonl"
    append_memory_read_event(event, log_path=log_path)
    (round_tripped,) = read_memory_read_events(log_path=log_path)
    assert round_tripped == event
    assert round_tripped.blob_oid == event.blob_oid


def test_read_log_accepts_v1_v2_and_v3(tmp_path: Path) -> None:
    log_path = tmp_path / "reads.jsonl"
    base = {
        "id": "read-x",
        "timestamp": "2026-05-23T12:00:00+00:00",
        "project": "proj",
        "cwd": "/tmp/demo",
        "canonical_path": "foo.md",
        "resolved_path": "/tmp/demo/memory/foo.md",
        "agent_name": "agent-a",
        "agent_source": "SASE_AGENT_NAME",
        "artifacts_dir": None,
        "reason": "Need foo",
        "byte_count": 42,
        "frontmatter_stripped": False,
    }
    v1 = {"schema_version": 1, **base, "id": "v1"}
    v2 = {"schema_version": 2, **base, "id": "v2"}
    v3 = {
        "schema_version": 3,
        **base,
        "id": "v3",
        "blob_oid": "abc123",
        "included_blob_oids": [["foo.md", "abc123"]],
    }
    log_path.write_text(
        "\n".join(json.dumps(row) for row in (v1, v2, v3)) + "\n", encoding="utf-8"
    )

    events = read_memory_read_events(log_path=log_path)

    assert [event.id for event in events] == ["v1", "v2", "v3"]
    assert events[0].blob_oid is None
    assert events[0].included_blob_oids == ()
    assert events[1].blob_oid is None
    assert events[2].blob_oid == "abc123"
    assert events[2].included_blob_oids == (("foo.md", "abc123"),)


def test_batch_event_records_included_blob_oids(tmp_path: Path) -> None:
    event = build_memory_read_batch_event(
        kind="strand",
        selectors=["glossary:stitch"],
        resolved_targets=["glossary:stitch"],
        byte_count=10,
        frontmatter_stripped=False,
        reason="Need stitch",
        agent=AgentIdentity("agent-a", "SASE_AGENT_NAME", None),
        project="proj",
        cwd=tmp_path,
        now=datetime(2026, 5, 23, 12, 0, tzinfo=UTC),
        read_id="read-batch-oid",
        included_blob_oids={"glossary:stitch": "deadbeef"},
    )
    log_path = tmp_path / "batch.jsonl"
    append_memory_read_event(event, log_path=log_path)

    (round_tripped,) = read_memory_read_events(log_path=log_path)
    assert round_tripped == event
    assert round_tripped.included_blob_oids == (("glossary:stitch", "deadbeef"),)


def test_launch_evidence_records_head_and_snapshot(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "config", "commit.gpgsign", "false")
    agents = workspace / "AGENTS.md"
    agents.write_text("# Agents\n", encoding="utf-8")
    _git(workspace, "add", "AGENTS.md")
    _git(workspace, "commit", "-m", "init", "--no-gpg-sign")

    head = capture_workspace_head(workspace)
    expected_head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert head == expected_head

    agent_meta: dict[str, object] = {}
    capture_launch_evidence(workspace, agent_meta)
    assert agent_meta["workspace_head"] == expected_head
    snapshot = agent_meta["instruction_snapshot"]
    assert isinstance(snapshot, list) and snapshot
    entry = next(
        item for item in snapshot if item["path"] == str(workspace / "AGENTS.md")
    )
    assert entry["repo"] == "project"
    assert entry["tracked"] is True
    assert entry["blob_oid"] == git_blob_oid(agents.read_bytes())
