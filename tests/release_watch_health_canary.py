"""release watch health canary tests."""

from __future__ import annotations

from typing import Any

import pytest

from _release_watch_health_test_helpers import (
    CORE_REPO,
    CORE_SHA,
    HEAD,
    OBSERVED,
    REPO,
    ReleaseTransportError,
    ScriptedGithub,
    canary_payload,
    make_facts,
    make_health,
    run_row,
    transport_error,
    wf_pages,
)


def canary_world(
    scheduled: dict[str, Any] | None,
    artifacts: dict[str, Any],
    payloads: dict[str, Any],
    extra_runs: list[dict[str, Any]] | None = None,
) -> tuple[ScriptedGithub, Any]:
    listing = {
        "artifacts": [
            {"id": index + 1, "name": name, "expired": expired}
            for index, (name, expired) in enumerate(artifacts.items())
        ]
    }
    runs = ([scheduled] if scheduled else []) + (extra_runs or [])
    sase = ScriptedGithub(
        REPO,
        reads={f"repos/{REPO}/actions/runs/7/artifacts": listing},
        listings={
            f"repos/{REPO}/actions/workflows/install-smoke.yml/runs": wf_pages(*runs)
        },
    )

    def artifact_text(repo: str, run_id: str, name: str) -> str:
        import json as _json

        assert repo == REPO and run_id == "7"
        if name not in payloads:
            raise transport_error(
                f"canary artifact {name}", "artifact is missing or expired: 404"
            )
        payload = payloads[name]
        if isinstance(payload, Exception):
            raise payload
        return _json.dumps(payload)

    return sase, artifact_text


def test_canary_green_pair_is_pass() -> None:
    scheduled = run_row(7, workflow="install-smoke.yml", event="schedule")
    sase, fetch = canary_world(
        scheduled,
        {"install-canary-ubuntu-latest": False, "install-canary-macos-latest": False},
        {
            "install-canary-ubuntu-latest": canary_payload("ubuntu-latest"),
            "install-canary-macos-latest": canary_payload("macos-latest", sha=CORE_SHA),
        },
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}), fetch)
    assert health.read_canary(OBSERVED) == {
        "linux": {
            "member": "linux",
            "run_id": "7",
            "attempt": 1,
            "sha": HEAD,
            "verdict": "pass",
            "packages": ["sase"],
            "scheduled": True,
        },
        "macos": {
            "member": "macos",
            "run_id": "7",
            "attempt": 1,
            "sha": CORE_SHA,
            "verdict": "pass",
            "packages": ["sase"],
            "scheduled": True,
        },
    }


def test_canary_red_marks_fail_with_reason() -> None:
    scheduled = run_row(7, workflow="install-smoke.yml", event="schedule")
    payload = canary_payload("ubuntu-latest", verdict="red")
    sase, fetch = canary_world(
        scheduled,
        {"install-canary-ubuntu-latest": False},
        {"install-canary-ubuntu-latest": payload},
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}), fetch)
    result = health.read_canary(OBSERVED)
    assert result["linux"]["verdict"] == "fail"
    assert result["linux"]["failing_step"] == "assert-newest-versions"
    assert "expected 0.18.0" in result["linux"]["reason"]
    assert result["macos"] is None


def test_canary_prefers_newest_scheduled_over_manual_probe() -> None:
    manual = run_row(9, workflow="install-smoke.yml", event="workflow_dispatch")
    scheduled = run_row(7, workflow="install-smoke.yml", event="schedule")
    sase, fetch = canary_world(
        scheduled,
        {"install-canary-ubuntu-latest": False},
        {"install-canary-ubuntu-latest": canary_payload("ubuntu-latest")},
        extra_runs=[manual],
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}), fetch)
    assert health.read_canary(OBSERVED)["linux"]["run_id"] == "7"


def test_canary_without_scheduled_run_is_empty_ready() -> None:
    manual = run_row(9, workflow="install-smoke.yml", event="workflow_dispatch")
    sase = ScriptedGithub(
        REPO,
        reads={},
        listings={
            f"repos/{REPO}/actions/workflows/install-smoke.yml/runs": wf_pages(manual)
        },
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}))
    assert health.read_canary(OBSERVED) == {"linux": None, "macos": None}


def test_canary_corrupt_json_is_unparsable_not_a_pass() -> None:
    scheduled = run_row(7, workflow="install-smoke.yml", event="schedule")
    sase, _ = canary_world(
        scheduled,
        {"install-canary-ubuntu-latest": False},
        {},
    )

    def bad_fetch(repo: str, run_id: str, name: str) -> str:
        return "{not json"

    health = make_health(
        make_facts(sase), ScriptedGithub(CORE_REPO, reads={}), bad_fetch
    )
    result = health.read_canary(OBSERVED)
    assert result["linux"]["verdict"] == "unparsable"
    assert result["linux"]["scheduled"] is True


def test_canary_identity_mismatch_is_flagged() -> None:
    scheduled = run_row(7, workflow="install-smoke.yml", event="schedule")
    sase, fetch = canary_world(
        scheduled,
        {"install-canary-ubuntu-latest": False},
        {"install-canary-ubuntu-latest": canary_payload("ubuntu-latest", run_id="999")},
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}), fetch)
    assert health.read_canary(OBSERVED)["linux"]["verdict"] == "unparsable"


def test_canary_listing_failure_raises_transport_error() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={},
        listings={
            f"repos/{REPO}/actions/workflows/install-smoke.yml/runs": transport_error(
                "install-smoke.yml runs", "HTTP 500"
            )
        },
    )
    health = make_health(make_facts(sase), ScriptedGithub(CORE_REPO, reads={}))
    with pytest.raises(ReleaseTransportError) as caught:
        health.read_canary(OBSERVED)
    assert caught.value.source == "install-smoke.yml runs"
