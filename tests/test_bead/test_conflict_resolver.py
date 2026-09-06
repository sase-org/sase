"""Tests for bead conflict resolver command behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.bead import conflict_resolver_git
from sase.bead.conflict_resolver import _git_add, resolve_bead_conflicts
from sase.bead.project import BEADS_DIRNAME

from .conflict_resolver_test_helpers import (
    _assert_config_roundtrips_save_config,
    _build_stream_conflict,
    _git,
    _init_repo,
)


def test_resolve_bead_conflicts_noops_without_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True
    assert result.message == "no conflicted bead files"


def test_git_add_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("resolved\n", encoding="utf-8")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    _git_add(tmp_path, ["note.txt"])

    assert not lock.exists()
    assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.strip() == (
        "note.txt"
    )


def test_resolve_bead_conflicts_rejects_nonmergeable_bead_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"owner":"base"}\n', encoding="utf-8")
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text('{"owner":"other"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text('{"owner":"local"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_config_counter_and_owner_divergence_is_unsupported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"issue_prefix":"beads","next_counter":1,"owner":"base"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text(
        '{"issue_prefix":"beads","next_counter":3,"owner":"other"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text(
        '{"issue_prefix":"beads","next_counter":2,"owner":"local"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_malformed_config_json_stage_is_unsupported(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"issue_prefix":"beads","next_counter":1,"owner":""}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text("{not json", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text(
        '{"issue_prefix":"beads","next_counter":2,"owner":""}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_next_counter_only_config_conflict_merges_to_max(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"issue_prefix":"beads","next_counter":10,"owner":""}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text(
        '{"issue_prefix":"beads","next_counter":12,"owner":""}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text(
        '{"issue_prefix":"beads","next_counter":11,"owner":""}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True, result.message
    assert result.resolved_files.count("sdd/beads/config.json") == 1
    merged = json.loads(config.read_text(encoding="utf-8"))
    assert merged["next_counter"] == 12
    assert merged["issue_prefix"] == "beads"
    assert merged["owner"] == ""
    assert _git(tmp_path, "diff", "--name-only", "--diff-filter=U").stdout == ""
    _assert_config_roundtrips_save_config(tmp_path / "sdd/beads", tmp_path)


def test_resolve_bead_conflicts_rejects_only_non_bead_conflicts(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "sdd/beads").mkdir(parents=True)
    notes = tmp_path / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.txt")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    notes.write_text("other\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    notes.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: notes.txt"


def test_failed_conflict_probe_is_not_reported_as_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    real_run_git = conflict_resolver_git._run_git

    def fail_conflict_probe(
        cwd: Path, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["diff"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="fatal: Unable to create '.git/index.lock': File exists.",
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver_git, "_run_git", fail_conflict_probe)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert "could not list conflicted bead files" in result.message
    assert result.resolved_files == ()


def test_conflict_probe_retries_through_a_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probes contend on index.lock, so they use the shared retry policy."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert contested in result.resolved_files
    assert not lock.exists()
