from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sdd.store import (
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    materialized_sdd_clone,
    read_sdd_store_record,
    resolve_sdd_dir,
    resolve_sdd_kind_dir,
    resolve_sdd_store,
    write_sdd_store_record,
)
from tests.sdd_store._helpers import clone, init_bare_repo


@pytest.mark.parametrize(
    ("detected_vcs", "expected_storage"),
    [
        ("github", SDD_STORAGE_SEPARATE_REPO),
        ("bare_git", SDD_STORAGE_IN_TREE),
        ("unclaimed", SDD_STORAGE_LOCAL),
        (None, SDD_STORAGE_LOCAL),
    ],
)
def test_provider_policy_owns_storage_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
    detected_vcs: str | None,
    expected_storage: str,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch(detected_vcs)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"storage": "local", "version_controlled": True}},
    )

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == expected_storage
    expected = {
        SDD_STORAGE_IN_TREE: workspace / "sdd",
        SDD_STORAGE_LOCAL: primary / ".sase" / "sdd",
        SDD_STORAGE_SEPARATE_REPO: workspace / ".sase" / "sdd",
    }[expected_storage]
    assert store.sdd_dir == expected
    assert resolve_sdd_dir(workspace, 2) == expected


def test_positive_record_precedes_provider_policy(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch("bare_git")
    written = write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/repo--sdd",
            "remote_url": "git@github.com:owner/repo--sdd.git",
            "discovery": "found",
        },
    )

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.provider == "github"
    assert store.remote_url == written.remote_url


def test_companion_record_round_trips_and_routes_kind_roots(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    provider_patch("bare_git")

    written = write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "companion_repos",
            "provider": "github",
            "companions": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "git@github.com:owner/repo--plans.git",
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": "git@github.com:owner/repo--research.git",
                },
            },
        },
    )

    assert read_sdd_store_record(primary) == written
    store = resolve_sdd_store(workspace, 2)
    plans = workspace / "sase" / "repos" / "repo--plans"
    research = workspace / "sase" / "repos" / "repo--research"
    assert store.is_companion_storage
    assert store.sdd_dir == plans
    assert store.repo_root == plans
    assert resolve_sdd_dir(workspace, 2) == plans
    assert resolve_sdd_kind_dir(workspace, 2, "plans") == plans
    assert resolve_sdd_kind_dir(workspace, 2, "beads") == plans / "beads"
    assert resolve_sdd_kind_dir(workspace, 2, "research") == research


def test_companion_record_requires_both_kind_mappings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="plans and research"):
        write_sdd_store_record(
            tmp_path,
            {
                "schema_version": 2,
                "storage": "companion_repos",
                "companions": {
                    "plans": {
                        "repo": "owner/repo--plans",
                        "remote_url": "plans-remote",
                    }
                },
            },
        )


def test_old_negative_record_is_ignored_but_github_policy_stays_separate(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            {
                "storage": "separate_repo",
                "provider": "github",
                "discovery": "not_found",
            }
        ),
        encoding="utf-8",
    )
    provider_patch("github")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.provider is None
    assert store.sdd_dir == workspace / ".sase" / "sdd"


def test_positive_record_round_trips_atomically(tmp_path: Path) -> None:
    primary = tmp_path / "repo"
    written = write_sdd_store_record(
        primary,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "fake",
            "host": "example.com",
            "repo": "owner/repo--sdd",
            "remote_url": "git@example.com:owner/repo--sdd.git",
            "discovery": "found",
        },
    )

    assert written.probed_at is not None
    assert read_sdd_store_record(primary) == written


def test_materialized_sdd_clone_skips_stale_clone_without_record(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"
    stale = primary / ".sase" / "sdd"
    stale.mkdir(parents=True)

    assert materialized_sdd_clone(primary) is None


def test_materialized_sdd_clone_returns_matching_primary_clone(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"
    companion = tmp_path / "companion.git"
    store = primary / ".sase" / "sdd"
    init_bare_repo(companion)
    clone(companion, store)
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/repo--sdd",
            "remote_url": str(companion),
            "discovery": "found",
        },
    )

    assert materialized_sdd_clone(primary) == store


def test_materialized_sdd_clone_skips_missing_clone_for_positive_record(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/repo--sdd",
            "remote_url": str(tmp_path / "companion.git"),
            "discovery": "found",
        },
    )

    assert materialized_sdd_clone(primary) is None


def test_materialized_sdd_clone_skips_clone_with_mismatched_remote(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"
    expected = tmp_path / "expected.git"
    other = tmp_path / "other.git"
    store = primary / ".sase" / "sdd"
    init_bare_repo(expected)
    init_bare_repo(other)
    clone(other, store)
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/repo--sdd",
            "remote_url": str(expected),
            "discovery": "found",
        },
    )

    assert materialized_sdd_clone(primary) is None


def test_negative_records_cannot_be_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive materialized"):
        write_sdd_store_record(
            tmp_path,
            {
                "storage": "separate_repo",
                "provider": "github",
                "discovery": "not_found",
            },
        )


def test_provider_policy_lookup_failure_does_not_fall_back_to_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: "github")

    def fail_policy_lookup(_vcs_name: str) -> str:
        raise RuntimeError("provider registry unavailable")

    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        fail_policy_lookup,
    )

    with pytest.raises(SddMaterializationError, match="provider registry unavailable"):
        resolve_sdd_store(tmp_path, 1)
