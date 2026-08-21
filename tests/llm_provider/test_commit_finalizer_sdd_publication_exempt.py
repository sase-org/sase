"""Coverage for the discarded-work guard's shared machine-wide clone exemption.

A machine-wide clone this agent does not exclusively own — machine-managed
store state (``kind == "sdd"``) or a repo merely opened via ``/sase_repo``
(``kind == "external"``) — can go clean with no locally-attributed commit for
reasons that have nothing to do with this agent discarding anything: a
managed sync rebase absorbed the content into a commit some other agent
already published, the commit is queued for a push that has not landed yet,
or a concurrent agent committed it first. Those transitions are races or
published state, not discards.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState

from ._commit_finalizer_sibling_helpers import init_git_repo


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _current_branch(repo: Path) -> str:
    return _run_git(repo, "branch", "--show-current").strip()


def _init_repo_with_upstream(base: Path, name: str) -> Path:
    origin = base / f"{name}-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    repo = base / name
    init_git_repo(repo)
    _run_git(repo, "remote", "add", "origin", str(origin))
    branch = _current_branch(repo)
    _run_git(repo, "push", "-u", "origin", branch)
    return repo


def _push_foreign_commit(repo: Path, tmp_path: Path) -> None:
    """Simulate another agent publishing a commit to *repo*'s origin."""
    origin = _run_git(repo, "remote", "get-url", "origin").strip()
    branch = _current_branch(repo)
    clone = tmp_path / f"foreign-clone-{repo.name}"
    subprocess.run(["git", "clone", "-q", origin, str(clone)], check=True)
    subprocess.run(
        ["git", "config", "user.name", "Foreign Agent"], cwd=clone, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "foreign@example.invalid"],
        cwd=clone,
        check=True,
    )
    (clone / "foreign.txt").write_text("foreign\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "foreign commit"], cwd=clone, check=True
    )
    subprocess.run(["git", "push", "-q", "origin", branch], cwd=clone, check=True)


def _dirty_state(
    repo: Path,
    changed_files: tuple[str, ...],
    *,
    kind: Literal["main", "sibling", "external", "sdd"] = "sdd",
) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name="research",
                path=finalizer_git.normalize_path(str(repo)),
                changed_files=changed_files,
                kind=kind,
            ),
        ),
        details="",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(),
        details="",
    )


def test_sync_rebase_absorbed_sdd_state_is_not_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo_with_upstream(tmp_path, "research")
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _push_foreign_commit(repo, tmp_path)
    branch = _current_branch(repo)
    _run_git(repo, "fetch", "-q", "origin")
    _run_git(repo, "reset", "-q", "--hard", f"origin/{branch}")

    assert _run_git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip() == "0"
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()


def test_sdd_state_ahead_of_upstream_is_pending_publication_not_a_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo_with_upstream(tmp_path, "research")
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    # A local, unattributed commit that is never pushed: the clone is left
    # ahead of its upstream. That is a queued/deferred push, a different
    # condition from the work being destroyed, so the guard exempts it and
    # leaves honest reporting of the unpublished state to the dedicated
    # unpublished-bead-state check.
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "local unattributed commit")

    assert _run_git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip() == "1"
    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()


def test_sdd_state_without_upstream_and_foreign_agent_is_a_race_not_a_discard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "research"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _run_git(repo, "add", "-A")
    _run_git(
        repo, "commit", "-q", "-m", "commit dirty payload\n\nSASE_AGENT=other-agent"
    )

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()


def test_external_kind_sync_absorbed_state_is_not_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption now also covers ``kind == "external"`` opened repos."""
    repo = _init_repo_with_upstream(tmp_path, "widget")
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",), kind="external")
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _push_foreign_commit(repo, tmp_path)
    branch = _current_branch(repo)
    _run_git(repo, "fetch", "-q", "origin")
    _run_git(repo, "reset", "-q", "--hard", f"origin/{branch}")

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert evidence == ()
