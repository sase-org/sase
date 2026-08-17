"""Tests for commit_epic_graph_checkpoint in sase.bead.sync."""

from __future__ import annotations

import subprocess

import pytest

from sase.bead.sync import bead_state_is_clean, commit_epic_graph_checkpoint
from sase.core.agent_identity_facade import AgentOwnerIdentity

from .sync_test_helpers import configure_git_identity, init_git_repo


def test_commit_epic_graph_checkpoint_commits_bead_state(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert message.stdout.strip() == (
        "chore(beads): checkpoint approved epic graph sase-1\n\nSASE_TYPE=beads"
    )
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert files.stdout.strip().splitlines() == [
        "sdd/beads/events/streams/sase-1.jsonl",
        "sdd/beads/issues.jsonl",
    ]


def test_commit_epic_graph_checkpoint_noops_outside_git(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')

    assert commit_epic_graph_checkpoint(beads_dir, "sase-1") is False


def test_commit_epic_graph_checkpoint_noops_when_bead_state_has_no_change(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(["git", "add", "sdd/beads/issues.jsonl"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add jsonl"], cwd=tmp_path, check=True)

    assert commit_epic_graph_checkpoint(beads_dir, "sase-1") is False
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert subject.stdout.strip() == "add jsonl"


def test_commit_epic_graph_checkpoint_leaves_unrelated_staged_files_staged(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    other = tmp_path / "notes.txt"
    jsonl.write_text('{"id":"initial"}\n')
    other.write_text("initial\n")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl", "notes.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "initial files"], cwd=tmp_path, check=True)

    jsonl.write_text('{"id":"changed"}\n')
    other.write_text("changed\n")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert files.stdout.strip() == "sdd/beads/issues.jsonl"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout.strip() == "notes.txt"


def test_commit_epic_graph_checkpoint_records_event_stream_deletion(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"sase-1"}\n')
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial bead state"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    stream.unlink()
    jsonl.write_text('{"id":"sase-1","updated":true}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    name_status = subprocess.run(
        ["git", "show", "--name-status", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "D\tsdd/beads/events/streams/sase-1.jsonl" in name_status
    assert "M\tsdd/beads/issues.jsonl" in name_status


def test_commit_epic_graph_checkpoint_picks_up_new_nested_subdirectory_files(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"sase-2"}\n')
    nested = beads_dir / "events/streams/sase-2.jsonl"
    nested.parent.mkdir(parents=True)
    nested.write_text('{"event_id":"sase-2:000001"}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-2")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/events/streams/sase-2.jsonl" in files


def test_commit_epic_graph_checkpoint_commits_staged_only_bead_state(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True, check=True
    )

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    assert bead_state_is_clean(beads_dir) is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/issues.jsonl" in files


def test_commit_epic_graph_checkpoint_on_unborn_head_does_not_raise(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    configure_git_identity(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True, check=True
    )

    assert bead_state_is_clean(beads_dir) is False

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/issues.jsonl" in files


def test_commit_epic_graph_checkpoint_stamps_agent_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-alpha")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "machine_a"),
    )
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert message == (
        "chore(beads): checkpoint approved epic graph sase-1\n\n"
        "SASE_TYPE=beads\nSASE_AGENT=alice.machine_a.agent-alpha"
    )


def test_commit_epic_graph_checkpoint_omits_agent_without_identity(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (
        message
        == "chore(beads): checkpoint approved epic graph sase-1\n\nSASE_TYPE=beads"
    )
