"""Generation-0 abandonment for train start."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._release_watch_train_start_helpers import (
    CANDIDATE,
    SHA,
    TAG,
    VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_actions import (  # noqa: E402
    ABANDONED_TITLE_PREFIX,
    ReleaseWatchActionExecutor,
)


REPO = "sase-org/sase"


class MemoryGithub:
    """Draft release without a sealed manifest, like a fresh tag."""

    def __init__(self) -> None:
        self.release: dict[str, Any] = {
            "tag_name": TAG,
            "draft": True,
            "name": f"Release {VERSION}",
            "assets": [],
        }
        self.assets: dict[int, Any] = {}
        self.next_id = 2

    def json(self, endpoint: str, **_: Any) -> Any:
        assert endpoint == f"repos/{REPO}/releases/tags/{TAG}"
        return copy.deepcopy(self.release)

    def asset_json(self, asset_id: int, *, source: str) -> Any:
        del source
        return copy.deepcopy(self.assets[asset_id])


class FakePypi:
    def __init__(self, files: list[dict[str, Any]] | None = None) -> None:
        self.files = files or []

    def project(self, package: str) -> dict[str, Any]:
        assert package == "sase"
        if self.files:
            return {"releases": {VERSION: copy.deepcopy(self.files)}}
        return {"releases": {}}


class FakeRunner:
    def __init__(self, github: MemoryGithub, *, crash_after: str | None = None) -> None:
        self.github = github
        self.crash_after = crash_after
        self.commands: list[list[str]] = []

    def __call__(
        self, argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(argv))
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
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class SimulatedCrash(BaseException):
    """Model process death after the remote side effect but before its reply."""


def _action_request() -> dict[str, Any]:
    train = {
        "candidate_id": CANDIDATE,
        "version": VERSION,
        "tag": TAG,
        "sha": SHA,
        "generation": 0,
        "confirmed": False,
        "abandoned": False,
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
        "schema_version": 2,
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


def _abandon_action() -> dict[str, Any]:
    return {
        "action": {
            "kind": "abandon_candidate",
            "candidate_id": CANDIDATE,
            "generation": 0,
            "observation_asset": f"{CANDIDATE}.gen0.abandoned.json",
        },
        "disposition": "proposed",
        "key": f"abandon:candidate={CANDIDATE}:gen=0:asset={CANDIDATE}.gen0.abandoned.json",
        "preconditions": [
            "release.yml completed without stashing a manifest",
            "zero PyPI files",
        ],
        "argv": [],
        "reason": "burn version with broken workflow at tag",
    }


def _action_decision(action: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "primary": {"kind": "waiting", "reason": "broken workflow at tag"},
        "details": "release.yml completed without stashing a manifest",
        "evidence": [],
        "blocker_started_at": None,
        "blocker_duration_uncertain": False,
        "train_action": copy.deepcopy(action),
        "escalation": None,
        "secondary": [],
        "process_exit": 0,
    }


def test_gen0_abandonment_writes_observation_and_prefixes_title() -> None:
    github = MemoryGithub()
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (_action_request(), _action_decision(_abandon_action())),
        runner=FakeRunner(github),
        github=github,
        pypi=FakePypi(),
        run_id=500,
        attempt=1,
    )
    result = executor.execute(
        _action_decision(_abandon_action()), _action_request(), live=True
    )
    assert result["train_action"]["disposition"] == "executed"
    assert github.release["assets"] == [
        {"id": 2, "name": "candidate-gen0-abandoned-run500-attempt1.json"}
    ]
    observation = github.assets[2]
    assert observation["candidate_id"] == CANDIDATE
    assert observation["generation"] == 0
    assert observation["kind"] == "abandoned"
    assert github.release["name"] == f"{ABANDONED_TITLE_PREFIX}Release {VERSION}"


def test_gen0_abandonment_recovers_after_upload_crash() -> None:
    github = MemoryGithub()
    executor = ReleaseWatchActionExecutor(
        recheck=lambda: (_action_request(), _action_decision(_abandon_action())),
        runner=FakeRunner(github, crash_after="upload"),
        github=github,
        pypi=FakePypi(),
        run_id=500,
        attempt=1,
    )
    with pytest.raises(SimulatedCrash):
        executor.execute(
            _action_decision(_abandon_action()), _action_request(), live=True
        )
    assert len(github.release["assets"]) == 1
    assert github.release["name"] == f"Release {VERSION}"

    recovered = dict(_action_request())
    recovered["snapshot"]["trains"]["value"][0]["abandoned"] = True
    recovery = ReleaseWatchActionExecutor(
        recheck=lambda: (recovered, _action_decision(None)),
        runner=FakeRunner(github),
        github=github,
        pypi=FakePypi(),
        run_id=501,
        attempt=1,
    )
    result = recovery.execute(_action_decision(None), recovered, live=True)
    assert len(github.release["assets"]) == 1
    assert github.release["name"] == f"{ABANDONED_TITLE_PREFIX}Release {VERSION}"
    assert result["train_action"]["disposition"] == "executed"
