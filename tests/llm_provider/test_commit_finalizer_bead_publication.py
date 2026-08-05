"""Publication verification for the finalizer's bead-state safety net.

Regression coverage for the failure where a bead mutation committed inside an
ephemeral workspace was reported as done and then destroyed with the clone. The
finalizer's safety net used to commit leftover bead state and stop, so a commit
the configured push policy never published still produced a ``finalized`` run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer import (
    CommitFinalizerError,
    run_commit_finalizer,
)
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV
from tests.sdd_policy_helpers import set_sdd_policy


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _configure_identity(repo: Path) -> None:
    _run_git(repo, "config", "user.name", "SASE Test")
    _run_git(repo, "config", "user.email", "sase-test@example.invalid")


def _create_primary_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _configure_identity(repo)
    (repo / ".gitignore").write_text(".sase/\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")


def _clone_sdd_store(repo: Path, bare: Path) -> Path:
    """Build the repo's external SDD store as a clone with an upstream."""
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    sdd_store = repo / ".sase" / "sdd"
    sdd_store.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", str(bare), str(sdd_store)],
        capture_output=True,
        check=True,
    )
    _configure_identity(sdd_store)
    (sdd_store / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(sdd_store, "add", ".")
    _run_git(sdd_store, "commit", "-q", "-m", "initial sdd")
    _run_git(sdd_store, "push", "-q", "-u", "origin", "HEAD:main")
    return sdd_store


def _write_dirty_bead_state(sdd_store: Path) -> None:
    beads = sdd_store / "beads" / "issues.jsonl"
    beads.parent.mkdir()
    beads.write_text('{"id":"beads-1"}\n', encoding="utf-8")


def _remote_subjects(bare: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )


@pytest.fixture
def published_sdd_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    """A clean primary repo whose external SDD store holds dirty bead state.

    ``push_after_commit`` is disabled, which is how the configured push policy
    behaves for a store whose publication is queued elsewhere: the safety net's
    commit lands locally and nothing publishes it.
    """
    repo = tmp_path / "sase_10"
    bare = tmp_path / "sdd-store.git"
    _create_primary_repo(repo)
    sdd_store = _clone_sdd_store(repo, bare)
    _write_dirty_bead_state(sdd_store)

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260528_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    _use_git_dirty_details(monkeypatch)
    set_sdd_policy(monkeypatch, "separate_repo")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    return repo, sdd_store, bare


def _run_finalizer(provider: MagicMock, artifacts_dir: Path) -> InvokeResult:
    return run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )


def test_finalizer_publishes_the_bead_state_it_commits(
    published_sdd_store: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _repo, _sdd_store, bare = published_sdd_store
    provider = MagicMock()
    artifacts_dir = tmp_path / "artifacts"

    result = _run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert "chore(beads): sync bead state" in _remote_subjects(bare)
    result_json = (artifacts_dir / "commit_finalizer_result.json").read_text(
        encoding="utf-8"
    )
    assert '"status": "finalized"' in result_json
    assert '"reason": "auto_committed_sdd_store"' in result_json


def test_unpublishable_bead_state_fails_instead_of_reporting_finalized(
    published_sdd_store: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    _repo, sdd_store, bare = published_sdd_store
    _run_git(sdd_store, "remote", "set-url", "origin", str(bare.parent / "missing.git"))
    provider = MagicMock()
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(CommitFinalizerError) as excinfo:
        _run_finalizer(provider, artifacts_dir)

    error = str(excinfo.value)
    assert "was committed locally but NOT published" in error
    assert "unpublished bead commit(s): 1" in error
    assert str(sdd_store) in error
    assert f"git -C {sdd_store} push" in error
    result_json = (artifacts_dir / "commit_finalizer_result.json").read_text(
        encoding="utf-8"
    )
    assert '"status": "failed"' in result_json
    assert '"reason": "bead_state_unpublished"' in result_json
    # The commit is preserved locally so it can still be republished.
    assert "chore(beads): sync bead state" in _run_git(
        sdd_store, "log", "-1", "--pretty=%s"
    )


def test_unpublished_bead_state_still_lets_the_agent_commit_its_own_work(
    published_sdd_store: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    """The publication failure is reported after the commit passes, not before."""
    repo, sdd_store, bare = published_sdd_store
    _run_git(sdd_store, "remote", "set-url", "origin", str(bare.parent / "missing.git"))
    (repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    provider = MagicMock()

    def invoke(*_: object, **__: object) -> InvokeResult:
        _run_git(repo, "add", "feature.py")
        _run_git(repo, "commit", "-q", "-m", "feat: commit main work")
        return InvokeResult(content="provider finalized")

    provider.invoke.side_effect = invoke

    with pytest.raises(CommitFinalizerError) as excinfo:
        _run_finalizer(provider, tmp_path / "artifacts")

    assert provider.invoke.call_count == 1
    assert _run_git(repo, "status", "--short") == ""
    assert "was committed locally but NOT published" in str(excinfo.value)


def test_sdd_store_without_an_upstream_stays_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store with no remote to publish to is not a publication failure."""
    repo = tmp_path / "sase_10"
    _create_primary_repo(repo)
    sdd_store = repo / ".sase" / "sdd"
    sdd_store.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=sdd_store, check=True)
    _configure_identity(sdd_store)
    (sdd_store / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(sdd_store, "add", ".")
    _run_git(sdd_store, "commit", "-q", "-m", "initial sdd")
    _write_dirty_bead_state(sdd_store)

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260528_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    _use_git_dirty_details(monkeypatch)
    set_sdd_policy(monkeypatch, "separate_repo")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    artifacts_dir = tmp_path / "artifacts"

    result = _run_finalizer(MagicMock(), artifacts_dir)

    assert result.content == "primary response"
    result_json = (artifacts_dir / "commit_finalizer_result.json").read_text(
        encoding="utf-8"
    )
    assert '"status": "finalized"' in result_json
    assert '"reason": "auto_committed_sdd_store"' in result_json
