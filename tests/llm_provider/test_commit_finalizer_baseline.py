"""Coverage for the commit finalizer's pre-existing dirty-path baseline.

Captured once at runner start (before the agent's first turn), the baseline
lets the finalizer tell paths that were already dirty when the run started
apart from paths this agent's own run touched, instead of telling the agent
its run fails unless it commits changes it did not make (bead sase-lb.1.6).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
    capture_dirty_baseline,
    capture_opened_repo_dirty_baseline,
    load_dirty_baseline,
)
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    split_pre_existing_changed_files,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    set_agent_env,
    set_clean_main,
)

_PRE_EXISTING_HEADER = "Pre-existing changes detected before this run started"


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git_repo_with_identity(repo: Path) -> None:
    init_git_repo(repo)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the "main" repo's changed-file list from real ``git status``.

    The finalizer normally resolves main-repo changes through a VCS-provider
    abstraction; swapping in a direct git-status reader keeps these tests
    focused on baseline exclusion instead of that unrelated machinery.
    """

    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )


def _dirty_details(project_dir: Path, artifacts_dir: Path) -> str:
    return collect_dirty_state(str(project_dir), artifact_root=artifacts_dir).details


def test_pre_existing_main_file_is_excluded_and_reported_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    pre_existing = repo / "pre_existing.txt"
    pre_existing.write_text("foreign\n", encoding="utf-8")

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    mine = repo / "mine.txt"
    mine.write_text("agent work\n", encoding="utf-8")

    details = _dirty_details(repo, artifacts_dir)
    assert _PRE_EXISTING_HEADER in details
    must_commit_section, _, pre_existing_section = details.partition(
        _PRE_EXISTING_HEADER
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
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    shared = repo / "shared.txt"
    shared.write_text("foreign v1\n", encoding="utf-8")

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    # The agent edits the same path that was already dirty at baseline; the
    # status code (untracked) is unchanged but the content is not.
    shared.write_text("agent v2\n", encoding="utf-8")

    details = _dirty_details(repo, artifacts_dir)
    assert "shared.txt" in details
    assert _PRE_EXISTING_HEADER not in details


def test_clean_baseline_does_not_affect_files_dirtied_after_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    artifacts_dir = tmp_path / "artifacts"
    capture_dirty_baseline(str(repo), str(artifacts_dir))  # nothing dirty yet

    mine = repo / "mine.txt"
    mine.write_text("agent work\n", encoding="utf-8")

    details = _dirty_details(repo, artifacts_dir)
    assert "mine.txt" in details
    assert _PRE_EXISTING_HEADER not in details


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
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    artifacts_dir = tmp_path / "artifacts"
    # Captured once, at lane start, before the starter agent has done any work.
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    # The starter agent does work and is interrupted (e.g. SIGTERMed for a
    # monitor handoff) before its own finalizer ever runs.
    starter_work = repo / "starter_work.txt"
    starter_work.write_text("starter's uncommitted work\n", encoding="utf-8")

    details = _dirty_details(repo, artifacts_dir)
    assert "starter_work.txt" in details
    assert _PRE_EXISTING_HEADER not in details


def test_missing_baseline_file_behaves_like_no_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    (repo / "mine.txt").write_text("agent work\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"  # capture_dirty_baseline never called

    details = _dirty_details(repo, artifacts_dir)
    assert _PRE_EXISTING_HEADER not in details


def test_corrupt_baseline_file_degrades_to_no_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)

    (repo / "mine.txt").write_text("agent work\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / BASELINE_FILENAME).write_text("not json{{{", encoding="utf-8")

    details = _dirty_details(repo, artifacts_dir)
    assert _PRE_EXISTING_HEADER not in details


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

    details = _dirty_details(main, artifacts_dir)
    assert "mine.txt" in details
    assert _PRE_EXISTING_HEADER in details
    _, _, pre_existing_section = details.partition(_PRE_EXISTING_HEADER)
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
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state", boom
    )
    artifacts_dir = tmp_path / "artifacts"

    capture_dirty_baseline(str(tmp_path), str(artifacts_dir))

    assert not (artifacts_dir / BASELINE_FILENAME).exists()
    assert not (artifacts_dir / FINALIZER_BASELINE_FILENAME).exists()


def test_capture_writes_fingerprints_for_dirty_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    (repo / "dirty.txt").write_text("hello\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"

    capture_dirty_baseline(str(repo), str(artifacts_dir))

    baseline = load_dirty_baseline(artifacts_dir)
    assert baseline is not None
    repo_entries = baseline[finalizer_git.normalize_path(str(repo))]
    xy, content_hash = repo_entries["dirty.txt"]
    assert xy == "??"
    assert content_hash == _run_git(repo, "hash-object", "dirty.txt").strip()
    payload = json.loads(
        (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == 1
    assert payload["repositories"][0]["fingerprints"]["dirty.txt"][0] == "??"
    assert not (artifacts_dir / BASELINE_FILENAME).exists()


def test_late_open_baseline_capture_first_repo_id_wins(tmp_path: Path) -> None:
    repo = tmp_path / "linked"
    _init_git_repo_with_identity(repo)
    (repo / "pre_existing.txt").write_text("foreign\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"

    assert (
        capture_opened_repo_dirty_baseline(
            "linked:core",
            str(repo),
            kind="linked",
            name="core",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )
    (repo / "after_open.txt").write_text("mine\n", encoding="utf-8")
    assert (
        capture_opened_repo_dirty_baseline(
            "linked:core",
            str(repo),
            kind="linked",
            name="core",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )

    payload = json.loads(
        (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["repositories"][0]["path"] == finalizer_git.normalize_path(str(repo))
    assert payload["repositories"][0]["scope"] == "opened_repo"
    assert sorted(payload["repositories"][0]["fingerprints"]) == ["pre_existing.txt"]
    assert load_dirty_baseline(artifacts_dir) == {}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"repo": "not a dict"}',
        '{"repo": {"path": ["only-one"]}}',
        '{"repo": {"path": ["xy", 1]}}',
        '{"repo": {"path": [1, "hash"]}}',
    ],
)
def test_load_dirty_baseline_rejects_malformed_payloads(
    tmp_path: Path, raw: str
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / BASELINE_FILENAME).write_text(raw, encoding="utf-8")

    assert load_dirty_baseline(artifacts_dir) is None


def test_load_dirty_baseline_returns_none_for_missing_root() -> None:
    assert load_dirty_baseline(None) is None


def test_load_dirty_baseline_reads_historical_legacy_file_only(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    repo = "/historical/repo"
    (artifacts_dir / BASELINE_FILENAME).write_text(
        json.dumps({repo: {"file.txt": ["M", "abc123"]}}),
        encoding="utf-8",
    )

    assert load_dirty_baseline(artifacts_dir) == {
        repo: {"file.txt": ("M", "abc123")},
    }


def test_split_pre_existing_changed_files_requires_matching_hash(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "sase_10"
    _init_git_repo_with_identity(repo)
    path = repo / "file.txt"
    path.write_text("v1\n", encoding="utf-8")

    baseline = dirty_path_fingerprints(str(repo))

    path.write_text("v2\n", encoding="utf-8")
    still, pre_existing = split_pre_existing_changed_files(
        str(repo), ["file.txt"], baseline
    )
    assert still == ["file.txt"]
    assert pre_existing == []

    path.write_text("v1\n", encoding="utf-8")
    still, pre_existing = split_pre_existing_changed_files(
        str(repo), ["file.txt"], baseline
    )
    assert still == []
    assert pre_existing == ["file.txt"]
