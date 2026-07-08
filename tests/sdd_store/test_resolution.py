from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.sdd._paths import get_sdd_dir
from sase.sdd.store import (
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    _write_sdd_store_record,
    get_configured_sdd_storage,
    read_sdd_store_record,
    resolve_sdd_dir,
    resolve_sdd_store,
)


@pytest.mark.parametrize(
    ("sdd_config", "detected_vcs", "expected_storage"),
    [
        ({"storage": "in_tree", "version_controlled": False}, "github", "in_tree"),
        ({"storage": "local", "version_controlled": True}, "bare_git", "local"),
        (
            {"storage": "separate_repo", "version_controlled": False},
            None,
            "separate_repo",
        ),
        ({"storage": "auto", "version_controlled": True}, "github", "in_tree"),
        ({"storage": "auto", "version_controlled": False}, "bare_git", "in_tree"),
        ({"storage": "auto", "version_controlled": False}, "github", "local"),
        ({"storage": "auto", "version_controlled": False}, None, "local"),
    ],
)
def test_resolve_sdd_store_equivalence_matrix(
    tmp_path: Path,
    config_patch,
    provider_patch,
    sdd_config: dict[str, Any],
    detected_vcs: str | None,
    expected_storage: str,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    config_patch({"sdd": sdd_config})
    provider_patch(detected_vcs)

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == expected_storage
    expected_sdd_dir = {
        SDD_STORAGE_IN_TREE: workspace / "sdd",
        SDD_STORAGE_LOCAL: primary / ".sase" / "sdd",
        SDD_STORAGE_SEPARATE_REPO: workspace / ".sase" / "sdd",
    }[expected_storage]
    assert store.sdd_dir == expected_sdd_dir

    expected_beads_dir = {
        SDD_STORAGE_IN_TREE: workspace / BEADS_DIRNAME,
        SDD_STORAGE_LOCAL: primary / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC,
        SDD_STORAGE_SEPARATE_REPO: workspace / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC,
    }[expected_storage]
    assert store.sdd_dir / "beads" == expected_beads_dir


@pytest.mark.parametrize(
    ("sdd_config", "expected"),
    [
        ({"storage": "local", "version_controlled": True}, "local"),
        ({"storage": "in_tree", "version_controlled": False}, "in_tree"),
        ({"storage": "separate_repo", "version_controlled": True}, "separate_repo"),
        ({"storage": "auto", "version_controlled": True}, "in_tree"),
        ({"version_controlled": True}, "in_tree"),
        ({"version_controlled": False}, "auto"),
    ],
)
def test_configured_storage_alias_conflict_behavior(
    config_patch,
    sdd_config: dict[str, Any],
    expected: str,
) -> None:
    config_patch({"sdd": sdd_config})

    assert get_configured_sdd_storage() == expected


def test_record_precedence_under_auto(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "remote_url": "git@github.com:owner/repo-sdd.git",
                "discovery": "found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    provider_patch("bare_git")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.sdd_dir == workspace / ".sase" / "sdd"
    assert store.provider == "github"
    assert store.remote_url == "git@github.com:owner/repo-sdd.git"


def test_negative_record_does_not_activate_separate_repo(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "discovery": "not_found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    provider_patch("github")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_LOCAL
    assert store.provider is None
    assert store.remote_url is None


def test_explicit_storage_wins_over_record(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "remote_url": "git@github.com:owner/repo-sdd.git",
                "discovery": "found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "local", "version_controlled": True}})
    provider_patch("bare_git")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_LOCAL
    assert store.sdd_dir == primary / ".sase" / "sdd"
    assert store.provider is None
    assert store.remote_url is None


@pytest.mark.parametrize(
    ("sdd_config", "expected_storage"),
    [
        ({"storage": "in_tree", "version_controlled": False}, SDD_STORAGE_IN_TREE),
        ({"storage": "local", "version_controlled": True}, SDD_STORAGE_LOCAL),
        (
            {"storage": "separate_repo", "version_controlled": False},
            SDD_STORAGE_SEPARATE_REPO,
        ),
    ],
)
def test_resolve_sdd_dir_matches_storage_paths(
    tmp_path: Path,
    config_patch,
    provider_patch,
    sdd_config: dict[str, Any],
    expected_storage: str,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    primary.mkdir()
    workspace.mkdir()
    config_patch({"sdd": sdd_config})
    provider_patch(None)

    expected = {
        SDD_STORAGE_IN_TREE: get_sdd_dir(str(workspace), 2, version_controlled=True),
        SDD_STORAGE_LOCAL: get_sdd_dir(str(workspace), 2, version_controlled=False),
        SDD_STORAGE_SEPARATE_REPO: workspace / ".sase" / "sdd",
    }[expected_storage]
    assert resolve_sdd_dir(workspace, 2) == expected


def test_write_sdd_store_record_round_trips(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"

    written = _write_sdd_store_record(
        primary,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "fake",
            "host": "example.com",
            "repo": "owner/repo-sdd",
            "remote_url": "git@example.com:owner/repo-sdd.git",
            "discovery": "found",
        },
    )

    assert written.probed_at is not None
    reread = read_sdd_store_record(primary)
    assert reread == written
    raw = json.loads((primary / ".sase" / "sdd-store.json").read_text())
    assert raw["storage"] == "separate_repo"
    assert raw["repo"] == "owner/repo-sdd"
    assert raw["probed_at"]
