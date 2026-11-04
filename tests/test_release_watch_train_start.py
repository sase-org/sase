"""Train start at a fresh tag: reader facts, generation-0 abandonment, and walk.

A fresh tag with an unsealed draft is its own train fact instead of reading
as ``WATCHER_BROKEN``. The steward dispatches ``release.yml mode=release``
once, burns a tag whose run completed without stashing a manifest, and
resumes (never re-releases) a sealed publishable generation with no PyPI
files.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tests._release_candidate_tool_helpers import dists, load_tool, seal_kwargs
from tests._release_steward_fixtures import releasable_request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_actions import (  # noqa: E402
    ABANDONED_TITLE_PREFIX,
    ReleaseWatchActionExecutor,
)
from _release_watch_facts import ReleaseFactsReader  # noqa: E402


SHA = "b" * 40
SEALED_SHA = "c" * 40
VERSION = "0.19.0"
TAG = f"v{VERSION}"
CANDIDATE = f"unsealed:{TAG}:{SHA}"
REPO = "sase-org/sase"


class FakeGithub:
    def __init__(self, assets: dict[int, object] | None = None) -> None:
        self.assets = assets or {}

    def json(self, endpoint: str, *, params: dict[str, object] | None = None) -> object:
        del params
        if endpoint.endswith("contents/.github/workflows/release.yml"):
            return {"encoding": "base64", "content": "IyB3b3JrZmxvdwo="}
        raise AssertionError(f"unexpected GitHub endpoint: {endpoint}")

    def asset_json(self, asset_id: int, *, source: str) -> object:
        del source
        return self.assets[asset_id]


def _fresh_context(
    *,
    draft: bool = True,
    pypi_files: list[dict[str, Any]] | None = None,
    release_runs: list[dict[str, Any]] | None = None,
    merged_head_sha: str | None = SHA,
    extra_assets: list[dict[str, Any]] | None = None,
    asset_payloads: dict[int, Any] | None = None,
    release_exists: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Drive ``_train_context`` over one fresh-tag fact set.

    No sealed manifest asset exists, so the tag is either its own fresh
    train fact or a manifest mismatch, depending on the arguments.
    """
    github = FakeGithub(dict(asset_payloads or {}))
    reader = ReleaseFactsReader(github=github)
    tags = [{"name": TAG, "peeled_sha": SHA, "has_manifest": False}]
    if release_exists:
        wire_assets = [
            {
                "id": item["id"],
                "name": item["name"],
                "kind": "abandoned",
                "generation": 0,
            }
            for item in (extra_assets or [])
        ]
        release_wire: dict[str, Any] | None = {
            "tag": TAG,
            "draft": draft,
            "name": f"Release {VERSION}",
            "url": f"https://github.com/sase-org/sase/releases/tag/{TAG}",
            "assets": wire_assets,
        }
        release_raw: dict[str, Any] = {
            "assets": [
                {"id": item["id"], "name": item["name"]}
                for item in (extra_assets or [])
            ]
        }
        releases = [(release_wire, release_raw)]
    else:
        releases = []
    pypi = {
        "sase": {"package": "sase", "files": list(pypi_files or [])},
        "core": {"package": "sase-core-rs", "files": []},
    }
    workflows = {
        "release_yml": list(release_runs or []),
        "publish_yml": [],
    }
    return reader._train_context(
        tags, releases, pypi, workflows, merged_head_sha=merged_head_sha
    )


def _release_run(
    *, status: str, conclusion: str | None = None, sha: str = SHA
) -> dict[str, Any]:
    return {
        "workflow": "release.yml",
        "run_id": "release-1",
        "attempt": 1,
        "ref_name": TAG,
        "sha": sha,
        "status": status,
        "conclusion": conclusion,
        "jobs": [],
        "started_at": "2026-10-20T12:00:00Z",
        "updated_at": "2026-10-20T12:00:00Z",
        "event": "workflow_dispatch",
        "url": "https://example.test/release-1",
    }


