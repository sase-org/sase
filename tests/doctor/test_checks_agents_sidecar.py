"""Tests for the bounded agents-sidecar dirt doctor check."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import sase_core_rs

from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.doctor.checks_agents_sidecar import _check_agents_sidecar_dirt
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path / ".sase")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _target(repo: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="alpha",
        project="Alpha",
        primary_checkout=repo,
        primary_roots=(repo,),
        sidecar_path=repo,
        remote_url="https://example.test/alpha--agents.git",
    )


def _init_clone(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase-test@example.com")
    _git(repo, "config", "user.name", "SASE Test")
    (repo / "README.md").write_text("# agents\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")


def _selection(target: ProjectTarget) -> TargetSelection:
    return TargetSelection(targets=(target,))


def test_agents_sidecar_dirt_is_ok_when_clean(tmp_path: Path, monkeypatch) -> None:
    clone = tmp_path / "agents"
    _init_clone(clone)
    monkeypatch.setattr(
        "sase.doctor.checks_agents_sidecar.resolve_sync_targets",
        lambda **_kwargs: _selection(_target(clone)),
    )

    check = _check_agents_sidecar_dirt(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["checked_clones"] == 1


def test_agents_sidecar_dirt_classifies_pending_objects_and_unexpected_paths(
    tmp_path: Path, monkeypatch
) -> None:
    clone = tmp_path / "agents"
    _init_clone(clone)
    payload = b"pending archive object"
    digest = hashlib.sha256(payload).hexdigest()
    object_path = clone / sase_core_rs.artifact_object_relpath(digest)
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(payload)
    (clone / "unexpected.txt").write_text("dirt\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.doctor.checks_agents_sidecar.resolve_sync_targets",
        lambda **_kwargs: _selection(_target(clone)),
    )

    check = _check_agents_sidecar_dirt(_context(tmp_path))

    assert check.status == "WARN"
    assert check.data["pending_object_count"] == 1
    assert check.data["unexpected_dirt_count"] == 1
    assert any("sase agent sync -p Alpha" in step for step in check.next_steps)
    assert any("unexpected dirt" in detail for detail in check.details)
