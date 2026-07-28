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


def test_sidecar_record_round_trips_and_routes_kind_roots(
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
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
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

    assert not written.has_split_beads
    assert written.sidecar_for_kind("beads") is None
    assert read_sdd_store_record(primary) == written
    store = resolve_sdd_store(workspace, 2)
    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    assert store.is_sidecar_storage
    assert store.sdd_dir == plans
    assert store.repo_root == plans
    assert resolve_sdd_dir(workspace, 2) == plans
    assert resolve_sdd_kind_dir(workspace, 2, "plans") == plans
    assert resolve_sdd_kind_dir(workspace, 2, "beads") == plans / "beads"
    assert resolve_sdd_kind_dir(workspace, 2, "research") == research
    assert store.repo_root_for_kind("plans") == plans
    assert store.repo_root_for_kind("beads") == plans
    assert store.repo_root_for_kind("research") == research
    assert store.beads_remote_url is None


def test_schema_three_sidecar_record_round_trips_and_routes_beads(
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
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "git@github.com:owner/repo--plans.git",
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": "git@github.com:owner/repo--research.git",
                },
                "beads": {
                    "repo": "owner/repo--beads",
                    "remote_url": "git@github.com:owner/repo--beads.git",
                },
            },
        },
    )

    assert written.has_split_beads
    assert written.sidecar_for_kind("beads") == written.beads
    assert read_sdd_store_record(primary) == written
    assert (
        json.loads((primary / ".sase" / "sdd-store.json").read_text(encoding="utf-8"))[
            "schema_version"
        ]
        == 3
    )

    store = resolve_sdd_store(workspace, 2)
    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    beads = workspace / "sase" / "repos" / "beads"
    assert store.kind_root("plans") == plans
    assert store.kind_root("research") == research
    assert store.kind_root("beads") == beads
    assert store.repo_root_for_kind("plans") == plans
    assert store.repo_root_for_kind("research") == research
    assert store.repo_root_for_kind("beads") == beads
    assert written.beads is not None
    assert store.beads_remote_url == written.beads.remote_url


def test_schema_two_record_rejects_beads_sidecar(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="beads sidecars require schema_version >= 3"):
        write_sdd_store_record(
            tmp_path,
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "sidecars": {
                    "plans": {
                        "repo": "owner/repo--plans",
                        "remote_url": "plans-remote",
                    },
                    "research": {
                        "repo": "owner/repo--research",
                        "remote_url": "research-remote",
                    },
                    "beads": {
                        "repo": "owner/repo--beads",
                        "remote_url": "beads-remote",
                    },
                },
            },
        )


def test_loading_schema_two_record_rejects_beads_sidecar(tmp_path: Path) -> None:
    record_path = tmp_path / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "sidecars": {
                    "plans": {
                        "repo": "owner/repo--plans",
                        "remote_url": "plans-remote",
                    },
                    "research": {
                        "repo": "owner/repo--research",
                        "remote_url": "research-remote",
                    },
                    "beads": {
                        "repo": "owner/repo--beads",
                        "remote_url": "beads-remote",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SddMaterializationError, match="refusing to touch it"):
        read_sdd_store_record(tmp_path)


def test_writing_unsplit_record_keeps_schema_version_two(tmp_path: Path) -> None:
    written = write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "plans-remote",
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": "research-remote",
                },
            },
        },
    )

    persisted = json.loads(
        (tmp_path / ".sase" / "sdd-store.json").read_text(encoding="utf-8")
    )
    assert written.schema_version == 2
    assert read_sdd_store_record(tmp_path) == written
    assert persisted["schema_version"] == 2
    assert set(persisted["sidecars"]) == {"plans", "research"}