def test_fresh_unsealed_tag_is_its_own_fact() -> None:
    trains, candidate = _fresh_context()
    assert len(trains) == 1
    train = trains[0]
    assert train["candidate_id"] == CANDIDATE
    assert train["generation"] == 0
    assert train["manifest_mismatch"] is False
    assert train["abandoned"] is False
    assert train["py_files_present"] == 0
    assert candidate is None


def test_fresh_tag_without_merged_head_knowledge_is_still_fresh() -> None:
    trains, _candidate = _fresh_context(merged_head_sha=None)
    assert trains[0]["manifest_mismatch"] is False


def test_fresh_tag_with_pypi_files_stays_mismatch() -> None:
    trains, _candidate = _fresh_context(
        pypi_files=[
            {
                "filename": f"sase-{VERSION}-py3-none-any.whl",
                "version": VERSION,
                "sha256": "d" * 64,
                "yanked": False,
            }
        ]
    )
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_head_mismatch_stays_mismatch() -> None:
    trains, _candidate = _fresh_context(merged_head_sha="d" * 40)
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_without_draft_release_stays_mismatch() -> None:
    trains, _candidate = _fresh_context(draft=False)
    assert trains[0]["manifest_mismatch"] is True
    trains, _candidate = _fresh_context(release_exists=False)
    assert trains[0]["manifest_mismatch"] is True


def test_fresh_tag_with_burned_observation_is_abandoned() -> None:
    name = "candidate-gen0-abandoned-run500-attempt1.json"
    trains, _candidate = _fresh_context(
        extra_assets=[{"id": 7, "name": name}],
        asset_payloads={
            7: {
                "asset": name,
                "kind": "abandoned",
                "generation": 0,
                "candidate_id": CANDIDATE,
                "run_id": 500,
                "attempt": 1,
                "verdict": "abandoned",
            }
        },
    )
    assert trains[0]["manifest_mismatch"] is False
    assert trains[0]["abandoned"] is True


def test_fresh_tag_with_foreign_abandoned_observation_is_not_abandoned() -> None:
    name = "candidate-gen0-abandoned-run500-attempt1.json"
    trains, _candidate = _fresh_context(
        extra_assets=[{"id": 7, "name": name}],
        asset_payloads={
            7: {
                "asset": name,
                "kind": "abandoned",
                "generation": 0,
                "candidate_id": "unsealed:v9.9.9:" + "e" * 40,
                "run_id": 500,
                "attempt": 1,
                "verdict": "abandoned",
            }
        },
    )
    assert trains[0]["abandoned"] is False


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


def _sealed_manifest() -> dict[str, Any]:
    tool = load_tool()
    return tool.seal_manifest(
        **seal_kwargs(
            version=VERSION,
            tag=f"refs/tags/{TAG}",
            sha=SEALED_SHA,
            dists=dists(VERSION),
            builder_revision=(
                "sase-org/sase/.github/workflows/release.yml@refs/tags/" + TAG
            ),
        )
    )


