"""Dirty-path behavior for the commit-finalizer baseline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
    capture_dirty_baseline,
)
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_baseline_helpers import (
    PRE_EXISTING_HEADER,
    dirty_details,
    init_git_repo_with_identity,
    use_git_dirty_details,
)
from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    set_agent_env,
    set_clean_main,
)


def test_pre_existing_main_file_is_excluded_and_reported_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    pre_existing = repo / "pre_existing.txt"
    pre_existing.write_text("foreign\n", encoding="utf-8")

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    mine = repo / "mine.txt"
    mine.write_text("agent work\n", encoding="utf-8")

    details = dirty_details(repo, artifacts_dir)
    assert PRE_EXISTING_HEADER in details
    must_commit_section, _, pre_existing_section = details.partition(
        PRE_EXISTING_HEADER
    )
    assert "mine.txt" in must_commit_section
    assert "pre_existing.txt" not in must_commit_section
    assert "pre_existing.txt" in pre_existing_section
    assert pre_existing.read_text(encoding="utf-8") == "foreign\n"
    assert not (artifacts_dir / BASELINE_FILENAME).exists()


def test_baseline_dirty_file_edited_again_stays_in_must_commit_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    shared = repo / "shared.txt"
    shared.write_text("foreign v1\n", encoding="utf-8")

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    # The agent edits the same path that was already dirty at baseline; the
    # status code (untracked) is unchanged but the content is not.
    shared.write_text("agent v2\n", encoding="utf-8")

    details = dirty_details(repo, artifacts_dir)
    assert "shared.txt" in details
    assert PRE_EXISTING_HEADER not in details


def test_clean_baseline_does_not_affect_files_dirtied_after_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))  # nothing dirty yet

    mine = repo / "mine.txt"
    mine.write_text("agent work\n", encoding="utf-8")

    details = dirty_details(repo, artifacts_dir)
    assert "mine.txt" in details
    assert PRE_EXISTING_HEADER not in details


def test_continuation_run_finalizer_commits_inherited_starters_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end regression coverage for the bug plan
    202608/lane_baseline_inheritance.md fixes: a lane's baseline is captured
    once, before the lane's first (starter) agent runs. A continuation run
    that inherits that same baseline file — rather than capturing a fresh one
    against the now-dirty workspace — must still list the starter's
    uncommitted work in the must-commit set, not under the pre-existing
    header, even though that work did not exist yet when the baseline was
    captured.
    """
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    artifacts_dir = tmp_path / "artifacts"
    # Captured once, at lane start, before the starter agent has done any work.
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    # The starter agent does work and is interrupted (e.g. SIGTERMed for a
    # monitor handoff) before its own finalizer ever runs.
    starter_work = repo / "starter_work.txt"
    starter_work.write_text("starter's uncommitted work\n", encoding="utf-8")

    details = dirty_details(repo, artifacts_dir)
    assert "starter_work.txt" in details
    assert PRE_EXISTING_HEADER not in details


def test_missing_baseline_file_behaves_like_no_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    (repo / "mine.txt").write_text("agent work\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"  # capture_dirty_baseline never called

    details = dirty_details(repo, artifacts_dir)
    assert PRE_EXISTING_HEADER not in details


def test_corrupt_baseline_file_degrades_to_no_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)

    (repo / "mine.txt").write_text("agent work\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / BASELINE_FILENAME).write_text("not json{{{", encoding="utf-8")

    details = dirty_details(repo, artifacts_dir)
    assert PRE_EXISTING_HEADER not in details


def test_pre_existing_sibling_file_is_excluded_and_reported_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps([{"name": "core", "workspace_dir": str(sibling)}]),
    )
    artifacts_dir = tmp_path / "artifacts"

    foreign_file = sibling / "foreign.txt"
    foreign_file.write_text("foreign\n", encoding="utf-8")
    capture_dirty_baseline(str(main), str(artifacts_dir))

    mine_file = sibling / "mine.txt"
    mine_file.write_text("agent\n", encoding="utf-8")

    details = dirty_details(main, artifacts_dir)
    assert "mine.txt" in details
    assert PRE_EXISTING_HEADER in details
    _, _, pre_existing_section = details.partition(PRE_EXISTING_HEADER)
    assert "foreign.txt" in pre_existing_section
    assert foreign_file.read_text(encoding="utf-8") == "foreign\n"
    foreign_status = subprocess.run(
        ["git", "status", "--porcelain", "foreign.txt"],
        cwd=sibling,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert foreign_status.strip() == "?? foreign.txt"


def test_capture_writes_no_baseline_when_dirty_state_collection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_baseline_repositories",
        boom,
    )
    artifacts_dir = tmp_path / "artifacts"

    capture_dirty_baseline(str(tmp_path), str(artifacts_dir))

    assert not (artifacts_dir / BASELINE_FILENAME).exists()
    assert not (artifacts_dir / FINALIZER_BASELINE_FILENAME).exists()
