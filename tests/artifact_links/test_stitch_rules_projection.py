"""Coverage tests for the `stitch-bead`/`stitch-agent` projection rules."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess

import pytest

from sase.artifact_links.projection._model import ProjectionInputs
from sase.artifact_links.projection._stitch_rules import project_stitch_rules
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests._conftest_environment import redirect_sase_home

_REPO_NAME = "sase"


def _git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.com")


def _commit(repo: Path, message: str, *, when: str, filename: str = "a.txt") -> str:
    (repo / filename).write_text(f"{message}\n{when}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        message,
        env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when},
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _inputs(
    repo: Path | None, project_key: str = "gh_sase-org__sase"
) -> ProjectionInputs:
    return ProjectionInputs(
        project_key=project_key,
        primary_repo_root=repo,
        primary_repo_name=_REPO_NAME if repo is not None else None,
        agents_sidecar_root=None,
    )


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")


@pytest.fixture(autouse=True)
def _fixed_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = AgentOwnerIdentity(username="alice", machine_name="athena")
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda cls: cls(owner, ())),
    )


def test_emits_both_bead_and_agent_rows_from_one_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    sha = _commit(
        repo,
        "feat: work\n\nSASE_BEAD=sase-xx\nSASE_AGENT=someagent",
        when="2026-08-20T00:00:00+00:00",
    )

    edges = project_stitch_rules(_inputs(repo))

    by_relation = {edge.relation: edge for edge in edges}
    assert by_relation["implements"].source_ref == f"stitch:sase@{sha}"
    assert by_relation["implements"].target_ref == "bead:sase-xx"
    assert by_relation["produced-by"].source_ref == f"stitch:sase@{sha}"
    assert by_relation["produced-by"].target_ref == "agent:alice.athena.someagent"
    assert by_relation["implements"].created_at == "2026-08-20T00:00:00Z"


def test_legacy_agent_spelling_is_also_recognized(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(
        repo,
        "feat: legacy\n\nAGENT=legacyagent",
        when="2026-08-20T00:00:00+00:00",
    )

    edges = project_stitch_rules(_inputs(repo))

    assert any(
        edge.relation == "produced-by"
        and edge.target_ref == "agent:alice.athena.legacyagent"
        for edge in edges
    )


def test_a_commit_with_no_trailers_contributes_nothing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(repo, "chore: untagged commit", when="2026-08-20T00:00:00+00:00")

    assert project_stitch_rules(_inputs(repo)) == ()


def test_no_primary_repo_is_a_no_op() -> None:
    assert project_stitch_rules(_inputs(None)) == ()


def test_idempotent_across_two_warm_runs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(
        repo,
        "feat: work\n\nSASE_BEAD=sase-xx",
        when="2026-08-20T00:00:00+00:00",
    )

    first = project_stitch_rules(_inputs(repo))
    second = project_stitch_rules(_inputs(repo))

    assert first == second


def test_incremental_walk_adds_only_the_new_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(
        repo,
        "feat: first\n\nSASE_BEAD=sase-aa",
        when="2026-08-20T00:00:00+00:00",
    )
    first = project_stitch_rules(_inputs(repo))
    assert len(first) == 1

    _commit(
        repo,
        "feat: second\n\nSASE_BEAD=sase-bb",
        when="2026-08-21T00:00:00+00:00",
    )
    second = project_stitch_rules(_inputs(repo))

    targets = {edge.target_ref for edge in second if edge.relation == "implements"}
    assert targets == {"bead:sase-aa", "bead:sase-bb"}


def test_unreachable_cached_sha_falls_back_to_a_full_walk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(
        repo,
        "feat: first\n\nSASE_BEAD=sase-aa",
        when="2026-08-20T00:00:00+00:00",
    )
    project_stitch_rules(_inputs(repo))

    # Rewrite history: the cached HEAD sha becomes unreachable.
    _git(repo, "commit", "--amend", "-q", "-m", "feat: first (amended)")
    _commit(
        repo,
        "feat: second\n\nSASE_BEAD=sase-bb",
        when="2026-08-21T00:00:00+00:00",
    )

    edges = project_stitch_rules(_inputs(repo))

    targets = {edge.target_ref for edge in edges if edge.relation == "implements"}
    assert targets == {"bead:sase-bb"}


def test_a_git_log_failure_degrades_to_the_cached_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _commit(
        repo,
        "feat: first\n\nSASE_BEAD=sase-aa",
        when="2026-08-20T00:00:00+00:00",
    )
    cached = project_stitch_rules(_inputs(repo))
    assert cached

    _commit(
        repo,
        "feat: second\n\nSASE_BEAD=sase-bb",
        when="2026-08-21T00:00:00+00:00",
    )

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated git failure")

    monkeypatch.setattr("sase.artifact_links.projection._stitch_rules.run_git", _boom)

    degraded = project_stitch_rules(_inputs(repo))

    assert degraded == cached
