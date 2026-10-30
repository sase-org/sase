"""Shared public fixtures for release watch health tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from _release_core import CORE_REPO
from _release_watch_facts import ReleaseFactsError, ReleaseFactsReader
from _release_watch_health import ReleaseHealthReader
from _release_watch_transport import ReleaseTransportError

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
                    "filename": (
                        f"sase_core_rs-{pin_tag}-cp312-abi3-manylinux_2_28_x86_64.whl"
                    ),
                    "digests": {"sha256": "e" * 64},
                    "yanked": False,
                },
            ]
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