def _sealed_context(
    manifest: dict[str, Any],
    *,
    draft: bool = True,
    pypi_files: list[dict[str, Any]] | None = None,
    release_runs: list[dict[str, Any]] | None = None,
    confirmation: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Drive ``_train_context`` over one sealed-generation fact set."""
    rows = [{"id": 1, "name": "candidate-manifest.json"}]
    for index, dist in enumerate(manifest["dists"], 2):
        rows.append({"id": index, "name": Path(dist["asset"].split("/", 1)[1]).name})
    wires = [
        {
            "id": row["id"],
            "name": row["name"],
            "kind": "manifest" if row["id"] == 1 else "other",
            "generation": 0,
        }
        for row in rows
    ]
    payloads: dict[int, Any] = {1: manifest}
    if confirmation:
        name = "candidate-gen1-confirmation-run17-attempt1.json"
        rows.append({"id": 9, "name": name})
        wires.append({"id": 9, "name": name, "kind": "confirmation", "generation": 1})
        payloads[9] = {
            "asset": name,
            "kind": "confirmation",
            "generation": 1,
            "candidate_id": manifest["candidate_id"],
            "run_id": 17,
            "attempt": 1,
            "verdict": "pass",
        }
    for row in rows[1:]:
        payloads.setdefault(row["id"], {})
    github = FakeGithub(payloads)
    reader = ReleaseFactsReader(github=github)
    release_wire = {
        "tag": TAG,
        "draft": draft,
        "name": f"Release {VERSION}",
        "url": f"https://github.com/sase-org/sase/releases/tag/{TAG}",
        "assets": wires,
    }
    if pypi_files is None:
        pypi_files = [
            {
                "filename": dist["filename"],
                "version": VERSION,
                "sha256": dist["sha256"],
                "yanked": False,
            }
            for dist in manifest["dists"]
        ]
    pypi = {
        "sase": {"package": "sase", "files": list(pypi_files)},
        "core": {"package": "sase-core-rs", "files": []},
    }
    workflows = {
        "release_yml": list(release_runs or []),
        "publish_yml": [],
    }
    return reader._train_context(
        [{"name": TAG, "peeled_sha": SEALED_SHA, "has_manifest": True}],
        [(release_wire, {"assets": rows})],
        pypi,
        workflows,
    )


def _sealed_release_run() -> dict[str, Any]:
    run = _release_run(status="completed", conclusion="success", sha=SEALED_SHA)
    run["run_id"] = "17"
    return run


def _publishable_eval(candidate_id: str, generation: int) -> dict[str, Any]:
    """A publishable evaluator result for a sealed generation.

    The real qualifier evidence lives in the release workflow, so the walk
    simulates the passing-evidence outcome the reader would emit; the fact
    shapes around it all come from the real reader.
    """
    return {
        "candidate_id": candidate_id,
        "generation": generation,
        "version": VERSION,
        "publishable": True,
        "rerun_eligible": False,
        "rerun_reason": "",
        "clauses": [
            {
                "name": "source_and_version_identity_match",
                "ok": True,
                "detail": "ok",
            },
            {
                "name": "public_dependency_contract_satisfied",
                "ok": True,
                "detail": "core complete",
            },
        ],
        "active_veto": False,
        "qualify_red": None,
        "exercise_red": None,
        "retained_asset_missing": False,
        "workflow_broken_at_tag": False,
    }


def _walk_request(
    *,
    trains: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    release_runs: list[dict[str, Any]] | None = None,
    release_pr: dict[str, Any] | None = "open",
    merged_head: str = SHA,
    tags: list[dict[str, Any]] | None = None,
    releases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    request = releasable_request()
    snapshot = request["snapshot"]
    snapshot["trains"] = {"status": "ready", "value": trains}
    snapshot["candidate"] = {"status": "ready", "value": candidate}
    snapshot["workflows"] = {
        "status": "ready",
        "value": {
            "release_yml": list(release_runs or []),
            "publish_yml": [],
        },
    }
    if release_pr == "open":
        pass
    elif release_pr == "merged":
        pr = dict(snapshot["release_pr"]["value"])
        pr["merged"] = True
        pr["merged_at"] = "2026-10-20T12:00:00Z"
        pr["head_sha"] = merged_head
        snapshot["release_pr"] = {"status": "ready", "value": pr}
    else:
        snapshot["release_pr"] = {"status": "ready", "value": release_pr}
    if tags is not None:
        snapshot["tags"] = {"status": "ready", "value": tags}
    if releases is not None:
        snapshot["releases"] = {"status": "ready", "value": releases}
    return request


def test_walk_drives_one_train_from_releasable_to_released() -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "release_steward_decide"):
        pytest.skip("installed sase_core_rs predates release_steward_decide")
    import _release_watch_decide as decide_tool

    tag_fact = {"name": TAG, "peeled_sha": SHA, "has_manifest": False}
    draft_release = {
        "tag": TAG,
        "draft": True,
        "name": f"Release {VERSION}",
        "assets": [],
        "url": f"https://github.com/sase-org/sase/releases/tag/{TAG}",
    }

    # Tick 1: an open releasable PR with merge authority on merges.
    result = decide_tool.decide(releasable_request())
    action = result["train_action"]
    assert action["disposition"] == "proposed"
    assert action["action"]["kind"] == "merge_release_pr"

    # Tick 2: the merged PR has no tag yet, so publish.yml mints one.
    request = _walk_request(trains=[], candidate=None, release_pr="merged")
    result = decide_tool.decide(request)
    action = result["train_action"]
    assert action["disposition"] == "proposed"
    assert action["action"]["kind"] == "dispatch_publish_metadata"

    # Tick 3: the fresh tag with its draft dispatches one initial release.
    trains, candidate = _fresh_context()
    assert candidate is None
    request = _walk_request(
        trains=trains,
        candidate=candidate,
        release_pr="merged",
        tags=[tag_fact],
        releases=[draft_release],
    )
    result = decide_tool.decide(request)
    action = result["train_action"]
    assert action["disposition"] == "proposed"
    assert action["action"]["kind"] == "dispatch_release"
    assert action["action"]["mode"] == "release"
    assert action["action"]["generation"] == 0

    # Tick 4: the identical facts plus the in-flight run take no action.
    request = _walk_request(
        trains=trains,
        candidate=candidate,
        release_runs=[_release_run(status="in_progress", conclusion=None)],
        release_pr="merged",
        tags=[tag_fact],
        releases=[draft_release],
    )
    result = decide_tool.decide(request)
    assert result["train_action"]["disposition"] != "proposed"

    # Tick 5: the sealed publishable generation with no PyPI files resumes.
    manifest = _sealed_manifest()
    sealed, sealed_candidate = _sealed_context(
        manifest,
        pypi_files=[],
        release_runs=[_sealed_release_run()],
    )
    assert len(sealed) == 1
    assert sealed[0]["generation"] == 1
    assert sealed[0]["manifest_mismatch"] is False
    assert sealed_candidate is not None
    assert sealed_candidate["candidate_id"] == sealed[0]["candidate_id"]
    publishable = _publishable_eval(sealed[0]["candidate_id"], sealed[0]["generation"])
    sealed_tag = {"name": TAG, "peeled_sha": SEALED_SHA, "has_manifest": True}
    sealed_release = {
        "tag": TAG,
        "draft": True,
        "name": f"Release {VERSION}",
        "assets": [
            {"name": "candidate-manifest.json", "kind": "manifest", "generation": 0}
        ],
        "url": f"https://github.com/sase-org/sase/releases/tag/{TAG}",
    }
    request = _walk_request(
        trains=sealed,
        candidate=publishable,
        release_runs=[_sealed_release_run()],
        release_pr="merged",
        merged_head=SEALED_SHA,
        tags=[sealed_tag],
        releases=[sealed_release],
    )
    result = decide_tool.decide(request)
    action = result["train_action"]
    assert action["disposition"] == "proposed"
    assert action["action"]["kind"] == "dispatch_release"
    assert action["action"]["mode"] == "resume"
    assert action["action"]["generation"] == 1

    # Tick 6: a repeated tick over the unchanged resumed facts takes none.
    in_flight = _sealed_release_run()
    in_flight["status"] = "in_progress"
    in_flight["conclusion"] = None
    request = _walk_request(
        trains=sealed,
        candidate=publishable,
        release_runs=[in_flight],
        release_pr="merged",
        merged_head=SEALED_SHA,
        tags=[sealed_tag],
        releases=[sealed_release],
    )
    result = decide_tool.decide(request)
    assert result["train_action"]["disposition"] != "proposed"

    # Tick 7: publication and confirmation release the version.
    confirmed, confirmed_candidate = _sealed_context(
        manifest,
        draft=False,
        release_runs=[_sealed_release_run()],
        confirmation=True,
    )
    assert confirmed[0]["confirmed"] is True
    assert confirmed[0]["confirmation_complete"] is True
    undrafted = dict(sealed_release, draft=False)
    request = _walk_request(
        trains=confirmed,
        candidate=confirmed_candidate,
        release_runs=[_sealed_release_run()],
        release_pr=None,
        tags=[sealed_tag],
        releases=[undrafted],
    )
    result = decide_tool.decide(request)
    assert result["primary"]["kind"] == "released"
    assert result.get("train_action") is None
    assert result["process_exit"] == 0
