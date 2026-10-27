"""Rebind run-start baselines onto the checkout the agent actually uses."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    bind_run_start_baseline_to_workspace,
    capture_dirty_baseline,
    capture_opened_repo_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_raw_commits import (
    absorb_raw_local_commits,
    unrecorded_local_commits,
)

from ._commit_finalizer_raw_commits_helpers import (
    baseline_record,
    commit_file,
    init_repo,
    repo_head,
    run_git,
    write_baseline,
)
from ._commit_finalizer_sibling_helpers import set_agent_env


def test_bind_replaces_placeholder_main_with_claimed_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placeholder = init_repo(tmp_path / "placeholder")
    claimed = init_repo(tmp_path / "claimed")
    run_git(claimed, "commit", "--allow-empty", "-q", "-m", "post-prepare head")
    artifacts_dir = tmp_path / "artifacts"
    set_agent_env(monkeypatch, placeholder)
    capture_dirty_baseline(str(placeholder), str(artifacts_dir))

    bind_run_start_baseline_to_workspace(
        str(claimed), str(artifacts_dir), inherited=False
    )

    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    run_start = [record for record in records if record.scope == "run_start"]
    mains = [record for record in run_start if record.kind == "main"]
    assert len(mains) == 1
    assert mains[0].path == finalizer_git.normalize_path(str(claimed))
    assert mains[0].head == repo_head(claimed)
    placeholder_path = finalizer_git.normalize_path(str(placeholder))
    assert all(record.path != placeholder_path for record in run_start)


def test_bind_is_noop_when_main_already_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = init_repo(tmp_path / "workspace")
    artifacts_dir = tmp_path / "artifacts"
    set_agent_env(monkeypatch, repo)
    capture_dirty_baseline(str(repo), str(artifacts_dir))
    before = (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")

    bind_run_start_baseline_to_workspace(str(repo), str(artifacts_dir), inherited=False)

    after = (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")
    assert after == before


def test_bind_inherited_clears_fingerprints_and_drops_outside_opened_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = init_repo(tmp_path / "primary")
    claimed = init_repo(tmp_path / "claimed")
    inside = init_repo(claimed / "opened-inside")
    outside = init_repo(tmp_path / "opened-outside")
    artifacts_dir = tmp_path / "artifacts"
    set_agent_env(monkeypatch, primary)
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main:main",
                repo=primary,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(primary),
                fingerprints={"stale.txt": ("M", "abc123")},
            ),
            baseline_record(
                repo_id="linked:inside",
                repo=inside,
                kind="linked",
                name="inside",
                scope="opened_repo",
                head=repo_head(inside),
            ),
            baseline_record(
                repo_id="linked:outside",
                repo=outside,
                kind="linked",
                name="outside",
                scope="opened_repo",
                head=repo_head(outside),
            ),
        ],
    )

    bind_run_start_baseline_to_workspace(
        str(claimed), str(artifacts_dir), inherited=True
    )

    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    mains = [
        record
        for record in records
        if record.kind == "main" and record.scope == "run_start"
    ]
    assert len(mains) == 1
    assert mains[0].path == finalizer_git.normalize_path(str(claimed))
    assert mains[0].head == repo_head(claimed)
    assert mains[0].fingerprints == {}
    opened = [record for record in records if record.scope == "opened_repo"]
    assert [record.name for record in opened] == ["inside"]
    assert opened[0].path == finalizer_git.normalize_path(str(inside))


def test_bind_noops_when_project_dir_is_not_a_git_checkout(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    bind_run_start_baseline_to_workspace(
        str(tmp_path / "not-a-repo"), str(artifacts_dir), inherited=False
    )
    assert not (artifacts_dir / FINALIZER_BASELINE_FILENAME).exists()


def test_bind_then_absorb_stale_baseline_incident_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale primary baseline plus raw commits in the claimed workspace are absorbed.

    Bind first (as launch does after claiming workspace B), then the agent
    opens a linked clone under B and runs raw ``git commit`` in both repos.
    """

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    primary = init_repo(tmp_path / "primary")
    claimed = init_repo(tmp_path / "claimed")
    linked = init_repo(claimed / "bob-mac-capture")
    artifacts_dir = tmp_path / "artifacts"
    set_agent_env(monkeypatch, primary)
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main:main",
                repo=primary,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(primary),
            ),
        ],
    )

    bind_run_start_baseline_to_workspace(
        str(claimed), str(artifacts_dir), inherited=True
    )
    assert (
        capture_opened_repo_dirty_baseline(
            "linked:bob-mac-capture",
            str(linked),
            kind="linked",
            name="bob-mac-capture",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )
    main_sha = commit_file(claimed, "main-work.txt", "main\n", "raw main commit")
    linked_sha = commit_file(linked, "linked-work.txt", "linked\n", "raw linked commit")

    findings = unrecorded_local_commits(artifacts_dir)
    found = {
        finding.kind: [commit.sha for commit in finding.commits] for finding in findings
    }
    assert found["main"] == [main_sha]
    assert found["linked"] == [linked_sha]

    absorbed = absorb_raw_local_commits(str(claimed), artifacts_dir)
    absorbed_kinds = {entry.kind for entry in absorbed}
    assert absorbed_kinds == {"main", "linked"}
    assert repo_head(claimed) != main_sha
    assert repo_head(linked) != linked_sha
    assert "A  main-work.txt" in run_git(claimed, "status", "--porcelain=v1")
    assert "A  linked-work.txt" in run_git(linked, "status", "--porcelain=v1")
