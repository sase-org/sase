"""Health, canary, and escalation evidence for the release steward.

Offline fixture tests for ``tools/_release_watch_health.py`` and the new
``ReleaseFactsReader`` accessors, plus a real-binding round trip proving
the composed snapshot satisfies the Rust wire.
"""

from __future__ import annotations

import base64
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_core import CORE_REPO  # noqa: E402
from _release_watch_facts import ReleaseFactsError, ReleaseFactsReader  # noqa: E402
from _release_watch_health import ReleaseHealthReader  # noqa: E402
from _release_watch_transport import ReleaseTransportError  # noqa: E402

HEAD = "a" * 40
PIN = "b" * 40
CORE_SHA = "c" * 40
OBSERVED = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
OBSERVED_ISO = "2026-10-20T12:00:00Z"
RUN_CREATED = "2026-10-20T11:00:00Z"

REPO = "sase-org/sase"

WORKFLOW_YML = """\
name: Release-plz
env:
  EXPECTED_DIST_SUFFIXES: |
    manylinux_2_28_x86_64.whl
    .tar.gz
"""


def b64(text: str) -> str:
    raw = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return "\n".join(raw[i : i + 60] for i in range(0, len(raw), 60))


def transport_error(source: str, message: str = "boom") -> ReleaseTransportError:
    return ReleaseTransportError(source, message)


def wf_pages(*runs: dict[str, Any]) -> list[dict[str, Any]]:
    """Transport-level workflow-run pages: objects the transport keeps paged."""
    return [{"workflow_runs": list(runs)}]


