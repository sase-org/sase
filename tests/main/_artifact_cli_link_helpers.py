"""Shared helpers for the split artifact-link CLI tests.

The tests formerly lived in a single ``test_artifact_cli_link`` module.
Helpers needed by more than one split module live here under public names;
the ``test_artifact_cli_link_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home

__all__ = [
    "make_store",
    "patch_link_ops_store",
]


def _init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)


def make_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_git(plans)
    _init_git(research)
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )


def patch_link_ops_store(
    monkeypatch: pytest.MonkeyPatch, store: ArtifactLinkStore
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-08-18T23:40:00Z",
    )
