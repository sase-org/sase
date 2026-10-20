"""release watch health core tests."""

from __future__ import annotations

from typing import Any

import pytest

from _release_watch_health_test_helpers import (
    CORE_REPO,
    CORE_SHA,
    HEAD,
    OBSERVED,
    REPO,
    ReleaseFactsError,
    ScriptedGithub,
    b64,
    flat,
    job_row,
    make_facts,
    make_health,
    run_row,
    wf_pages,
)


def core_base_reads(
    master_runs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reads = {
        f"repos/{CORE_REPO}/git/ref/heads/master": {
            "object": {"sha": CORE_SHA, "type": "commit"}
        },
        f"repos/{CORE_REPO}/actions/runs": {"total_count": 0, "workflow_runs": []},
    }
    listings: dict[str, Any] = {
        f"repos/{CORE_REPO}/actions/workflows/ci.yml/runs": wf_pages(*master_runs),
        f"repos/{CORE_REPO}/actions/workflows/release-plz.yml/runs": [],
        f"repos/{CORE_REPO}/pulls": [],
    }
    return reads, listings


def test_core_master_ci_green_run_carries_jobs() -> None:
    run = run_row(7, sha=CORE_SHA)
    reads, listings = core_base_reads([run])
    listings["repos/sase-org/sase-core/actions/runs/7/attempts/1/jobs"] = [
        {
            "jobs": [
                {
                    "id": 11,
                    "name": "tests",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        }
    ]
    sase = ScriptedGithub(REPO, reads={})
    health = make_health(
        make_facts(sase), ScriptedGithub(CORE_REPO, reads=reads, listings=listings)
    )
    core = health.read_core_facts(OBSERVED)
    assert core["open_release_pr"] is None
    assert core["cuts"] == []
    gate = core["master_ci"]
    assert gate is not None
    assert gate["sha"] == CORE_SHA
    assert gate["conclusion"] == "success"
    assert "created_at" not in gate
    assert gate["jobs"] == [
        {
            "id": "11",
            "name": "tests",
            "conclusion": "success",
            "is_test": True,
            "is_lint": False,
            "attempt": 1,
        }
    ]


def test_core_master_ci_absent_without_matching_run() -> None:
    run = run_row(7, sha=HEAD)
    reads, listings = core_base_reads([run])
    sase = ScriptedGithub(REPO, reads={})
    health = make_health(
        make_facts(sase), ScriptedGithub(CORE_REPO, reads=reads, listings=listings)
    )
    assert health.read_core_facts(OBSERVED)["master_ci"] is None


def test_core_release_pr_matches_release_plz_convention() -> None:
    run = run_row(7, sha=HEAD)
    reads, listings = core_base_reads([run])
    listings[f"repos/{CORE_REPO}/pulls"] = flat(
        [
            {
                "number": 12,
                "head": {"ref": "release-plz-2026-10-20T07-41-00Z", "sha": HEAD},
                "title": "chore: release v0.50.1",
                "html_url": "https://example.test/pr/12",
            }
        ]
    )
    sase = ScriptedGithub(REPO, reads={})
    health = make_health(
        make_facts(sase), ScriptedGithub(CORE_REPO, reads=reads, listings=listings)
    )
    assert health.read_core_facts(OBSERVED)["open_release_pr"] == {
        "number": 12,
        "head_sha": HEAD,
        "url": "https://example.test/pr/12",
    }


def test_core_release_pr_multiple_matches_are_inconsistent() -> None:
    reads, listings = core_base_reads([])
    listings[f"repos/{CORE_REPO}/pulls"] = flat(
        [
            {
                "number": 12,
                "head": {"ref": "release-plz-2026-10-20T07-41-00Z", "sha": HEAD},
                "title": "chore: release v0.50.1",
                "html_url": "https://example.test/12",
            },
            {
                "number": 13,
                "head": {"ref": "release-plz-2026-10-19T07-41-00Z", "sha": CORE_SHA},
                "title": "chore: release v0.50.0",
                "html_url": "https://example.test/13",
            },
        ]
    )
    sase = ScriptedGithub(REPO, reads={})
    health = make_health(
        make_facts(sase), ScriptedGithub(CORE_REPO, reads=reads, listings=listings)
    )
    with pytest.raises(ReleaseFactsError, match="multiple open core release PRs"):
        health.read_core_facts(OBSERVED)


def cut_world(
    runs: list[dict[str, Any]],
    jobs_by_attempt: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    annotations: dict[str, list[dict[str, Any]]] | None = None,
) -> ScriptedGithub:
    reads: dict[str, Any] = {
        f"repos/{CORE_REPO}/git/ref/heads/master": {
            "object": {"sha": CORE_SHA, "type": "commit"}
        },
        f"repos/{CORE_REPO}/actions/runs": {"total_count": 0, "workflow_runs": []},
    }
    listings: dict[str, Any] = {
        f"repos/{CORE_REPO}/actions/workflows/ci.yml/runs": [],
        f"repos/{CORE_REPO}/actions/workflows/release-plz.yml/runs": wf_pages(*runs),
        f"repos/{CORE_REPO}/pulls": [],
    }
    for (run_id, attempt), jobs in (jobs_by_attempt or {}).items():
        listings[f"repos/{CORE_REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs"] = [
            {"jobs": jobs}
        ]
    for check_id, notes in (annotations or {}).items():
        reads[f"repos/{CORE_REPO}/check-runs/{check_id}/annotations"] = notes
    return ScriptedGithub(CORE_REPO, reads=reads, listings=listings)


def test_in_flight_cut_carries_pin_and_no_evidence() -> None:
    run = run_row(
        9,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="in_progress",
        conclusion=None,
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), cut_world([run])).read_core_facts(OBSERVED)[
        "cuts"
    ]
    assert cuts == [
        {
            "run_id": "9",
            "attempt": 1,
            "source_pin": CORE_SHA,
            "status": "in_progress",
            "conclusion": None,
            "diagnostic_available": True,
        }
    ]


def test_red_cut_with_typed_annotation_is_evidence() -> None:
    run = run_row(
        9,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="completed",
        conclusion="failure",
    )
    line = "CORE_CUT_RED check=tests run=https://example.test/9 attempt=1"
    core = cut_world(
        [run],
        jobs_by_attempt={("9", 1): [job_row(11, conclusion="failure", check_run=99)]},
        annotations={"99": [{"message": line, "annotation_level": "failure"}]},
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), core).read_core_facts(OBSERVED)["cuts"]
    assert cuts[0]["typed_failure"] == line
    assert cuts[0]["diagnostic_available"] is True


def test_red_cut_without_annotation_fails_closed() -> None:
    run = run_row(
        9,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="completed",
        conclusion="failure",
    )
    core = cut_world(
        [run],
        jobs_by_attempt={("9", 1): [job_row(11, conclusion="failure", check_run=99)]},
        annotations={
            "99": [{"message": "generic boom", "annotation_level": "failure"}]
        },
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), core).read_core_facts(OBSERVED)["cuts"]
    assert "typed_failure" not in cuts[0]
    assert cuts[0]["diagnostic_available"] is False


