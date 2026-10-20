"""Restart-safe execution of release-steward train actions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_actions import (  # noqa: E402
    ABANDONED_TITLE_PREFIX,
    ReleaseWatchActionExecutor,
)


REPO = "sase-org/sase"
CANDIDATE = "candidate-0123456789abcdef0123456789abcdef"
TAG = "v0.51.0"
SHA = "a" * 40


def request(*, abandoned: bool = False) -> dict[str, Any]:
    train = {
        "candidate_id": CANDIDATE,
        "version": "0.51.0",
        "tag": TAG,
        "sha": SHA,
        "generation": 2,
        "confirmed": False,
        "abandoned": abandoned,
        "pre_train_legacy": False,
        "manifest_mismatch": False,
        "evidence_mismatch": False,
        "py_files_present": 0,
        "py_files_expected": 2,
        "py_digest_conflict": False,
        "py_extra_files": False,
        "confirmation_complete": False,
    }
    return {
        "schema_version": 1,
        "observed_at": "2026-10-20T12:00:00Z",
        "policy": {"tick_identity": "run-500/attempt-1"},
        "snapshot": {
            "repository": {
                "status": "ready",
                "value": {
                    "owner": "sase-org",
                    "name": "sase",
                    "default_branch": "master",
                },
            },
            "trains": {"status": "ready", "value": [train]},
            "candidate": {"status": "ready", "value": None},
            "pypi": {
                "status": "ready",
                "value": {"sase": {"package": "sase", "files": []}},
            },
        },
    }


def abandon_action() -> dict[str, Any]:
    return {
        "action": {
            "kind": "abandon_candidate",
            "candidate_id": CANDIDATE,
            "generation": 2,
            "observation_asset": f"{CANDIDATE}.gen2.abandoned.json",
        },
        "disposition": "proposed",
        "key": f"abandon:candidate={CANDIDATE}:gen=2:asset={CANDIDATE}.gen2.abandoned.json",
        "preconditions": ["zero PyPI files"],
        "argv": [],
        "reason": "unrecoverable red candidate",
    }


def decision(action: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "primary": {"kind": "qualify_red", "signature": "n1", "recovered": False},
        "details": "qualification retries exhausted",
        "evidence": [],
        "blocker_started_at": None,
        "blocker_duration_uncertain": False,
        "train_action": copy.deepcopy(action),
        "escalation": None,
        "secondary": [],
        "process_exit": 0,
    }


class FakePypi:
    def __init__(self, files: list[dict[str, Any]] | None = None) -> None:
        self.files = files or []
        self.reads = 0

    def project(self, package: str) -> dict[str, Any]:
        assert package == "sase"
        self.reads += 1
        return {"releases": {"0.51.0": copy.deepcopy(self.files)} if self.files else {}}


class MemoryGithub:
    def __init__(self) -> None:
        self.release: dict[str, Any] = {
            "tag_name": TAG,
            "draft": True,
            "name": "Release 0.51.0",
            "assets": [{"id": 1, "name": "candidate-manifest.json"}],
        }
        self.assets: dict[int, Any] = {
            1: {
                "candidate_id": CANDIDATE,
                "generation": 2,
                "version": "0.51.0",
                "tag": TAG,
                "sha": SHA,
                "observations": [],
            }
        }
        self.next_id = 2

    def json(self, endpoint: str, **_: Any) -> Any:
        assert endpoint == f"repos/{REPO}/releases/tags/{TAG}"
        return copy.deepcopy(self.release)

    def asset_json(self, asset_id: int, *, source: str) -> Any:
        del source
        return copy.deepcopy(self.assets[asset_id])


class SimulatedCrash(BaseException):
    """Model process death after the remote side effect but before its reply."""


class FakeRunner:
    def __init__(self, github: MemoryGithub, *, crash_after: str | None = None) -> None:
        self.github = github
        self.crash_after = crash_after
        self.commands: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append((list(argv), dict(kwargs)))
        if argv[0] == sys.executable:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=kwargs["timeout"],
                env=kwargs.get("env"),
            )
        if argv[:3] == ["gh", "release", "upload"]:
            path = Path(argv[-1])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.github.assets[self.github.next_id] = payload
            self.github.release["assets"].append(
                {"id": self.github.next_id, "name": path.name}
            )
            self.github.next_id += 1
            if self.crash_after == "upload":
                raise SimulatedCrash()
        elif argv[:3] == ["gh", "release", "edit"]:
            self.github.release["name"] = argv[argv.index("--title") + 1]
            if self.crash_after == "title":
                raise SimulatedCrash()
        else:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_read_only_execution_never_rechecks_or_mutates() -> None:
    assert (ROOT / "tools" / "_release_watch_actions.py").is_file()
    calls: list[Any] = []
    expected = decision(
        {
            "action": {"kind": "dispatch_publish_metadata"},
            "disposition": "proposed",
            "key": "metadata:pr=1:head=x:pin=y",
            "preconditions": [],
            "argv": ["gh", "workflow", "run", "publish.yml"],
            "reason": "refresh metadata",
        }
    )
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (_ for _ in ()).throw(AssertionError("must not recheck")),
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    result = executor.execute(expected, request(), live=False)
    assert result == expected
    assert calls == []


def test_dispatch_uses_rust_argv_after_matching_fresh_decision() -> None:
    action = {
        "action": {"kind": "dispatch_publish_metadata"},
        "disposition": "proposed",
        "key": "metadata:pr=42:head=" + SHA + ":pin=" + "b" * 40,
        "preconditions": ["release PR is stale"],
        "argv": ["gh", "workflow", "run", "publish.yml"],
        "reason": "refresh release-please metadata",
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(action)),
        runner=runner,
    )
    result = executor.execute(decision(action), request(), live=True)
    assert result["train_action"]["disposition"] == "executed"
    assert calls[0][0] == action["argv"]
    assert calls[0][1]["env"]["GH_REPO"] == REPO


def test_changed_action_is_suppressed_without_write() -> None:
    planned = {
        "action": {"kind": "merge_release_pr", "pr_number": 42, "head_sha": SHA},
        "disposition": "proposed",
        "key": f"merge:pr=42:head={SHA}",
        "preconditions": ["same release PR head"],
        "argv": ["gh", "pr", "merge", "42", "--merge", "--match-head-commit", SHA],
        "reason": "release PR is ready",
    }
    changed_sha = "c" * 40
    changed = {
        **planned,
        "action": {
            "kind": "merge_release_pr",
            "pr_number": 42,
            "head_sha": changed_sha,
        },
        "key": f"merge:pr=42:head={changed_sha}",
        "argv": [
            "gh",
            "pr",
            "merge",
            "42",
            "--merge",
            "--match-head-commit",
            changed_sha,
        ],
    }
    calls: list[Any] = []
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(changed)),
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    result = executor.execute(decision(planned), request(), live=True)
    assert result["train_action"]["disposition"] == "suppressed"
    assert "key changed" in result["train_action"]["reason"]
    assert calls == []


def test_core_cut_targets_core_repository() -> None:
    action = {
        "action": {"kind": "dispatch_core_cut", "source_pin": SHA},
        "disposition": "proposed",
        "key": f"core-cut:pin={SHA}",
        "preconditions": ["no cut covers pin"],
        "argv": ["gh", "workflow", "run", "release-plz.yml", "-f", "dry_run=false"],
        "reason": "cut pinned core",
    }
    calls: list[tuple[list[str], dict[str, Any]]] = []
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(action)),
        runner=lambda argv, **kwargs: (
            calls.append((argv, kwargs))
            or subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        ),
    )
    result = executor.execute(decision(action), request(), live=True)
    assert result["train_action"]["disposition"] == "executed"
    assert calls[0][1]["env"]["GH_REPO"] == "sase-org/sase-core"


@pytest.mark.parametrize(
    ("action", "argv"),
    [
        (
            {
                "kind": "dispatch_release",
                "tag": TAG,
                "sha": SHA,
                "mode": "resume",
                "generation": 2,
            },
            [
                "gh",
                "workflow",
                "run",
                "release.yml",
                "--ref",
                TAG,
                "-f",
                "mode=resume",
            ],
        ),
        (
            {
                "kind": "rerun_failed_jobs",
                "run_id": "900",
                "attempt": 1,
                "job_ids": ["test"],
            },
            ["gh", "run", "rerun", "900", "--failed"],
        ),
    ],
)
def test_release_and_rerun_actions_use_the_selected_argv(
    action: dict[str, Any], argv: list[str]
) -> None:
    wrapped = {
        "action": action,
        "disposition": "proposed",
        "key": "fixture-action",
        "preconditions": ["fresh policy approved"],
        "argv": argv,
        "reason": "fixture action",
    }
    calls: list[list[str]] = []
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(wrapped)),
        runner=lambda command, **kwargs: (
            calls.append(command)
            or subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        ),
    )
    result = executor.execute(decision(wrapped), request(), live=True)
    assert result["train_action"]["disposition"] == "executed"
    assert calls == [argv]


def test_uncertain_acknowledgement_is_reported_without_retry() -> None:
    wrapped = {
        "action": {"kind": "dispatch_publish_metadata"},
        "disposition": "proposed",
        "key": "metadata:pr=42:head=x:pin=y",
        "preconditions": [],
        "argv": ["gh", "workflow", "run", "publish.yml"],
        "reason": "refresh metadata",
    }
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="request timed out"
        )

    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(wrapped)),
        runner=runner,
    )
    result = executor.execute(decision(wrapped), request(), live=True)
    assert result["primary"]["kind"] == "watcher_broken"
    assert "uncertain acknowledgement" in result["details"]
    assert result["train_action"]["disposition"] == "suppressed"
    assert len(calls) == 1


def test_tick_executes_at_most_one_train_action_and_one_escalation() -> None:
    train = {
        "action": {"kind": "dispatch_publish_metadata"},
        "disposition": "proposed",
        "key": "metadata:pr=42:head=x:pin=y",
        "preconditions": ["release PR is stale"],
        "argv": ["gh", "workflow", "run", "publish.yml"],
        "reason": "refresh metadata",
    }
    escalation = {
        "operation": {
            "kind": "open",
            "family": "install_broken",
            "title": "release-steward: install_broken (linux)",
            "labels": ["release-steward"],
            "body": "immediate install_broken linux",
            "identity_marker": "release-steward:install_broken:linux",
        },
        "disposition": "proposed",
        "key": "esc-open:install_broken:release-steward:install_broken:linux",
        "severity": "immediate",
    }
    first_decision = decision(train)
    first_decision["escalation"] = copy.deepcopy(escalation)
    current_decision = decision(train)
    current_decision["escalation"] = copy.deepcopy(escalation)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class EmptyIssues:
        def pages(self, endpoint: str, **_: Any) -> list[Any]:
            assert endpoint == f"repos/{REPO}/issues"
            return []

    def train_runner(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def issue_runner(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), current_decision),
        runner=train_runner,
        issue_runner=issue_runner,
        github=EmptyIssues(),
    )
    result = executor.execute(first_decision, request(), live=True)
    assert result["train_action"]["disposition"] == "executed"
    assert result["escalation"]["disposition"] == "executed"
    assert len(calls) == 2
    assert calls[0][0] == train["argv"]
    assert calls[1][0][0:2] == ["gh", "api"]


@pytest.mark.parametrize("crash_after", ["upload", "title"])
def test_abandonment_restarts_without_duplicate_observation_or_title(
    tmp_path: Path, crash_after: str
) -> None:
    github = MemoryGithub()
    pypi = FakePypi()
    runner = FakeRunner(github, crash_after=crash_after)
    first = request(abandoned=False)
    first_decision = decision(abandon_action())
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (first, first_decision),
        runner=runner,
        github=github,
        pypi=pypi,
        run_id=500,
        attempt=1,
    )
    with pytest.raises(SimulatedCrash):
        executor.execute(first_decision, first, live=True)

    assert len(github.release["assets"]) == 2
    assert github.release["assets"][1]["name"] == (
        "candidate-gen2-abandoned-run500-attempt1.json"
    )
    if crash_after == "upload":
        assert github.release["name"] == "Release 0.51.0"
    else:
        assert github.release["name"] == f"{ABANDONED_TITLE_PREFIX}Release 0.51.0"

    recovered_request = request(abandoned=True)
    recovered_decision = decision(None)
    recovery = ReleaseWatchActionExecutor(
        recheck=lambda: (recovered_request, recovered_decision),
        runner=FakeRunner(github),
        github=github,
        pypi=pypi,
        run_id=501,
        attempt=1,
    )
    result = recovery.execute(recovered_decision, recovered_request, live=True)
    assert len(github.release["assets"]) == 2
    assert github.release["name"] == f"{ABANDONED_TITLE_PREFIX}Release 0.51.0"
    if crash_after == "upload":
        assert result["train_action"]["disposition"] == "executed"
    assert pypi.reads >= 2


def test_public_files_appearing_refuses_abandonment_before_any_write() -> None:
    github = MemoryGithub()
    runner = FakeRunner(github)
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (request(), decision(abandon_action())),
        runner=runner,
        github=github,
        pypi=FakePypi([{"filename": "sase-0.51.0-py3-none-any.whl"}]),
        run_id=500,
        attempt=1,
    )
    result = executor.execute(decision(abandon_action()), request(), live=True)
    assert result["primary"]["kind"] == "watcher_broken"
    assert "public PyPI files" in result["details"]
    assert github.release["name"] == "Release 0.51.0"
    assert len(github.release["assets"]) == 1
    assert not any("gh" == command[0][0] for command in runner.commands)
