"""Monitor retention lifecycle: baselines, linked repos, and notifications.

Covers linked-repository baselines, unavailable checkouts, stale bindings,
failed git preflights, linked-discovery failures, foreign and same-workspace
starter evidence, and the single-notification guarantee.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.monitor._settlement_retention import release_monitor_claim
from sase.running_field import get_claimed_workspaces

from ._fixtures import make_starter_agent
from ._retention_fixtures import (
    init_retention_repo,
    make_retention_monitor,
    read_retention_meta,
    retention_record,
    write_monitor_baselines,
    write_opened_linked,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def _write_starter_baseline(
    starter_dir: str, repos: list[tuple[str, str, str, Path]]
) -> None:
    """Write a run-start baseline with explicit kinds into a starter dir."""
    import json

    from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
    from sase.llm_provider.commit_finalizer_git import normalize_path

    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(path)),
                "kind": kind,
                "name": name,
                "scope": "run_start",
                "captured_at": "2026-09-06T11:59:00+00:00",
                "fingerprints": {},
            }
            for repo_id, kind, name, path in repos
        ],
    }
    (Path(starter_dir) / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_dirty_linked_repo_beyond_eighth_still_retains(tmp_path: Path) -> None:
    """No eight-repository cutoff: the ninth dirty linked repo retains."""
    repos: list[tuple[str, Path]] = []
    primary = init_retention_repo(tmp_path / "ws-0", dirty=False)
    repos.append(("primary", primary))
    for index in range(1, 9):
        clean = init_retention_repo(tmp_path / f"ws-{index}", dirty=False)
        repos.append((f"linked-{index}", clean))
    ninth = init_retention_repo(tmp_path / "ws-9", dirty=True)
    repos.append(("linked-9", ninth))
    artifacts_dir, project_file = make_retention_monitor(primary)
    write_monitor_baselines(artifacts_dir, repos)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (ninth / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_unavailable_owned_checkout_retains_as_uncertainty(
    tmp_path: Path,
) -> None:
    """A deleted owned checkout is uncertainty, not a clean release."""
    import shutil

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    write_monitor_baselines(artifacts_dir, [("primary", repo)])
    shutil.rmtree(repo)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("probe_errors")


def test_stale_binding_retries_in_fresh_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale loaded binding retries the same Rust settlement fresh."""
    from sase.turns import workspace_retention as _adapter

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    def _stale(*_args: object, **_kwargs: object) -> object:
        raise TypeError("old release_workspace signature")

    monkeypatch.setattr(_adapter, "settle_stranded_workspace", _stale)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_failed_git_preflight_without_baseline_retains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed git preflight keeps the known dirty workspace instead of dropping it."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._classify_git_toplevel",
        lambda _path: ("failed", "git preflight failed"),
    )

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"


def test_discovery_failure_with_dirty_opened_linked_retains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed linked discovery retains rather than classifying only a clean primary."""
    primary = init_retention_repo(tmp_path / "ws", dirty=False)
    linked = init_retention_repo(tmp_path / "linked", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(primary)
    write_opened_linked(artifacts_dir, "linked-core", linked)
    monkeypatch.setattr(
        "sase.monitor.settlement_fresh_owner._shared_repos",
        lambda *_args, **_kwargs: ([], set(), "linked discovery failed"),
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (linked / "tracked.txt").read_text() == "session owned\n"
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record.get("probe_errors")


def test_foreign_starter_evidence_releases_clean_workspace(
    tmp_path: Path,
) -> None:
    """A starter from a deleted foreign workspace must not pin this monitor."""
    import shutil

    foreign_ws = tmp_path / "foreign-ws"
    foreign_repo = init_retention_repo(foreign_ws, dirty=True)
    foreign_plans = init_retention_repo(tmp_path / "foreign-plans", dirty=True)
    starter_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        workspace_num=9,
        workspace_dir=str(foreign_ws),
        pid=999999999,
    )
    _write_starter_baseline(
        starter_dir,
        [
            ("main:main", "main", "main", foreign_repo),
            ("sibling:plans", "sibling", "plans", foreign_plans),
        ],
    )
    write_opened_linked(starter_dir, "foreign-linked", foreign_repo)
    shutil.rmtree(foreign_ws)
    shutil.rmtree(foreign_plans)

    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(repo)
    write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_starter_artifacts_dir"] = starter_dir
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None


def test_same_workspace_starter_baseline_still_contributes(
    tmp_path: Path,
) -> None:
    """A starter from the same workspace still contributes baseline evidence."""
    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    linked = init_retention_repo(tmp_path / "linked", dirty=False)
    starter_dir = make_starter_agent(
        "proj",
        "20260906115900",
        "acme",
        workspace_num=3,
        workspace_dir=str(repo),
        pid=os.getpid(),
    )
    write_monitor_baselines(starter_dir, [("linked", linked)])
    write_opened_linked(starter_dir, "linked", linked)
    (linked / "tracked.txt").write_text("session owned\n", encoding="utf-8")

    artifacts_dir, project_file = make_retention_monitor(repo)
    write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)
    meta["monitor_starter_artifacts_dir"] = starter_dir
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record = retention_record(artifacts_dir)
    assert record is not None
    assert record["disposition"] == "retain"
    assert record["policy_reason"] == "session_owned_dirt"
    assert "linked" in record["affected_repo_ids"]


def test_retained_monitor_stores_exactly_one_notification(
    tmp_path: Path,
) -> None:
    """A retained monitor stores one recovery notification, plus-oned on retry."""
    from sase.notifications.store import load_notifications

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    write_monitor_baselines(artifacts_dir, [("primary", repo)])
    meta = read_retention_meta(artifacts_dir)

    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    rows = load_notifications()
    assert len(rows) == 1
    assert "Workspace held: stranded work" in rows[0].notes
    assert rows[0].action == "JumpToAgent"
    assert rows[0].action_data["raw_suffix"] == "20260906120000"

    meta = read_retention_meta(artifacts_dir)
    assert (
        release_monitor_claim(meta, project_name="proj", artifacts_dir=artifacts_dir)
        is None
    )
    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].plus_one_count >= 1
