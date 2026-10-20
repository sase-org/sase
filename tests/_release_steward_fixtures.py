"""Complete release-steward snapshot fixtures for policy and later phases.

Fact reads use ``status=ready|absent|unreadable``. Unreadable required
facts cannot authorize an action; known-missing optional facts use
``absent`` or ``ready`` with ``value: null``.
"""

from __future__ import annotations

from typing import Any

HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PIN = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
CORE_VERSION = "0.50.0"
NOON = "2026-10-19T12:00:00Z"
SCHEMA = 1


def ready(value: Any) -> dict[str, Any]:
    return {"status": "ready", "value": value}


def absent(reason: str) -> dict[str, Any]:
    return {"status": "absent", "reason": reason}


def unreadable(source: str, message: str, remedy: str) -> dict[str, Any]:
    return {
        "status": "unreadable",
        "source": source,
        "message": message,
        "remedy": remedy,
    }


def success_check(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "conclusion": "success",
        "is_test": True,
        "is_lint": False,
        "url": f"https://example.test/check/{name}",
    }


def green_gate_run(sha: str) -> dict[str, Any]:
    return {
        "workflow": "ci.yml",
        "run_id": "gate-1",
        "attempt": 1,
        "ref_name": "master",
        "sha": sha,
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {
                "id": "job-test",
                "name": "tests",
                "conclusion": "success",
                "is_test": True,
                "is_lint": False,
                "attempt": 1,
            },
            {
                "id": "job-lint",
                "name": "lint",
                "conclusion": "success",
                "is_test": False,
                "is_lint": True,
                "attempt": 1,
            },
        ],
        "started_at": NOON,
        "updated_at": NOON,
        "event": "push",
        "url": "https://example.test/gate-1",
    }


def passing_canary(member: str) -> dict[str, Any]:
    return {
        "member": member,
        "run_id": f"canary-{member}",
        "attempt": 1,
        "sha": HEAD,
        "verdict": "pass",
        "packages": ["sase"],
        "scheduled": True,
    }


def releasable_snapshot() -> dict[str, Any]:
    return {
        "repository": ready(
            {
                "owner": "sase-org",
                "name": "sase",
                "default_branch": "master",
            }
        ),
        "master": ready(
            {
                "sha": HEAD,
                "gate_run": green_gate_run(HEAD),
                "expected_required_checks": [
                    {"name": "tests", "source": "branch protection"},
                    {"name": "lint", "source": "branch protection"},
                ],
                "expected_checks_source": "branch protection",
                "expected_checks_readable": True,
            }
        ),
        "release_pr": ready(
            {
                "number": 42,
                "head_sha": HEAD,
                "source_pin": PIN,
                "exact_public_core_pin": CORE_VERSION,
                "labels": ["autorelease: pending"],
                "checks": [success_check("tests"), success_check("lint")],
                "merge_history": [],
                "stale_head": False,
                "pin_changed": False,
                "merged": False,
                "url": "https://github.com/sase-org/sase/pull/42",
                "core_smoke": success_check("release-core-floor-smoke"),
            }
        ),
        "tags": ready([]),
        "releases": ready([]),
        "pypi": ready(
            {
                "sase": {"package": "sase", "files": []},
                "core": {"package": "sase-core-rs", "files": []},
            }
        ),
        "trains": ready([]),
        "workflows": ready({"release_yml": [], "publish_yml": []}),
        "core": ready(
            {
                "master_ci": green_gate_run(PIN),
                "cuts": [],
            }
        ),
        "canary": ready(
            {
                "linux": passing_canary("linux"),
                "macos": passing_canary("macos"),
            }
        ),
        "candidate": ready(None),
        "core_ensure": ready(
            {
                "kind": "pinned",
                "version": CORE_VERSION,
                "files": [
                    "sase_core_rs-0.50.0.tar.gz",
                    "sase_core_rs-0.50.0-cp312-abi3-manylinux.whl",
                ],
            }
        ),
        "issues": ready([]),
        "core_actions_access": ready({"readable": True, "detail": "read ok"}),
        "merge_history": ready([]),
        "blocker_lineage": ready(None),
    }


def releasable_request() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "observed_at": NOON,
        "policy": {
            "merge_authority_enabled": True,
            "observe_only": True,
            "tick_identity": "run-1/attempt-1",
            "cadence": {
                "kind": "daily",
                "merge_after_hour_utc": 9,
                "max_merges_per_utc_day": 1,
            },
        },
        "snapshot": releasable_snapshot(),
    }
