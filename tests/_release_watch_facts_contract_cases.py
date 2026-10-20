"""Tests for tools/_release_watch_facts.py and tools/_release_watch_transport.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._release_candidate_tool_helpers import load_tool, seal_kwargs


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_facts import (  # noqa: E402
    ReleaseFactsError,
    ReleaseFactsReader,
    _candidate_cli,
    parse_pypi_inventory,
)
from _release_watch_transport import (  # noqa: E402
    GithubTransport,
    ReleaseTransportError,
)

SHA = "4e5b7d2eb6c4a5b6c4a5b6c4a5b6c4a5b6c4a5b6"
VERSION = "0.18.0"
TAG = f"v{VERSION}"


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


def _manifest() -> dict[str, Any]:
    tool = load_tool()
    args = seal_kwargs()
    args.update({"tag": f"refs/tags/{TAG}", "sha": SHA})
    return tool.seal_manifest(**args)


def _asset_rows(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [{"id": 1, "name": "candidate-manifest.json"}]
    for index, dist in enumerate(manifest["dists"], 2):
        name = Path(dist["asset"].split("/", 1)[1]).name
        rows.append({"id": index, "name": name})
    wire = [
        {
            "id": asset["id"],
            "name": asset["name"],
            "kind": "manifest" if asset["id"] == 1 else "other",
            "generation": 0,
        }
        for asset in rows
    ]
    return rows, wire


def _pypi(manifest: dict[str, Any], *, conflict: bool = False) -> dict[str, Any]:
    files = []
    for index, dist in enumerate(manifest["dists"]):
        files.append(
            {
                "filename": dist["filename"],
                "version": VERSION,
                "sha256": ("f" * 64 if conflict and index == 0 else dist["sha256"]),
                "yanked": False,
            }
        )
    return {
        "sase": {"package": "sase", "files": files},
        "core": {"package": "sase-core-rs", "files": []},
    }


def _train_context(
    manifest: dict[str, Any],
    *,
    conflict: bool = False,
    extra_assets: list[dict[str, Any]] | None = None,
    wrong_head: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    asset_rows, asset_wires = _asset_rows(manifest)
    asset_payloads = {1: manifest}
    if extra_assets:
        asset_rows.extend(extra_assets)
        asset_wires.extend(
            {
                "id": row["id"],
                "name": row["name"],
                "kind": "exercise",
                "generation": 2,
            }
            for row in extra_assets
        )
        asset_payloads.update({row["id"]: row["payload"] for row in extra_assets})
    for row in asset_rows[1:]:
        asset_payloads.setdefault(row["id"], {})
    github = FakeGithub(asset_payloads)
    reader = ReleaseFactsReader(github=github)
    release_wire = {
        "tag": TAG,
        "draft": True,
        "name": TAG,
        "url": f"https://github.com/sase-org/sase/releases/tag/{TAG}",
        "assets": asset_wires,
    }
    release_raw = {"assets": asset_rows}
    workflows = {
        "release_yml": [
            {
                "ref_name": TAG,
                "sha": "c" * 40 if wrong_head else SHA,
                "run_id": "17",
                "attempt": 1,
                "status": "completed",
                "jobs": [],
            }
        ],
        "publish_yml": [],
    }
    return reader._train_context(
        [{"name": TAG, "peeled_sha": SHA, "has_manifest": True}],
        [(release_wire, release_raw)],
        _pypi(manifest, conflict=conflict),
        workflows,
    )


def test_github_transport_uses_pagination_timeout_and_plain_environment() -> None:
    seen: list[tuple[list[str], float, dict[str, str]]] = []

    def runner(
        argv: list[str], *, timeout: float, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        seen.append((argv, timeout, env))
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([[{"id": 1}], [{"id": 2}]]), ""
        )

    transport = GithubTransport("sase-org/sase", runner=runner)
    assert transport.pages("repos/sase-org/sase/releases") == [{"id": 1}, {"id": 2}]
    argv, timeout, env = seen[0]
    assert argv[:4] == ["gh", "api", "--paginate", "--slurp"]
    assert "page=1" in argv[-1] and "per_page=100" in argv[-1]
    assert timeout > 0
    assert env["GH_REPO"] == "sase-org/sase"
    assert env["GH_PROMPT_DISABLED"] == "1"
    assert env["GH_FORCE_TTY"] == "0"


def test_empty_paginated_read_is_distinct_from_failed_read() -> None:
    def empty_runner(
        argv: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "[[]]", "")

    def failed_runner(
        argv: list[str], **_kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "HTTP 403")

    assert GithubTransport("sase-org/sase", runner=empty_runner).pages("releases") == []
    with pytest.raises(ReleaseTransportError, match="403"):
        GithubTransport("sase-org/sase", runner=failed_runner).pages("releases")


def test_pypi_inventory_keeps_yanks_and_digest_identity() -> None:
    payload = {
        "releases": {
            "1.0.0": [
                {
                    "filename": "pkg-1.0.0.whl",
                    "digests": {"sha256": "a" * 64},
                    "yanked": True,
                }
            ]
        }
    }
    assert parse_pypi_inventory("pkg", payload) == {
        "package": "pkg",
        "files": [
            {
                "filename": "pkg-1.0.0.whl",
                "version": "1.0.0",
                "sha256": "a" * 64,
                "yanked": True,
            }
        ],
    }
    payload["releases"]["1.0.0"][0]["digests"]["sha256"] = "bad"
    with pytest.raises(ReleaseFactsError, match="SHA-256"):
        parse_pypi_inventory("pkg", payload)


def test_candidate_cli_preserves_identity_clauses_and_missing_evidence_refusal() -> (
    None
):
    manifest = _manifest()
    report = _candidate_cli(manifest, [])
    assert report["candidate_id"] == manifest["candidate_id"]
    assert report["generation"] == manifest["generation"]
    assert report["version"] == VERSION
    assert report["publishable"] is False
    assert report["rerun_eligible"] is False
    assert {clause["name"] for clause in report["clauses"]} >= {
        "qualification",
        "exercise",
        "public_dependency_contract_satisfied",
    }
    assert report["evidence_mismatch"] is False


def test_candidate_evaluator_malformed_output_is_an_error() -> None:
    manifest = _manifest()

    def malformed_runner(
        argv: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if "verify" in argv:
            return subprocess.CompletedProcess(
                argv, 0, f"OK {manifest['candidate_id']}\n", ""
            )
        return subprocess.CompletedProcess(argv, 2, "not json", "")

    with pytest.raises(ReleaseFactsError, match="malformed JSON"):
        _candidate_cli(manifest, [], runner=malformed_runner)


def test_train_reader_matches_and_rejects_conflicting_pypi_digests() -> None:
    manifest = _manifest()
    matching, matching_candidate = _train_context(manifest)
    assert matching_candidate is not None
    assert matching[0]["py_files_present"] == 2
    assert matching[0]["py_digest_conflict"] is False
    assert matching[0]["manifest_mismatch"] is False

    conflicting, _candidate = _train_context(manifest, conflict=True)
    assert conflicting[0]["py_digest_conflict"] is True


def test_tag_sha_and_observation_generation_mismatches_fail_closed() -> None:
    manifest = _manifest()
    manifest["sha"] = "c" * 40
    trains, _candidate = _train_context(manifest)
    assert trains[0]["manifest_mismatch"] is True

    manifest = _manifest()
    wrong_observation = {
        "id": 9,
        "name": "candidate-gen2-exercise-run7-attempt1.json",
        "payload": {
            "asset": "candidate-gen2-exercise-run7-attempt1.json",
            "kind": "exercise",
            "generation": 2,
            "run_id": 7,
            "attempt": 1,
            "candidate_id": manifest["candidate_id"],
            "verdict": "pass",
        },
    }
    trains, _candidate = _train_context(manifest, extra_assets=[wrong_observation])
    assert trains[0]["evidence_mismatch"] is True

    manifest = _manifest()
    trains, _candidate = _train_context(manifest, wrong_head=True)
    assert trains[0]["evidence_mismatch"] is True


def test_candidate_attempt_gap_is_not_promoted_from_stale_evidence() -> None:
    tool = load_tool()
    manifest = _manifest()
    stale = tool.append_observation(
        manifest,
        kind="exercise",
        run_id=17,
        attempt=2,
        verdict="pass",
    )
    report = _candidate_cli(manifest, [stale])
    assert report["publishable"] is False
    assert report["evidence_mismatch"] is True
    exercise = next(
        clause for clause in report["clauses"] if clause["name"] == "exercise"
    )
    assert "omits one or more earlier attempts" in exercise["detail"]
