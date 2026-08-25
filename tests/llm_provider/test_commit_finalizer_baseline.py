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

from sase.finalizers.commit_validation import protected_baseline_paths
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
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    set_agent_env,
    set_clean_main,
)

_PRE_EXISTING_HEADER = "Pre-existing changes detected before this run started"
_PROVENANCE_ALREADY_DIRTY = "already_dirty_at_run_start"
_PROVENANCE_CHANGED = "changed_since_run_start"
_PROVENANCE_NEW = "new_since_run_start"


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


def _write_finalizer_baseline_records(
    artifacts_dir: Path,
    records: list[dict[str, object]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps({"schema_version": 1, "repositories": records}),
        encoding="utf-8",
    )


def _sidecar_store(plans: Path, **sidecars: Path) -> SddStore:
    return SddStore(
        storage=SDD_STORAGE_SIDECAR_REPOS,
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs=sidecars,
    )


def _finalizer_baseline_record(
    *,
    repo_id: str,
    repo_path: Path,
    kind: str,
    name: str,
    scope: str,
    fingerprints: dict[str, tuple[str, str | None]],
    captured_at: str,
) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "path": finalizer_git.normalize_path(str(repo_path)),
        "kind": kind,
        "name": name,
        "scope": scope,
        "captured_at": captured_at,
        "fingerprints": {
            path: list(fingerprint) for path, fingerprint in fingerprints.items()
        },
    }


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


def _is_protected(artifacts_dir: Path, repo_path: Path, path: str) -> bool:
    return path in protected_baseline_paths(
        artifacts_dir,
        str(repo_path),
        get_changed_files=lambda _repo: [path],
    )


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
        "sase.llm_provider.commit_finalizer_state.collect_baseline_repositories",
        boom,
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


def test_capture_records_clean_sdd_sidecar_before_late_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    for repo in (main, plans, research):
        _init_git_repo_with_identity(repo)
    set_agent_env(monkeypatch, main)
    _use_git_dirty_details(monkeypatch)
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
    assert _is_protected(artifacts_dir, research, target) is False
    details = _dirty_details(main, artifacts_dir)
    assert target in details
    assert _PRE_EXISTING_HEADER not in details


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
    _init_git_repo_with_identity(repo)
    artifacts_dir = tmp_path / "artifacts"
    _write_finalizer_baseline_records(
        artifacts_dir,
        [
            _finalizer_baseline_record(
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


def test_finalizer_baseline_views_share_scope_and_duplicate_path_contract(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    run_start_repo = tmp_path / "run-start"
    opened_repo = tmp_path / "opened"
    duplicate_repo = tmp_path / "duplicate"
    for repo in (run_start_repo, opened_repo, duplicate_repo):
        _init_git_repo_with_identity(repo)

    (run_start_repo / "run.txt").write_text("foreign at run start\n", encoding="utf-8")
    (opened_repo / "opened.txt").write_text("foreign at open\n", encoding="utf-8")
    (duplicate_repo / "dup.txt").write_text("agent work\n", encoding="utf-8")

    duplicate_fingerprints = dirty_path_fingerprints(str(duplicate_repo))
    _write_finalizer_baseline_records(
        artifacts_dir,
        [
            _finalizer_baseline_record(
                repo_id="linked:duplicate",
                repo_path=duplicate_repo,
                kind="linked",
                name="duplicate",
                scope="opened_repo",
                fingerprints=duplicate_fingerprints,
                captured_at="2026-08-25T11:00:02+00:00",
            ),
            _finalizer_baseline_record(
                repo_id="linked:opened",
                repo_path=opened_repo,
                kind="linked",
                name="opened",
                scope="opened_repo",
                fingerprints=dirty_path_fingerprints(str(opened_repo)),
                captured_at="2026-08-25T11:00:01+00:00",
            ),
            _finalizer_baseline_record(
                repo_id="main",
                repo_path=run_start_repo,
                kind="main",
                name="main",
                scope="run_start",
                fingerprints=dirty_path_fingerprints(str(run_start_repo)),
                captured_at="2026-08-25T11:00:00+00:00",
            ),
            _finalizer_baseline_record(
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
        assert _is_protected(artifacts_dir, repo_path, path) == (
            provenance != _PROVENANCE_NEW
        )


def test_historical_opened_repo_baseline_views_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "research"
    _init_git_repo_with_identity(repo)
    target = "202608/remove_direct_git_plugin_installs.md"
    (repo / "202608").mkdir()
    (repo / target).write_text("historical report body\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    recorded_fingerprint = ("??", "727c244a43888a5ac147acfcc54b5699862f777c")
    _write_finalizer_baseline_records(
        artifacts_dir,
        [
            _finalizer_baseline_record(
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
    assert _is_protected(artifacts_dir, repo, target) is True


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
