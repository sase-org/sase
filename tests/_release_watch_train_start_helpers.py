"""Shared facts for release-watch train-start splits."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

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


def fresh_context(
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
