"""Baseline record parsing and provenance views."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    load_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    split_pre_existing_changed_files,
)

from ._commit_finalizer_baseline_helpers import (
    finalizer_baseline_record,
    init_git_repo_with_identity,
    is_protected,
    write_finalizer_baseline_records,
)

_PROVENANCE_ALREADY_DIRTY = "already_dirty_at_run_start"
_PROVENANCE_CHANGED = "changed_since_run_start"
_PROVENANCE_NEW = "new_since_run_start"


def _path_provenance(
    *,
    repo_path: Path,
    path: str,
    baseline: dict[str, dict[str, tuple[str, str | None]]],
) -> str:
    fingerprints = baseline.get(finalizer_git.normalize_path(str(repo_path)))
    if fingerprints is None:
        return _PROVENANCE_NEW

    _run_owned, pre_existing = split_pre_existing_changed_files(
        str(repo_path),
        [path],
        fingerprints,
    )
    if path in pre_existing:
        return _PROVENANCE_ALREADY_DIRTY
    if path in fingerprints:
        return _PROVENANCE_CHANGED
    return _PROVENANCE_NEW


def test_finalizer_baseline_views_share_scope_and_duplicate_path_contract(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    run_start_repo = tmp_path / "run-start"
    opened_repo = tmp_path / "opened"
    duplicate_repo = tmp_path / "duplicate"
    for repo in (run_start_repo, opened_repo, duplicate_repo):
        init_git_repo_with_identity(repo)

    (run_start_repo / "run.txt").write_text("foreign at run start\n", encoding="utf-8")
    (opened_repo / "opened.txt").write_text("foreign at open\n", encoding="utf-8")
    (duplicate_repo / "dup.txt").write_text("agent work\n", encoding="utf-8")

    duplicate_fingerprints = dirty_path_fingerprints(str(duplicate_repo))
    write_finalizer_baseline_records(
        artifacts_dir,
        [
            finalizer_baseline_record(
                repo_id="linked:duplicate",
                repo_path=duplicate_repo,
                kind="linked",
                name="duplicate",
                scope="opened_repo",
                fingerprints=duplicate_fingerprints,
                captured_at="2026-08-25T11:00:02+00:00",
            ),
            finalizer_baseline_record(
                repo_id="linked:opened",
                repo_path=opened_repo,
                kind="linked",
                name="opened",
                scope="opened_repo",
                fingerprints=dirty_path_fingerprints(str(opened_repo)),
                captured_at="2026-08-25T11:00:01+00:00",
            ),
            finalizer_baseline_record(
                repo_id="main",
                repo_path=run_start_repo,
                kind="main",
                name="main",
                scope="run_start",
                fingerprints=dirty_path_fingerprints(str(run_start_repo)),
                captured_at="2026-08-25T11:00:00+00:00",
            ),
            finalizer_baseline_record(
                repo_id="sdd:duplicate",
                repo_path=duplicate_repo,
                kind="sdd",
                name="duplicate",
                scope="run_start",
                fingerprints={},
                captured_at="2026-08-25T10:59:59+00:00",
            ),
        ],
    )

    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    records_by_path = {record.path: record for record in records}
    duplicate_key = finalizer_git.normalize_path(str(duplicate_repo))
    opened_key = finalizer_git.normalize_path(str(opened_repo))
    assert records_by_path[duplicate_key].scope == "run_start"
    assert records_by_path[opened_key].scope == "opened_repo"

    baseline = load_dirty_baseline(artifacts_dir)
    assert baseline is not None
    pairs = (
        (run_start_repo, "run.txt"),
        (opened_repo, "opened.txt"),
        (duplicate_repo, "dup.txt"),
    )
    for repo_path, path in pairs:
        provenance = _path_provenance(
            repo_path=repo_path,
            path=path,
            baseline=baseline,
        )
        assert is_protected(artifacts_dir, repo_path, path) == (
            provenance != _PROVENANCE_NEW
        )


def test_historical_opened_repo_baseline_views_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "research"
    init_git_repo_with_identity(repo)
    target = "202608/remove_direct_git_plugin_installs.md"
    (repo / "202608").mkdir()
    (repo / target).write_text("historical report body\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    recorded_fingerprint = ("??", "727c244a43888a5ac147acfcc54b5699862f777c")
    write_finalizer_baseline_records(
        artifacts_dir,
        [
            finalizer_baseline_record(
                repo_id="linked:research",
                repo_path=repo,
                kind="linked",
                name="research",
                scope="opened_repo",
                fingerprints={target: recorded_fingerprint},
                captured_at="2026-08-25T15:21:06+00:00",
            ),
        ],
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_status.dirty_path_fingerprints",
        lambda _repo_path: {target: recorded_fingerprint},
    )

    baseline = load_dirty_baseline(artifacts_dir)
    assert baseline is not None
    provenance = _path_provenance(repo_path=repo, path=target, baseline=baseline)

    assert provenance != _PROVENANCE_NEW
    assert is_protected(artifacts_dir, repo, target) is True


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
