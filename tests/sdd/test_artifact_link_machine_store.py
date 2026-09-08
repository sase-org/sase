"""Tests for the machine-context artifact-link store resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd.artifact_link_store import resolve_machine_artifact_link_store
from sase.sdd.store import write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def _sidecar_repos_primary(
    tmp_path: Path,
    *,
    roles: dict[str, Path],
) -> Path:
    """Write a materialized sidecar-repos record for *roles* -> remote path."""

    primary = tmp_path / "primary"
    primary.mkdir(exist_ok=True)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                role: {
                    "repo": f"acme/widget--{role}",
                    "remote_url": str(remote),
                }
                for role, remote in roles.items()
            },
        },
    )
    return primary


def _seeded_remote(tmp_path: Path, name: str, *, content: str = "v1\n") -> Path:
    remote = tmp_path / f"{name}.git"
    seed = tmp_path / f"{name}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text(content, encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    return remote


class TestHiddenStorePathMapping:
    def test_document_roles_resolve_to_hidden_clones(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        plans_remote = _seeded_remote(tmp_path, "plans")
        research_remote = _seeded_remote(tmp_path, "research")
        primary = _sidecar_repos_primary(
            tmp_path, roles={"plans": plans_remote, "research": research_remote}
        )

        store = resolve_machine_artifact_link_store("acme_widget", primary)

        assert store.sidecar_roots["plan"] == Path(
            hidden_sidecar_clone_dir("acme_widget", "plans")
        )
        assert store.sidecar_roots["research"] == Path(
            hidden_sidecar_clone_dir("acme_widget", "research")
        )
        assert store.sidecar_roots["plan"] != primary / "sase" / "repos" / "plans"

    def test_beads_and_agents_stay_at_existing_read_context_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        monkeypatch.setattr(
            "sase.bead.project_name.infer_project_name_from_cwd",
            lambda *_a, **_kw: "acme_widget",
        )
        plans_remote = _seeded_remote(tmp_path, "plans")
        agents_remote = _seeded_remote(tmp_path, "agents")
        beads_remote = _seeded_remote(tmp_path, "beads")
        primary = tmp_path / "primary"
        primary.mkdir()
        write_sdd_store_record(
            primary,
            {
                "schema_version": 3,
                "storage": "sidecar_repos",
                "provider": "github",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": str(plans_remote),
                    },
                    "agents": {
                        "repo": "acme/widget--agents",
                        "remote_url": str(agents_remote),
                    },
                    "beads": {
                        "repo": "acme/widget--beads",
                        "remote_url": str(beads_remote),
                    },
                },
            },
        )
        # Beads is only ever read context for the machine store, so it is
        # never materialized by resolve_machine_artifact_link_store itself;
        # a real project would already have it cloned here beforehand.
        clone(beads_remote, primary / "sase" / "repos" / "beads")

        store = resolve_machine_artifact_link_store("acme_widget", primary)

        # agents was already hidden before this phase and stays that way. It
        # is not a document role, so it never appears in sidecar_roots (that
        # mapping is artifact-link document kinds only) -- check the
        # underlying resolved SddStore instead.
        assert store.sdd_store is not None
        assert store.sdd_store.sidecar_dirs["agents"] == Path(
            hidden_sidecar_clone_dir("acme_widget", "agents")
        )
        # beads is left at its existing (primary-anchored) read-context root.
        assert store.beads_dir == primary / "sase" / "repos" / "beads"


class TestMaterializationAndIntegration:
    def test_missing_hidden_clone_is_materialized_from_the_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        plans_remote = _seeded_remote(tmp_path, "plans")
        primary = _sidecar_repos_primary(tmp_path, roles={"plans": plans_remote})

        resolve_machine_artifact_link_store("acme_widget", primary)

        hidden_plans = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        assert (hidden_plans / "README.md").is_file()
        assert (hidden_plans / ".git").is_dir()

    def test_existing_hidden_clone_integrates_fresh_remote_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        plans_remote = _seeded_remote(tmp_path, "plans")
        primary = _sidecar_repos_primary(tmp_path, roles={"plans": plans_remote})

        resolve_machine_artifact_link_store("acme_widget", primary)
        hidden_plans = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        assert (hidden_plans / "README.md").read_text(encoding="utf-8") == "v1\n"

        seed = tmp_path / "plans-seed"
        (seed / "README.md").write_text("v2\n", encoding="utf-8")
        commit_all(seed, "v2")
        git(["push"], seed)

        resolve_machine_artifact_link_store("acme_widget", primary)

        assert (hidden_plans / "README.md").read_text(encoding="utf-8") == "v2\n"

    def test_primary_clone_is_used_only_as_a_git_object_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        plans_remote = _seeded_remote(tmp_path, "plans")
        primary = _sidecar_repos_primary(tmp_path, roles={"plans": plans_remote})
        primary_plans = primary / "sase" / "repos" / "plans"
        clone(plans_remote, primary_plans)

        calls: list[dict[str, object]] = []
        import sase.sdd._store_link as store_link_mod

        original = store_link_mod.ensure_sidecar_sdd_clone

        def _spy(clone_dir: Path, remote_url: str, **kwargs: Any) -> None:
            calls.append({"clone_dir": clone_dir, "remote_url": remote_url, **kwargs})
            original(clone_dir, remote_url, **kwargs)

        monkeypatch.setattr(store_link_mod, "ensure_sidecar_sdd_clone", _spy)

        resolve_machine_artifact_link_store("acme_widget", primary)

        assert len(calls) == 1
        assert calls[0]["reference_repo"] == primary_plans
        assert calls[0]["fresh"] is True
        assert calls[0]["strict"] is True

    def test_no_reference_repo_when_primary_clone_is_not_materialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        plans_remote = _seeded_remote(tmp_path, "plans")
        primary = _sidecar_repos_primary(tmp_path, roles={"plans": plans_remote})
        # No clone materialized at primary / sase/repos/plans.

        calls: list[dict[str, object]] = []
        import sase.sdd._store_link as store_link_mod

        original = store_link_mod.ensure_sidecar_sdd_clone

        def _spy(clone_dir: Path, remote_url: str, **kwargs: Any) -> None:
            calls.append({"clone_dir": clone_dir, "remote_url": remote_url, **kwargs})
            original(clone_dir, remote_url, **kwargs)

        monkeypatch.setattr(store_link_mod, "ensure_sidecar_sdd_clone", _spy)

        resolve_machine_artifact_link_store("acme_widget", primary)

        assert calls[0]["reference_repo"] is None


class TestNonSplitStorageFallsBackUnchanged:
    def test_in_tree_storage_is_returned_as_is(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "bare_git")
        monkeypatch.setattr(
            "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
            lambda vcs_name: {"bare_git": "in_tree"}.get(vcs_name),
        )
        primary = tmp_path / "primary"
        primary.mkdir()

        store = resolve_machine_artifact_link_store("acme_widget", primary)

        assert store.sdd_store is not None
        assert not store.sdd_store.is_sidecar_storage
        assert store.sdd_store.sdd_dir == primary / "sdd"
