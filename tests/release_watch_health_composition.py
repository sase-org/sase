"""release watch health composition tests."""

from __future__ import annotations

from typing import Any

import pytest

from _release_watch_health_test_helpers import (
    CORE_REPO,
    CORE_SHA,
    HEAD,
    OBSERVED,
    OBSERVED_ISO,
    PIN,
    REPO,
    WORKFLOW_YML,
    ReleaseFactsReader,
    ReleaseHealthReader,
    ScriptedGithub,
    b64,
    canary_payload,
    make_facts,
    make_health,
    pypi_complete,
    run_row,
    wf_pages,
)


class StubTrainReader(ReleaseFactsReader):
    def __init__(self, train: dict[str, Any]) -> None:
        self._train = train

    def collect_train_snapshot(self, *, observed_at: Any) -> dict[str, Any]:
        del observed_at
        return dict(self._train)


def stub_train(
    master: dict[str, Any] | None = None,
    release_pr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def envelope(value: Any) -> dict[str, Any]:
        return {"status": "ready", "value": value}

    return {
        "repository": envelope({}),
        "master": envelope(master),
        "release_pr": envelope(release_pr),
        "tags": envelope([]),
        "releases": envelope([]),
        "pypi": envelope({}),
        "trains": envelope([]),
        "workflows": envelope({}),
        "candidate": envelope(None),
        "merge_history": envelope([]),
    }


class StubHealth:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.seen: dict[str, Any] = {}

    def collect_health_snapshot(
        self, *, observed_at: Any, master: Any, release_pr: Any
    ) -> dict[str, Any]:
        self.seen = {
            "observed_at": observed_at,
            "master": master,
            "release_pr": release_pr,
        }
        return dict(self.snapshot)


def health_envelopes() -> dict[str, Any]:
    def envelope(value: Any) -> dict[str, Any]:
        return {"status": "ready", "value": value}

    return {
        "core": envelope({}),
        "canary": envelope({}),
        "core_ensure": envelope({}),
        "issues": envelope([]),
        "core_actions_access": envelope({}),
        "blocker_lineage": envelope(None),
    }


def test_collect_snapshot_merges_sixteen_keys_in_wire_order() -> None:
    master = {"sha": HEAD}
    pr = {"source_pin": PIN}
    stub = StubHealth(health_envelopes())
    snapshot = StubTrainReader(stub_train(master, pr)).collect_snapshot(
        observed_at=OBSERVED, health=stub
    )
    assert list(snapshot) == [
        "repository",
        "master",
        "release_pr",
        "tags",
        "releases",
        "pypi",
        "trains",
        "workflows",
        "core",
        "canary",
        "candidate",
        "core_ensure",
        "issues",
        "core_actions_access",
        "merge_history",
        "blocker_lineage",
    ]
    assert stub.seen["master"] == master
    assert stub.seen["release_pr"] == pr


def test_collect_snapshot_core_ensure_fails_closed_without_master() -> None:
    train = stub_train(None, None)
    train["master"] = {
        "status": "unreadable",
        "source": "master",
        "message": "boom",
        "remedy": "fix",
    }
    sase = ScriptedGithub(
        REPO,
        reads={},
        listings={
            f"repos/{REPO}/actions/workflows/install-smoke.yml/runs": [],
            f"repos/{REPO}/issues": [],
        },
    )
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/git/ref/heads/master": {"object": {"sha": HEAD}},
            f"repos/{CORE_REPO}/actions/runs": {"total_count": 0, "workflow_runs": []},
        },
        listings={
            f"repos/{CORE_REPO}/actions/workflows/ci.yml/runs": [],
            f"repos/{CORE_REPO}/actions/workflows/release-plz.yml/runs": [],
            f"repos/{CORE_REPO}/pulls": [],
        },
    )
    health = make_health(make_facts(sase), core)
    snapshot = StubTrainReader(train).collect_snapshot(
        observed_at=OBSERVED, health=health
    )
    assert snapshot["core_ensure"]["status"] == "unreadable"
    assert snapshot["core_ensure"]["source"] == "core_ensure"
    assert snapshot["canary"] == {
        "status": "ready",
        "value": {"linux": None, "macos": None},
    }
    assert snapshot["blocker_lineage"] == {"status": "ready", "value": None}


