"""End-to-end regression for the commit finalizer's discarded-work guard.

Reproduces the two recorded failure clusters against the real guard and real
git, not mocks:

- Cluster A: a resumed commit whose message was rewritten during conflict
  resolution — dropping its ``SASE_*`` provenance footer — is restamped by
  the real ``sase stitch create --resume`` restamp helper and the real
  ``discarded_dirty_work_evidence`` guard then recognizes it as this agent's
  own commit.
- Cluster B: a machine-wide shared clone that goes clean under a concurrent
  agent's commit is classified as a race rather than a discard.
- A genuine discard — dirty files reset with no commit anywhere — still
  fails.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pluggy
import pytest

from sase.llm_provider.commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow_resume import _restamp_missing_footer_tags

from ._commit_finalizer_sibling_helpers import init_git_repo


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _dirty_before(
    repo: Path, changed_files: tuple[str, ...], *, kind: str = "main"
) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=changed_files,
                kind=kind,  # type: ignore[arg-type]
            ),
        ),
        details="",
    )


def _clean_after(repo: Path) -> DirtyState:
    return DirtyState(project_dir=str(repo), repos=(), details="")


def test_resume_restamped_footer_is_attributable_to_the_real_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo(repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "bbugyi200.athena.sase-ai.2")

    tracked = repo / "tracked.txt"
    tracked.write_text("dirty\n", encoding="utf-8")
    before = _dirty_before(repo, ("tracked.txt",))
    fingerprint_before = progress_fingerprint(before)

    # Conflict resolution: the agent re-authors the body to match reality
    # and, along with the stale paragraph, drops the whole SASE_* footer —
    # the subject line survives unchanged.
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "fix: bug\n\nUpdated to match upstream reality.",
    )

    checkpoint_message = (
        "fix: bug\n\n"
        "SASE_BEAD=sase-ai.2\n"
        "SASE_TYPE=stitch\n"
        "SASE_AGENT=bbugyi200.athena.sase-ai.2"
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": checkpoint_message},
        cwd=str(repo),
    )
    provider = _make_git_provider()

    restamp_failure = _restamp_missing_footer_tags(provider, cp, "git")

    assert restamp_failure is None
    head_message = _run_git(repo, "log", "-1", "--format=%B").strip()
    assert "SASE_AGENT=bbugyi200.athena.sase-ai.2" in head_message
    assert "SASE_BEAD=sase-ai.2" in head_message
    assert "Updated to match upstream reality." in head_message

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_after(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()


def test_shared_clone_race_under_a_concurrent_agent_is_not_a_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    init_git_repo(repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    tracked = repo / "tracked.txt"
    tracked.write_text("dirty\n", encoding="utf-8")
    before = _dirty_before(repo, ("tracked.txt",), kind="external")
    fingerprint_before = progress_fingerprint(before)

    # A concurrent agent commits into the same machine-wide clone before
    # this agent's own finalizer pass re-checks it.
    _run_git(repo, "add", "-A")
    _run_git(
        repo,
        "commit",
        "-q",
        "-m",
        "commit dirty file\n\nSASE_AGENT=other-agent",
    )

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_after(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()


def test_genuine_discard_with_no_commit_anywhere_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo(repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    before = _dirty_before(repo, ("tracked.txt",))
    fingerprint_before = progress_fingerprint(before)

    # The agent resets its own uncommitted work instead of committing it.
    _run_git(repo, "checkout", "--", ".")

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_after(repo),
        fingerprint_before=fingerprint_before,
    )

    assert len(evidence) == 1
    assert evidence[0].reason == "head_not_advanced"
    assert evidence[0].repo_name == "main"
