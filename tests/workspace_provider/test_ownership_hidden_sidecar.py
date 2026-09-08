"""Host-owned hidden sidecar clones are a confined machine-writable lane.

Covers the ``hidden-clone-machine-writes`` phase's ownership-contract
extension: a project's recorded document sidecar role resolves to a
machine-writable :class:`AccessKind.HOST_OWNED_SIDECAR` context when it lives
under the canonical ``~/.sase/projects/<project_key>/repos/<role>`` root, while
every other invariant this contract enforces (primary ``#0`` refusal, foreign
lookalikes, unconfigured roles) stays fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd.store import write_sdd_store_record
from sase.workspace_provider.ownership import (
    WorkspaceOwnershipError,
    authorize_store_mutation,
)


def _materialized_primary(
    tmp_path: Path,
    *,
    roles: tuple[str, ...] = ("plans", "research"),
) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                role: {
                    "repo": f"acme/widget--{role}",
                    "remote_url": f"git@github.com:acme/widget--{role}.git",
                }
                for role in roles
            },
        },
    )
    return primary


def _patch_primary_lookup(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, Path],
) -> None:
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda project_key: mapping.get(project_key),
    )


class TestHiddenSidecarIsMachineWritable:
    def test_configured_document_role_authorizes_machine_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path)
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        target = (
            Path(hidden_sidecar_clone_dir("acme_widget", "research"))
            / "links"
            / "202609"
            / "a.md.json"
        )
        target.parent.mkdir(parents=True)
        target.touch()

        authorize_store_mutation(target, mutation_origin="machine")  # no raise

    def test_plans_role_also_authorizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path)
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        root = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        root.mkdir(parents=True)

        authorize_store_mutation(root, mutation_origin="machine")  # no raise


class TestUnconfiguredOrForeignLookalikesAreRefused:
    def test_role_not_recorded_on_the_primary_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path, roles=("plans",))
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        # "research" is a plausible sibling role, but this project never
        # recorded it as a sidecar.
        root = Path(hidden_sidecar_clone_dir("acme_widget", "research"))
        root.mkdir(parents=True)

        with pytest.raises(WorkspaceOwnershipError):
            authorize_store_mutation(root, mutation_origin="machine")

    def test_unknown_project_key_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        _patch_primary_lookup(monkeypatch, {})
        root = Path(hidden_sidecar_clone_dir("no_such_project", "plans"))
        root.mkdir(parents=True)

        with pytest.raises(WorkspaceOwnershipError):
            authorize_store_mutation(root, mutation_origin="machine")

    def test_primary_with_no_materialized_record_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = tmp_path / "primary"
        primary.mkdir()
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        root = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        root.mkdir(parents=True)

        with pytest.raises(WorkspaceOwnershipError):
            authorize_store_mutation(root, mutation_origin="machine")

    def test_path_adjacent_to_but_outside_the_hidden_root_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A sibling directory next to a legitimate hidden clone role.

        Guards against a naive prefix check treating ``.../repos/plans-evil``
        as inside ``.../repos/plans``.
        """

        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path, roles=("plans",))
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        plans_root = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        lookalike = plans_root.parent / "plans-evil"
        lookalike.mkdir(parents=True)

        with pytest.raises(WorkspaceOwnershipError):
            authorize_store_mutation(lookalike, mutation_origin="machine")


class TestConfinementToTheSelectedRole:
    def test_mutation_is_confined_to_the_recorded_roles_own_clone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path, roles=("plans", "research"))
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        plans_root = Path(hidden_sidecar_clone_dir("acme_widget", "plans"))
        research_root = Path(hidden_sidecar_clone_dir("acme_widget", "research"))
        plans_root.mkdir(parents=True)
        research_root.mkdir(parents=True)

        # Both configured roles authorize independently...
        authorize_store_mutation(plans_root, mutation_origin="machine")
        authorize_store_mutation(research_root, mutation_origin="machine")

        # ...and a path that only resolves under a third, unrecorded role
        # sharing the same project directory is still refused, proving the
        # grant is scoped to one role's clone rather than the whole project.
        designs_root = Path(hidden_sidecar_clone_dir("acme_widget", "designs"))
        designs_root.mkdir(parents=True)
        with pytest.raises(WorkspaceOwnershipError):
            authorize_store_mutation(designs_root, mutation_origin="machine")


class TestPrimaryRefusalIsUnchanged:
    def test_primary_zero_nested_sidecar_clone_is_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path)
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})
        nested = primary / "sase" / "repos" / "research"
        nested.mkdir(parents=True)

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            authorize_store_mutation(nested, mutation_origin="machine")

    def test_primary_checkout_itself_is_still_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
        primary = _materialized_primary(tmp_path)
        _patch_primary_lookup(monkeypatch, {"acme_widget": primary})

        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            authorize_store_mutation(primary, mutation_origin="machine")
