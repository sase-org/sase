"""Fetch and refresh behavior for dev-update root planning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
from sase.version._git import GitUpstreamStatus
from tests.dev_update._plan_helpers import (
    probe,
    record,
    status,
    stub_fetch_git_upstream,  # noqa: F401 (registers the autouse fixture)
)


def test_plan_dev_update_fetches_before_classifying_root_actionability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo")
    fetched = False
    classify_calls: list[tuple[str, bool]] = []

    def classify(root: Path) -> GitUpstreamStatus:
        classify_calls.append((str(root), fetched))
        return status("/repo", behind=2 if fetched else 0)

    def fetch(upstream_status: GitUpstreamStatus) -> None:
        nonlocal fetched
        assert upstream_status.behind == 0
        fetched = True

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([host], host_record=host)

    assert classify_calls == [("/repo", False), ("/repo", True)]
    assert plan.roots[0].status == "actionable"
    assert plan.roots[0].behind == 2
    assert [pkg.record.name for pkg in plan.actionable] == ["sase"]


def test_plan_dev_update_fetches_once_per_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo")
    plugin = record("sase-github", role="plugin", source_root="/repo/plugins/github")
    fetches: list[GitUpstreamStatus] = []

    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status("/repo")
    )
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetches.append)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([host, plugin], host_record=host)

    assert len(fetches) == 1
    assert plan.roots[0].packages == ("sase", "sase-github")


def test_plan_dev_update_reuses_only_explicitly_refreshed_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/fresh")
    plugin = record("sase-github", role="plugin", source_root="/repo/other")
    fetched: set[str] = set()
    classified: list[str] = []

    def classify(root: Path) -> GitUpstreamStatus:
        root_text = str(root)
        classified.append(root_text)
        behind = 2 if root_text == "/repo/fresh" or root_text in fetched else 0
        return status(root_text, behind=behind)

    def fetch(upstream_status: GitUpstreamStatus) -> None:
        fetched.add(upstream_status.root)

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update(
        [host, plugin],
        host_record=host,
        already_refreshed_roots={"/repo/fresh"},
    )

    assert fetched == {"/repo/other"}
    assert classified == ["/repo/fresh", "/repo/other", "/repo/other"]
    assert [root.status for root in plan.roots] == ["actionable", "actionable"]
    assert [root.behind for root in plan.roots] == [2, 2]


def test_plan_dev_update_fetch_failure_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = record("sase", role="host", source_root="/repo/current")
    behind = record("sase-github", role="plugin", source_root="/repo/behind")
    statuses = {
        "/repo/current": status("/repo/current", behind=0),
        "/repo/behind": status("/repo/behind", behind=3),
    }

    def classify(root: Path) -> GitUpstreamStatus:
        return statuses[str(root)]

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise subprocess.CalledProcessError(1, ["git"], stderr="network down")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fail_fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([current, behind], host_record=current)

    current_root = plan.roots[0]
    behind_root = plan.roots[1]
    assert current_root.status == "skipped"
    assert "fetch failed; using cached upstream ref: network down" in (
        current_root.reason
    )
    assert current_root.fetch_error == "network down"
    assert plan.packages[0].fetch_error == "network down"
    assert behind_root.status == "actionable"
    assert behind_root.reason == "behind upstream by 3 commit(s)"
    assert behind_root.fetch_error == "network down"
    assert plan.packages[1].status == "actionable"
    assert plan.packages[1].fetch_error == "network down"


def test_plan_dev_update_does_not_fetch_no_upstream_or_detached_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_upstream = record("sase", role="host", source_root="/repo/no-upstream")
    detached = record("sase-core-rs", role="core", source_root="/repo/detached")
    statuses = {
        "/repo/no-upstream": status(
            "/repo/no-upstream", upstream=None, ahead=None, behind=None
        ),
        "/repo/detached": status(
            "/repo/detached",
            detached=True,
            upstream=None,
            ahead=None,
            behind=None,
        ),
    }

    def classify(root: Path) -> GitUpstreamStatus:
        return statuses[str(root)]

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise AssertionError("no-upstream and detached roots must not fetch")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fail_fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([no_upstream, detached], host_record=no_upstream)

    assert plan.actionable == ()
    assert [root.fetch_error for root in plan.roots] == [None, None]
    assert "no upstream" in plan.roots[0].reason
    assert "detached" in plan.roots[1].reason