def flat(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Transport-level array-endpoint payload: flattened by the transport."""
    return list(rows)


class ScriptedGithub:
    """Exact-path fake for GithubTransport.json/pages."""

    def __init__(
        self,
        repo: str,
        *,
        reads: dict[str, Any] | None = None,
        listings: dict[str, Any] | None = None,
    ) -> None:
        self.repo = repo
        self.reads = reads or {}
        self.listings = listings or {}
        self.calls: list[str] = []

    def _lookup(self, table: dict[str, Any], path: str) -> Any:
        self.calls.append(path)
        if path not in table:
            raise AssertionError(f"unexpected endpoint: {path}")
        response = table[path]
        if isinstance(response, Exception):
            raise response
        return response

    def json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        del params
        return self._lookup(self.reads, path)

    def pages(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        del params
        return self._lookup(self.listings, path)


class ScriptedPypi:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def project(self, name: str) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        assert name == "sase-core-rs"
        return self.payload


def pypi_complete(*, pin_tag: str = "0.50.0") -> dict[str, Any]:
    return {
        "releases": {
            pin_tag: [
                {
                    "filename": f"sase_core_rs-{pin_tag}.tar.gz",
                    "digests": {"sha256": "d" * 64},
                    "yanked": False,
                },
                {
                    "filename": f"sase_core_rs-{pin_tag}-manylinux_2_28_x86_64.whl",
                    "digests": {"sha256": "e" * 64},
                    "yanked": False,
                },
            ]
        }
    }


def revision_reads(pin: str = PIN, ref: str = HEAD) -> dict[str, Any]:
    del ref
    return {
        f"repos/{REPO}/contents/sase-core-revision.txt": {
            "encoding": "base64",
            "content": b64(pin + "\n"),
        }
    }


def make_facts(sase: ScriptedGithub, pypi_payload: Any = None) -> ReleaseFactsReader:
    return ReleaseFactsReader(
        repo=REPO, github=sase, pypi=ScriptedPypi(pypi_payload or {"releases": {}})
    )


def make_health(
    facts: ReleaseFactsReader,
    core: ScriptedGithub,
    artifact_text: Any = None,
) -> ReleaseHealthReader:
    return ReleaseHealthReader(facts, core_github=core, artifact_text=artifact_text)


def core_compare_reads(status: str = "ahead") -> dict[str, Any]:
    return {
        f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": status},
        f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
            "encoding": "base64",
            "content": b64(WORKFLOW_YML),
        },
    }


def run_row(
    run_id: int = 7,
    *,
    workflow: str = "ci.yml",
    sha: str = HEAD,
    branch: str = "master",
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "push",
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "run_attempt": attempt,
        "head_sha": sha,
        "head_branch": branch,
        "status": status,
        "conclusion": conclusion,
        "created_at": RUN_CREATED,
        "updated_at": RUN_CREATED,
        "run_started_at": RUN_CREATED,
        "event": event,
        "html_url": f"https://example.test/{workflow}/{run_id}",
    }


def job_row(
    job_id: int = 11,
    *,
    name: str = "Merge release PR",
    conclusion: str | None = "failure",
    check_run: int | None = 99,
) -> dict[str, Any]:
    return {
        "id": job_id,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "check_run_url": (
            f"https://api.github.com/repos/sase-org/sase-core/check-runs/{check_run}"
            if check_run is not None
            else None
        ),
    }


def canary_payload(
    os_name: str = "ubuntu-latest",
    *,
    verdict: str = "green",
    run_id: str = "7",
    attempt: str | int = "1",
    sha: str = HEAD,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "os": os_name,
        "run_id": run_id,
        "attempt": attempt,
        "sha": sha,
        "mode": "newest+exact",
        "verdict": verdict,
        "packages": [
            {
                "name": "sase",
                "expected": "0.18.0",
                "installed": "0.18.0",
                "rule": "newest",
                "ok": True,
                "reason": None,
            }
        ],
        "failing_step": None if verdict == "green" else "assert-newest-versions",
        "reason": None if verdict == "green" else "sase 0.1.0 (expected 0.18.0)",
    }


def issue_row(
    number: int = 3,
    *,
    title: str = "release-steward: install_broken (linux)",
    state: str = "open",
    body: str = "<!-- release-steward:family=install_broken identity=linux -->",
    labels: list[str] | None = None,
    opened: str = "2026-10-18T10:00:00Z",
    updated: str = "2026-10-19T10:00:00Z",
    closed: str | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": body,
        "labels": [{"name": name} for name in (labels or ["release-steward"])],
        "created_at": opened,
        "updated_at": updated,
        "closed_at": closed,
    }


# -- core-ensure ---------------------------------------------------------------


def test_core_ensure_prefers_pr_pin_over_master_pin() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(CORE_REPO, reads=core_compare_reads())
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    pr = {"source_pin": PIN, "head_sha": HEAD}
    assert health.read_core_ensure(pr, CORE_SHA)["kind"] == "pinned"
    assert f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0" in core.calls
    assert not any("contents/sase-core-revision" in call for call in sase.calls)


def test_core_ensure_falls_back_to_master_pin() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads(pin=PIN, ref=HEAD))
    core = ScriptedGithub(CORE_REPO, reads=core_compare_reads())
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure(None, HEAD)
    assert result["kind"] == "pinned"
    assert f"repos/{REPO}/contents/sase-core-revision.txt" in sase.calls


def test_core_ensure_lag_reports_newest_complete() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": "diverged"},
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result == {"kind": "core_lag", "pin": PIN, "newest_complete": "0.50.0"}


def test_core_ensure_error_is_a_ready_variant_not_an_outage() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": {"status": "weird"},
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result["kind"] == "error"
    assert "unknown status" in result["message"]


def test_core_ensure_compare_outage_is_an_error_variant() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads())
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/compare/{PIN}...v0.50.0": transport_error(
                "compare", "HTTP 500"
            ),
            f"repos/{CORE_REPO}/contents/.github/workflows/release-plz.yml": {
                "encoding": "base64",
                "content": b64(WORKFLOW_YML),
            },
        },
    )
    facts = make_facts(sase, pypi_complete())
    health = make_health(facts, core)
    result = health.read_core_ensure({"source_pin": PIN}, HEAD)
    assert result["kind"] == "error"


# -- reader accessors ----------------------------------------------------------


def test_read_ref_sha_validates_shape() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={f"repos/{REPO}/git/ref/heads/master": {"object": {"sha": HEAD}}},
    )
    assert make_facts(sase).read_ref_sha() == HEAD
    with pytest.raises(ValueError):
        make_facts(sase).read_ref_sha("not a ref")


def test_read_jobs_validates_arguments() -> None:
    sase = ScriptedGithub(REPO)
    facts = make_facts(sase)
    with pytest.raises(ValueError):
        facts.read_jobs("", 1)
    with pytest.raises(ValueError):
        facts.read_jobs("7", 0)


def test_git_file_decodes_wrapped_base64() -> None:
    long_text = "x = 1  # " + "padding " * 40
    sase = ScriptedGithub(
        REPO,
        reads={
            f"repos/{REPO}/contents/pyproject.toml": {
                "encoding": "base64",
                "content": b64(long_text),
            }
        },
    )
    assert "padding" in make_facts(sase)._git_file("pyproject.toml", HEAD)


def test_read_source_pin_reads_remote_identity() -> None:
    sase = ScriptedGithub(REPO, reads=revision_reads(pin=PIN, ref=CORE_SHA))
    assert make_facts(sase).read_source_pin(CORE_SHA) == PIN.lower()


# -- train-reader integration repairs -------------------------------------------
# Minimal root-cause fixes in the train-phase reader, proven against the
# live API during this phase and covered here so they cannot regress:
# wrapped base64 (above), flattened array pages (below), and the
# repository metadata path (below).


def test_read_repository_uses_slashless_path() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={
            f"repos/{REPO}": {
                "owner": {"login": "sase-org"},
                "name": "sase",
                "default_branch": "master",
            }
        },
    )
    assert make_facts(sase).read_repository() == {
        "owner": "sase-org",
        "name": "sase",
        "default_branch": "master",
    }


def release_raw(tag: str, draft: bool = False) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "draft": draft,
        "name": tag,
        "assets": [],
        "created_at": "2026-10-19T10:00:00Z",
        "html_url": f"https://example.test/{tag}",
    }


def test_read_releases_accepts_flattened_array_pages() -> None:
    sase = ScriptedGithub(
        REPO,
        reads={},
        listings={
            f"repos/{REPO}/releases": flat(
                [release_raw("v0.18.0"), release_raw("v0.19.0", draft=True)]
            )
        },
    )
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = datetime(2026, 10, 21, tzinfo=UTC)
    assert make_facts(sase).read_releases(since=start, until=end) == [
        {
            "tag": "v0.18.0",
            "draft": False,
            "name": "v0.18.0",
            "assets": [],
            "url": "https://example.test/v0.18.0",
        },
        {
            "tag": "v0.19.0",
            "draft": True,
            "name": "v0.19.0",
            "assets": [],
            "url": "https://example.test/v0.19.0",
        },
    ]


# -- core facts ----------------------------------------------------------------


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


# -- canary --------------------------------------------------------------------


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


# -- issues, lineage, access ----------------------------------------------------


def issues_world(
    issues: list[dict[str, Any]],
    comments: dict[int, list[dict[str, Any]]] | None = None,
) -> ScriptedGithub:
    listings: dict[str, Any] = {f"repos/{REPO}/issues": flat(issues)}
    for issue in issues:
        number = issue["number"]
        listings[f"repos/{REPO}/issues/{number}/comments"] = flat(
            (comments or {}).get(number, [])
        )
    return ScriptedGithub(REPO, reads={}, listings=listings)


def comment_row(body: str, created: str) -> dict[str, Any]:
    return {"body": body, "created_at": created}


def test_issues_parse_markers_comments_and_closed_history() -> None:
    body = "<!-- release-steward:family=install_broken identity=linux sha=abc -->"
    world = issues_world(
        [
            issue_row(3, body=body),
            issue_row(
                4,
                title="release-steward: install_broken (linux)",
                state="closed",
                body="no marker here",
                closed="2026-10-17T10:00:00Z",
            ),
        ],
        comments={
            3: [
                comment_row(
                    "<!-- release-steward:tick=run-1/1 --> +1", "2026-10-18T11:00:00Z"
                )
            ]
        },
    )
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    issues = health.read_issues()
    assert [issue["number"] for issue in issues] == [3, 4]
    assert issues[0]["identity_marker"] == "release-steward:install_broken:linux"
    assert issues[0]["sha"] == "abc"
    assert issues[0]["comments"] == [
        {"tick_identity": "run-1/1", "created_at": "2026-10-18T11:00:00Z"}
    ]
    assert issues[1]["family"] == "install_broken"
    assert issues[1]["identity_marker"] == "release-steward:install_broken:linux"
    assert issues[1]["closed_at"] == "2026-10-17T10:00:00Z"


def test_issues_without_markers_are_unknown() -> None:
    world = issues_world(
        [issue_row(5, title="Some random bug report", body="nothing machine-readable")]
    )
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    issues = health.read_issues()
    assert issues[0]["family"] == "unknown"
    assert issues[0]["identity_marker"] == ""


def test_issues_skip_pull_requests() -> None:
    row = issue_row(6)
    row["pull_request"] = {"url": "https://example.test/pr/6"}
    world = issues_world([row])
    health = make_health(make_facts(world), ScriptedGithub(CORE_REPO, reads={}))
    assert health.read_issues() == []


def test_lineage_names_oldest_open_marker() -> None:
    issues = [
        {
            "state": "open",
            "family": "core_lag",
            "identity_marker": "m:core_lag:x",
            "opened_at": "2026-10-17T10:00:00Z",
            "number": 8,
        },
        {
            "state": "open",
            "family": "install_broken",
            "identity_marker": "release-steward:install_broken:linux",
            "opened_at": "2026-10-16T10:00:00Z",
            "number": 7,
        },
        {
            "state": "closed",
            "family": "gate_red",
            "identity_marker": "release-steward:gate_red:y",
            "opened_at": "2026-10-10T10:00:00Z",
            "number": 2,
        },
    ]
    lineage = ReleaseHealthReader.derive_blocker_lineage(issues)
    assert lineage == {
        "family": "install_broken",
        "identity": "linux",
        "started_at": "2026-10-16T10:00:00Z",
        "continuous": True,
        "identity_changed": False,
    }
    assert ReleaseHealthReader.derive_blocker_lineage([]) is None


def test_access_probe_reports_read_only_scope() -> None:
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/actions/runs": {"total_count": 1, "workflow_runs": []}
        },
    )
    sase = ScriptedGithub(REPO, reads={})
    access = make_health(make_facts(sase), core).read_core_actions_access()
    assert access["readable"] is True
    assert "dispatch" in access["detail"]
    assert "write" not in access["detail"].lower().replace("workflow-dispatch", "")


def test_access_probe_failure_is_denied_not_unreadable() -> None:
    core = ScriptedGithub(
        CORE_REPO,
        reads={
            f"repos/{CORE_REPO}/actions/runs": transport_error(
                "actions/runs", "HTTP 403"
            )
        },
    )
    sase = ScriptedGithub(REPO, reads={})
    access = make_health(make_facts(sase), core).read_core_actions_access()
    assert access == {"readable": False, "detail": access["detail"]}
    assert access["detail"]


# -- composition -----------------------------------------------------------------


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


# -- real binding round trip -------------------------------------------------------


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
