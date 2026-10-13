"""Capture and late-open behavior for commit-finalizer baselines."""

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
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    split_pre_existing_changed_files,
)
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore

from ._commit_finalizer_baseline_helpers import (
    PRE_EXISTING_HEADER,
    dirty_details,
    finalizer_baseline_record,
    init_git_repo_with_identity,
    is_protected,
    use_git_dirty_details,
    write_finalizer_baseline_records,
)
from ._commit_finalizer_sibling_helpers import set_agent_env


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _sidecar_store(plans: Path, **sidecars: Path) -> SddStore:
    return SddStore(
        storage=SDD_STORAGE_SIDECAR_REPOS,
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs=sidecars,
    )


def test_capture_records_head_for_run_start_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"

    capture_dirty_baseline(str(repo), str(artifacts_dir))

    expected_head = _run_git(repo, "rev-parse", "HEAD").strip()
    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    assert len(records) == 1
    assert records[0].head == expected_head


def test_legacy_baseline_record_without_head_parses_and_skips_detection(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    artifacts_dir = tmp_path / "artifacts"
    write_finalizer_baseline_records(
        artifacts_dir,
        [
            finalizer_baseline_record(
                repo_id="main",
                repo_path=repo,
                kind="main",
                name="main",
                scope="run_start",
                fingerprints={},
                captured_at="2026-08-25T11:00:00+00:00",
            ),
        ],
    )

    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    assert records[0].head is None


def test_capture_writes_fingerprints_for_dirty_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, repo)
    use_git_dirty_details(monkeypatch)
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


def test_capture_records_clean_sdd_sidecar_before_late_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    for repo in (main, plans, research):
        init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, main)
    use_git_dirty_details(monkeypatch)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda *_args: _sidecar_store(plans, research=research),
    )
    artifacts_dir = tmp_path / "artifacts"

    capture_dirty_baseline(str(main), str(artifacts_dir))
    target = "202608/report.md"
    (research / "202608").mkdir()
    (research / target).write_text("agent work\n", encoding="utf-8")
    assert (
        capture_opened_repo_dirty_baseline(
            "linked:research",
            str(research),
            kind="linked",
            name="research",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )

    baseline = load_dirty_baseline(artifacts_dir)
    assert baseline is not None
    assert baseline[finalizer_git.normalize_path(str(research))] == {}
    assert is_protected(artifacts_dir, research, target) is False
    details = dirty_details(main, artifacts_dir)
    assert target in details
    assert PRE_EXISTING_HEADER not in details


def test_late_open_baseline_capture_first_repo_id_wins(tmp_path: Path) -> None:
    repo = tmp_path / "linked"
    init_git_repo_with_identity(repo)
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
    assert load_dirty_baseline(artifacts_dir) == {
        finalizer_git.normalize_path(str(repo)): {
            "pre_existing.txt": (
                "??",
                _run_git(repo, "hash-object", "pre_existing.txt").strip(),
            )
        }
    }


def test_late_open_baseline_capture_first_path_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "research"
    init_git_repo_with_identity(repo)
    artifacts_dir = tmp_path / "artifacts"
    write_finalizer_baseline_records(
        artifacts_dir,
        [
            finalizer_baseline_record(
                repo_id="sdd:research",
                repo_path=repo,
                kind="sdd",
                name="research",
                scope="run_start",
                fingerprints={},
                captured_at="2026-08-25T11:00:00+00:00",
            ),
        ],
    )
    before = (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_bytes()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.dirty_path_fingerprints",
        lambda _path: pytest.fail("same-path late open should not fingerprint"),
    )

    assert (
        capture_opened_repo_dirty_baseline(
            "linked:research",
            str(repo),
            kind="linked",
            name="research",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )

    assert (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_bytes() == before


def test_split_pre_existing_changed_files_requires_matching_hash(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "sase_10"
    init_git_repo_with_identity(repo)
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