def test_never_registered_cut_parses() -> None:
    run = run_row(
        9,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="completed",
        conclusion="failure",
    )
    line = "CHECKS_NEVER_REGISTERED check=checks run=unknown attempt=0"
    core = cut_world(
        [run],
        jobs_by_attempt={("9", 1): [job_row(11, conclusion="failure", check_run=99)]},
        annotations={"99": [{"message": line}]},
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), core).read_core_facts(OBSERVED)["cuts"]
    assert cuts[0]["typed_failure"] == line


def test_cancelled_cut_needs_no_diagnostic() -> None:
    run = run_row(
        9,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="completed",
        conclusion="cancelled",
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), cut_world([run])).read_core_facts(OBSERVED)[
        "cuts"
    ]
    assert "typed_failure" not in cuts[0]
    assert cuts[0]["diagnostic_available"] is True


def test_cuts_keep_newest_twenty_completed_plus_in_flight() -> None:
    runs = [
        run_row(100 + i, workflow="release-plz.yml", sha=CORE_SHA) for i in range(21)
    ]
    live = run_row(
        7,
        workflow="release-plz.yml",
        sha=CORE_SHA,
        status="in_progress",
        conclusion=None,
    )
    sase = ScriptedGithub(REPO, reads={})
    cuts = make_health(make_facts(sase), cut_world(runs + [live])).read_core_facts(
        OBSERVED
    )["cuts"]
    assert len(cuts) == 21
    assert cuts[0]["run_id"] == "7"
    assert cuts[0]["status"] == "in_progress"
