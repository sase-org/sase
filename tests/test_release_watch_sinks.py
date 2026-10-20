"""Idempotent issue operations for the release-steward escalation sink."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_sinks import ReleaseWatchIssueSink  # noqa: E402


REPO = "sase-org/sase"
MARKER = "release-steward:install_broken:linux"


class MemoryGithub:
    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.comments: dict[int, list[dict[str, str]]] = {}

    def pages(self, endpoint: str, **_: Any) -> list[Any]:
        if endpoint == f"repos/{REPO}/issues":
            return self.issues
        prefix = f"repos/{REPO}/issues/"
        if endpoint.startswith(prefix) and endpoint.endswith("/comments"):
            number = int(endpoint[len(prefix) : -len("/comments")])
            return self.comments.setdefault(number, [])
        raise AssertionError(f"unexpected pages endpoint: {endpoint}")

    def json(self, endpoint: str, **_: Any) -> Any:
        prefix = f"repos/{REPO}/issues/"
        assert endpoint.startswith(prefix)
        number = int(endpoint[len(prefix) :])
        return next(issue for issue in self.issues if issue["number"] == number)


class MemoryRunner:
    def __init__(self, github: MemoryGithub) -> None:
        self.github = github
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        endpoint = argv[4]
        method = argv[argv.index("--method") + 1]
        payload = json.loads(kwargs["input"])
        if method == "POST" and endpoint == f"repos/{REPO}/issues":
            number = max((item["number"] for item in self.github.issues), default=0) + 1
            self.github.issues.append(
                {
                    "number": number,
                    "state": "open",
                    "title": payload["title"],
                    "body": payload["body"],
                    "labels": [{"name": name} for name in payload["labels"]],
                }
            )
        elif method == "POST" and endpoint.endswith("/comments"):
            number = int(endpoint.split("/")[-2])
            self.github.comments.setdefault(number, []).append(
                {"body": payload["body"]}
            )
        elif method == "PATCH":
            number = int(endpoint.split("/")[-1])
            issue = next(
                item for item in self.github.issues if item["number"] == number
            )
            issue["state"] = payload["state"]
        else:
            raise AssertionError(f"unexpected mutation: {method} {endpoint}")
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")


def issue(
    number: int = 7, *, identity: str = "linux", state: str = "open"
) -> dict[str, Any]:
    return {
        "number": number,
        "state": state,
        "title": f"release-steward: install_broken ({identity})",
        "body": (
            "immediate install_broken "
            f"<!-- release-steward:family=install_broken identity={identity} -->"
        ),
        "labels": [{"name": "release-steward"}],
    }


def request(*, issue_row: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = [] if issue_row is None else [issue_row]
    return {
        "observed_at": "2026-10-20T12:00:00Z",
        "snapshot": {
            "issues": {"status": "ready", "value": rows},
            "candidate": {
                "status": "ready",
                "value": {"candidate_id": "candidate-abc", "generation": 3},
            },
            "trains": {
                "status": "ready",
                "value": [{"candidate_id": "candidate-abc", "version": "0.51.0"}],
            },
            "release_pr": {
                "status": "ready",
                "value": {"source_pin": "b" * 40, "head_sha": "a" * 40},
            },
            "master": {"status": "ready", "value": {"sha": "c" * 40}},
        },
    }


def decision() -> dict[str, Any]:
    return {
        "primary": {"kind": "install_broken", "member": "linux"},
        "secondary": [],
        "blocker_started_at": "2026-10-19T12:00:00Z",
        "evidence": [
            {"kind": "canary", "identity": "run-5", "url": "https://example.test/run/5"}
        ],
    }


def open_operation() -> dict[str, Any]:
    return {
        "kind": "open",
        "family": "install_broken",
        "title": "release-steward: install_broken (linux)",
        "labels": ["release-steward"],
        "body": "immediate install_broken linux",
        "identity_marker": MARKER,
    }


def test_open_writes_fixed_label_and_machine_readable_context() -> None:
    assert (ROOT / "tools" / "_release_watch_sinks.py").is_file()
    github = MemoryGithub()
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    outcome, reason = sink.execute(
        {"operation": open_operation(), "disposition": "proposed"},
        request(),
        decision(),
        live=True,
    )
    assert outcome == "executed"
    assert "opened" in reason
    opened = github.issues[0]
    assert opened["labels"] == [{"name": "release-steward"}]
    assert "release-steward:family=install_broken identity=linux" in opened["body"]
    assert "candidate=candidate-abc" in opened["body"]
    assert f"pin={'b' * 40}" in opened["body"]
    assert f"sha={'a' * 40}" in opened["body"]
    assert "observed_at=2026-10-20T12:00:00Z" in opened["body"]
    assert runner.calls[0][1]["env"]["GH_REPO"] == REPO


def test_open_deduplicates_by_identity_marker_not_title() -> None:
    unrelated = issue(identity="macos")
    github = MemoryGithub([unrelated])
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    outcome, _ = sink.execute(
        {"operation": open_operation(), "disposition": "proposed"},
        request(),
        decision(),
        live=True,
    )
    assert outcome == "executed"
    assert len(github.issues) == 2
    assert len(runner.calls) == 1


def test_matching_open_issue_is_already_satisfied() -> None:
    github = MemoryGithub([issue()])
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    outcome, _ = sink.execute(
        {"operation": open_operation(), "disposition": "proposed"},
        request(),
        decision(),
        live=True,
    )
    assert outcome == "already_satisfied"
    assert runner.calls == []


def test_comment_uses_tick_marker_and_reexecution_does_not_duplicate() -> None:
    existing = issue()
    row = {
        "number": 7,
        "state": "open",
        "family": "install_broken",
        "identity_marker": MARKER,
        "labels": ["release-steward"],
    }
    github = MemoryGithub([existing])
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    escalation = {
        "operation": {
            "kind": "comment",
            "family": "install_broken",
            "issue_number": 7,
            "body": "+1 blocked 24h install_broken linux",
            "tick_identity": "run-500/attempt-1",
        },
        "disposition": "proposed",
    }
    req = request(issue_row=row)
    first, _ = sink.execute(escalation, req, decision(), live=True)
    second, _ = sink.execute(escalation, req, decision(), live=True)
    assert first == "executed"
    assert second == "already_satisfied"
    assert len(runner.calls) == 1
    body = github.comments[7][0]["body"]
    assert "release-steward:tick=run-500/attempt-1" in body
    assert "release-steward:family=install_broken identity=linux" in body


def test_close_leaves_an_issue_with_a_changed_identity_open() -> None:
    old = issue(identity="macos")
    github = MemoryGithub([old])
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    row = {
        "number": 7,
        "state": "open",
        "family": "install_broken",
        "identity_marker": MARKER,
        "labels": ["release-steward"],
    }
    outcome, reason = sink.execute(
        {
            "operation": {
                "kind": "close",
                "family": "install_broken",
                "issue_number": 7,
                "reason": "state recovered",
            },
            "disposition": "proposed",
        },
        request(issue_row=row),
        decision(),
        live=True,
    )
    assert outcome == "suppressed"
    assert "identity changed" in reason
    assert old["state"] == "open"
    assert runner.calls == []


def test_observe_only_issue_sink_executes_no_reads_or_writes() -> None:
    github = MemoryGithub()
    runner = MemoryRunner(github)
    sink = ReleaseWatchIssueSink(github=github, runner=runner)
    outcome, _ = sink.execute(
        {"operation": open_operation(), "disposition": "proposed"},
        request(),
        decision(),
        live=False,
    )
    assert outcome == "proposed"
    assert github.issues == []
    assert runner.calls == []