def full_world() -> tuple[ReleaseFactsReader, ReleaseHealthReader]:
    gate = run_row(3, sha=HEAD)
    gate_jobs = [
        {"id": 31, "name": "lint", "status": "completed", "conclusion": "success"},
        {"id": 32, "name": "tests", "status": "completed", "conclusion": "success"},
    ]
    sase_reads = {
        f"repos/{REPO}": {
            "owner": {"login": "sase-org"},
            "name": "sase",
            "default_branch": "master",
        },
        f"repos/{REPO}/git/ref/heads/master": {"object": {"sha": HEAD}},
        f"repos/{REPO}/branches/master/protection/required_status_checks": {
            "contexts": ["tests", "lint"],
            "checks": [],
        },
        f"repos/{REPO}/contents/sase-core-revision.txt": {
            "encoding": "base64",
            "content": b64(PIN + "\n"),
        },
        f"repos/{REPO}/actions/runs/7/artifacts": {
            "artifacts": [
                {"id": 1, "name": "install-canary-ubuntu-latest", "expired": False},
                {"id": 2, "name": "install-canary-macos-latest", "expired": False},
            ]
        },
    }
    sase_listings: dict[str, Any] = {
        f"repos/{REPO}/actions/workflows/master-gate.yml/runs": wf_pages(gate),
        f"repos/{REPO}/actions/runs/3/attempts/1/jobs": [{"jobs": gate_jobs}],
        f"repos/{REPO}/pulls": [],
        f"repos/{REPO}/git/matching-refs/tags/v": [],
        f"repos/{REPO}/releases": [],
        f"repos/{REPO}/actions/workflows/release.yml/runs": wf_pages(),
        f"repos/{REPO}/actions/workflows/publish.yml/runs": wf_pages(),
        f"repos/{REPO}/actions/workflows/install-smoke.yml/runs": wf_pages(
            run_row(7, workflow="install-smoke.yml", event="schedule")
        ),
        f"repos/{REPO}/issues": [],
    }
    sase = ScriptedGithub(REPO, reads=sase_reads, listings=sase_listings)
    pypi = {
        "sase": {"releases": {}},
        "sase-core-rs": pypi_complete(),
    }

    class TwoPackagePypi:
        def project(self, name: str) -> Any:
            return pypi[name]

    core_gate = run_row(5, sha=CORE_SHA)
    core_reads = {
        f"repos/{CORE_REPO}/git/ref/heads/master": {"object": {"sha": CORE_SHA}},
        f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
            "encoding": "base64",
            "content": b64(WORKFLOW_YML),
        },
        f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": "ahead"},
        f"repos/{CORE_REPO}/actions/runs": {"total_count": 0, "workflow_runs": []},
    }
    core_listings: dict[str, Any] = {
        f"repos/{CORE_REPO}/actions/workflows/ci.yml/runs": wf_pages(core_gate),
        f"repos/{CORE_REPO}/actions/runs/5/attempts/1/jobs": [{"jobs": gate_jobs}],
        f"repos/{CORE_REPO}/actions/workflows/release-plz.yml/runs": [],
        f"repos/{CORE_REPO}/pulls": [],
    }
    core = ScriptedGithub(CORE_REPO, reads=core_reads, listings=core_listings)
    facts = ReleaseFactsReader(repo=REPO, github=sase, pypi=TwoPackagePypi())  # type: ignore[arg-type]

    def artifact_text(repo: str, run_id: str, name: str) -> str:
        import json as _json

        os_name = name.removeprefix("install-canary-")
        return _json.dumps(canary_payload(os_name))

    return facts, ReleaseHealthReader(
        facts, core_github=core, artifact_text=artifact_text
    )


def test_complete_snapshot_feeds_real_binding() -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "release_steward_decide"):
        pytest.skip("installed sase_core_rs predates release_steward_decide")
    import _release_watch_decide as decide_tool

    facts, health = full_world()
    snapshot = facts.collect_snapshot(observed_at=OBSERVED, health=health)
    request = {
        "schema_version": 1,
        "observed_at": OBSERVED_ISO,
        "policy": {
            "merge_authority_enabled": True,
            "observe_only": True,
            "tick_identity": "run-7/attempt-1",
            "cadence": {
                "kind": "daily",
                "merge_after_hour_utc": 9,
                "max_merges_per_utc_day": 1,
            },
        },
        "snapshot": snapshot,
    }
    result = decide_tool.decide(request)
    assert result["process_exit"] == 0
    assert result["primary"]["kind"] == "nothing_to_release"
    assert result.get("train_action") is None
    assert result.get("escalation") is None