@pytest.mark.parametrize(
    ("storage", "sdd_suffix"),
    [
        (SDD_STORAGE_IN_TREE, "sdd"),
        (SDD_STORAGE_LOCAL, ".sase/sdd"),
        (SDD_STORAGE_SEPARATE_REPO, ".sase/sdd"),
    ],
)
def test_repo_root_for_kind_in_non_sidecar_layouts(
    tmp_path: Path,
    provider_patch,
    storage: str,
    sdd_suffix: str,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    detected_vcs = {
        SDD_STORAGE_IN_TREE: "bare_git",
        SDD_STORAGE_LOCAL: None,
        SDD_STORAGE_SEPARATE_REPO: "github",
    }[storage]
    provider_patch(detected_vcs)

    store = resolve_sdd_store(workspace, 2)
    expected_root = (
        workspace / sdd_suffix if storage != SDD_STORAGE_LOCAL else primary / sdd_suffix
    )
    assert store.storage == storage
    assert store.repo_root_for_kind("plans") == expected_root
    assert store.repo_root_for_kind("research") == expected_root
    assert store.repo_root_for_kind("beads") == expected_root


def test_legacy_github_https_sidecars_resolve_to_ssh_without_rewriting_record(
    tmp_path: Path,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    raw = {
        "schema_version": 2,
        "storage": "sidecar_repos",
        "provider": "github",
        "host": "github.com",
        "sidecars": {
            "plans": {
                "repo": "owner/repo--plans",
                "remote_url": "https://github.com/owner/repo--plans.git",
            },
            "research": {
                "repo": "owner/repo--research",
                "remote_url": "https://github.com/owner/repo--research.git",
            },
        },
    }
    record_path.write_text(json.dumps(raw), encoding="utf-8")
    provider_patch(None)

    record = read_sdd_store_record(primary)
    store = resolve_sdd_store(workspace, 2)

    assert record is not None and record.plans is not None
    assert record.research is not None
    assert record.plans.remote_url == "git@github.com:owner/repo--plans.git"
    assert record.research.remote_url == "git@github.com:owner/repo--research.git"
    assert store.remote_url == record.plans.remote_url
    assert store.research_remote_url == record.research.remote_url
    assert json.loads(record_path.read_text(encoding="utf-8")) == raw


def test_legacy_github_enterprise_https_sidecars_use_configured_ssh_port(
    tmp_path: Path,
) -> None:
    record = write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "host": "github.enterprise.test:2222",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": (
                        "https://github.enterprise.test/acme/widget--plans.git"
                    ),
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": (
                        "ssh://git@github.enterprise.test:2222/"
                        "acme/widget--research.git"
                    ),
                },
            },
        },
    )

    assert record.plans is not None and record.research is not None
    assert record.plans.remote_url == (
        "ssh://git@github.enterprise.test:2222/acme/widget--plans.git"
    )
    assert record.research.remote_url == (
        "ssh://git@github.enterprise.test:2222/acme/widget--research.git"
    )


def test_unresolved_http_sidecar_metadata_fails_resolution(tmp_path: Path) -> None:
    record_path = tmp_path / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "provider": "custom",
                "host": "git.example.test",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": (
                            "https://git.example.test/acme/widget--plans.git"
                        ),
                    },
                    "research": {
                        "repo": "acme/widget--research",
                        "remote_url": "git@git.example.test:acme/widget--research.git",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        SddMaterializationError,
        match=r"Invalid plans SDD sidecar metadata.*Git was not invoked",
    ):
        read_sdd_store_record(tmp_path)


def test_legacy_split_record_normalizes_and_rewrites_canonical_spellings(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    legacy_storage = "com" + "panion_repos"
    legacy_sidecars_key = "com" + "panions"
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "storage": legacy_storage,
                legacy_sidecars_key: {
                    "plans": {
                        "repo": "owner/repo--plans",
                        "remote_url": "plans-remote",
                    },
                    "research": {
                        "repo": "owner/repo--research",
                        "remote_url": "research-remote",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    record = read_sdd_store_record(primary)

    assert record is not None
    assert record.storage == "sidecar_repos"
    write_sdd_store_record(primary, record)
    rewritten = json.loads(record_path.read_text(encoding="utf-8"))
    assert rewritten["storage"] == "sidecar_repos"
    assert "sidecars" in rewritten
    assert legacy_sidecars_key not in rewritten


def test_sidecar_record_requires_both_kind_mappings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="plans and research"):
        write_sdd_store_record(
            tmp_path,
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "sidecars": {
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


def test_resolution_rejects_foreign_record_without_local_fallback(
    tmp_path: Path,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "storage": "sidecar_repos",
                "discovery": "found",
            }
        ),
        encoding="utf-8",
    )
    provider_patch("bare_git")

    with pytest.raises(SddMaterializationError, match="refusing to touch it"):
        resolve_sdd_store(workspace, 2)

    assert record_path.exists()


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
    sidecar = tmp_path / "sidecar.git"
    store = primary / ".sase" / "sdd"
    init_bare_repo(sidecar)
    clone(sidecar, store)
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "owner/repo--sdd",
            "remote_url": str(sidecar),
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
            "remote_url": str(tmp_path / "sidecar.git"),
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
