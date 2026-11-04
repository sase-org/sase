"""Releasable-to-released walk for train start."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from tests._release_candidate_tool_helpers import dists, load_tool, seal_kwargs
from tests._release_steward_fixtures import releasable_request
from tests._release_watch_train_start_helpers import (
    SHA,
    TAG,
    VERSION,
    FakeGithub,
    fresh_context,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_facts import ReleaseFactsReader  # noqa: E402


SEALED_SHA = "c" * 40


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
        payloads.setdefault(row["id"], {})  # type: ignore[call-overload]
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
    release_pr: str | dict[str, Any] | None = "open",
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
    import _release_watch_decide as decide_tool  # noqa: E402

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
    trains, candidate = fresh_context()
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
