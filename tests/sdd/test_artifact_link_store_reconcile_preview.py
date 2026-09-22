"""Reconciliation store iteration and aggregate preview for the link store."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoCloneRecord, RepoInventory, RepoRecord
from sase.sdd._artifact_link_cutover_state import _ArtifactLinkCutoverInspection
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row


def _primary_inventory(
    *,
    project_key: str,
    primary_path: Path,
    ephemeral_paths: tuple[Path, ...],
    primary_workspace_num: int = 0,
) -> RepoInventory:
    clones = (
        RepoCloneRecord(primary_workspace_num, str(primary_path), True),
        *(
            RepoCloneRecord(index, str(path), True)
            for index, path in enumerate(ephemeral_paths, start=2)
        ),
    )
    return RepoInventory(
        records=(
            RepoRecord(
                name="sase",
                kind="primary",
                project="sase",
                project_key=project_key,
                path=str(primary_path),
                exists=True,
                auto_clone=False,
                description=None,
                source="test",
                env_name=None,
                clones=clones,
            ),
        )
    )


def _stub_reconciliation_inventory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_key: str,
    primary_path: Path,
    primary_store: ArtifactLinkStore,
    ephemeral_paths: tuple[Path, ...],
    ephemeral_stores: tuple[ArtifactLinkStore, ...],
    primary_workspace_num: int = 0,
) -> list[str]:
    constructed: list[str] = []
    stores_by_path = {
        str(primary_path): primary_store,
        **{
            str(path): store
            for path, store in zip(ephemeral_paths, ephemeral_stores, strict=True)
        },
    }
    monkeypatch.setattr(
        "sase.repo_inventory.collect_repo_inventory",
        lambda **_kwargs: _primary_inventory(
            project_key=project_key,
            primary_path=primary_path,
            ephemeral_paths=ephemeral_paths,
            primary_workspace_num=primary_workspace_num,
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda path, _workspace_num: SimpleNamespace(path=str(path)),
    )

    def fake_from_sdd_store(
        sdd_store: SimpleNamespace, _project_key: str
    ) -> ArtifactLinkStore:
        constructed.append(str(sdd_store.path))
        return stores_by_path[str(sdd_store.path)]

    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_impl.ArtifactLinkStore.from_sdd_store",
        fake_from_sdd_store,
    )
    return constructed


def test_iter_reconciliation_stores_keeps_self_and_primary_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    machine = tmp_path / "machine" / "plans"
    primary = tmp_path / "primary"
    ephemeral_a = tmp_path / "sase_12"
    ephemeral_b = tmp_path / "sase_30"
    machine.mkdir(parents=True)
    (primary / "plans").mkdir(parents=True)
    (ephemeral_a / "plans").mkdir(parents=True)
    (ephemeral_b / "plans").mkdir(parents=True)
    self_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": machine},
    )
    primary_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": primary / "plans"},
    )
    ephemeral_stores = (
        ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": ephemeral_a / "plans"},
        ),
        ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": ephemeral_b / "plans"},
        ),
    )
    constructed = _stub_reconciliation_inventory(
        monkeypatch,
        project_key="gh_sase-org__sase",
        primary_path=primary,
        primary_store=primary_store,
        ephemeral_paths=(ephemeral_a, ephemeral_b),
        ephemeral_stores=ephemeral_stores,
    )

    yielded = tuple(self_store._iter_reconciliation_stores())

    assert yielded == (self_store, primary_store)
    assert constructed == [str(primary)]


def test_preview_does_not_multiply_compatibility_rows_by_ephemeral_clones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    machine = tmp_path / "machine" / "plans"
    primary = tmp_path / "primary"
    ephemeral = tmp_path / "sase_12"
    machine.mkdir(parents=True)
    (primary / "plans").mkdir(parents=True)
    (ephemeral / "plans").mkdir(parents=True)
    self_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": machine},
    )
    primary_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": primary / "plans"},
    )
    ephemeral_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": ephemeral / "plans"},
    )
    constructed = _stub_reconciliation_inventory(
        monkeypatch,
        project_key="gh_sase-org__sase",
        primary_path=primary,
        primary_store=primary_store,
        ephemeral_paths=(ephemeral,),
        ephemeral_stores=(ephemeral_store,),
    )
    bead_identities: list[object] = []

    def fake_bead_rows(self: ArtifactLinkStore) -> tuple[dict[str, object], ...]:
        bead_identities.append(self._store_identity())
        return ()

    monkeypatch.setattr(ArtifactLinkStore, "_iter_bead_rows", fake_bead_rows)

    self_store.preview_reconciled_aggregate()

    assert constructed == [str(primary)]
    assert bead_identities == [
        self_store._store_identity(),
        primary_store._store_identity(),
    ]
    assert ephemeral_store._store_identity() not in bead_identities


def test_preview_deadline_skips_remaining_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans_a = tmp_path / "clone-a" / "plans"
    plans_b = tmp_path / "clone-b" / "plans"
    plans_a.mkdir(parents=True)
    plans_b.mkdir(parents=True)
    store_a = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_a},
    )
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_b},
    )
    store_a.upsert_row(_row(source="plan:202608/a.md", target="plan:202608/b.md"))
    store_b.upsert_row(_row(source="plan:202608/c.md", target="plan:202608/d.md"))
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )
    now = {"t": 0.0}
    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_reconcile.time.monotonic",
        lambda: now["t"],
    )
    snapshotted: list[object] = []
    original_snapshot = ArtifactLinkStore.artifact_link_event_snapshot

    def tracking_snapshot(self: ArtifactLinkStore, **kwargs: object) -> object:
        snapshotted.append(self._store_identity())
        snapshot = original_snapshot(self, **kwargs)
        now["t"] = 50.0
        return snapshot

    monkeypatch.setattr(
        ArtifactLinkStore, "artifact_link_event_snapshot", tracking_snapshot
    )
    compatibility: list[object] = []
    original_compat = ArtifactLinkStore._iter_reconciliation_compatibility_rows

    def tracking_compat(
        self: ArtifactLinkStore,
        store: ArtifactLinkStore,
        *,
        event_snapshot: object,
    ) -> object:
        compatibility.append(store._store_identity())
        yield from original_compat(self, store, event_snapshot=event_snapshot)

    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_compatibility_rows",
        tracking_compat,
    )

    preview = store_a.preview_reconciled_aggregate(deadline=10.0)

    assert snapshotted == [store_a._store_identity()]
    assert store_b._store_identity() not in snapshotted
    assert store_b._store_identity() not in compatibility
    assert preview["skip_diagnostics"]
    assert any(
        "reconcile deadline expired" in item and "remaining store" in item
        for item in preview["skip_diagnostics"]
    )


def test_preview_does_not_raise_on_sibling_incomplete_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans_a = tmp_path / "clone-a" / "plans"
    plans_b = tmp_path / "clone-b" / "plans"
    plans_a.mkdir(parents=True)
    plans_b.mkdir(parents=True)
    store_a = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_a},
    )
    store_b = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans_b},
    )
    store_a.upsert_row(_row(source="plan:202608/a.md", target="plan:202608/b.md"))
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )

    def fake_inspect(
        sidecar_roots: object, *, project_key: str
    ) -> _ArtifactLinkCutoverInspection:
        if sidecar_roots == store_b.sidecar_roots:
            return _ArtifactLinkCutoverInspection(state="incomplete")
        return _ArtifactLinkCutoverInspection(state="none")

    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_core.inspect_artifact_link_cutover_markers",
        fake_inspect,
    )

    def fake_imported(sidecar_roots: object, *, project_key: str) -> bool:
        if sidecar_roots == store_b.sidecar_roots:
            raise RuntimeError(
                "artifact-link cutover is incomplete; resume with "
                "sase artifact link import-indexes --apply"
            )
        return False

    monkeypatch.setattr(
        "sase.sdd._artifact_link_store_rows.artifact_link_indexes_imported",
        fake_imported,
    )

    preview = store_a.preview_reconciled_aggregate()

    assert {(row["source_ref"], row["target_ref"]) for row in preview["rows"]} == {
        ("plan:202608/a.md", "plan:202608/b.md")
    }
    assert any("cutover is incomplete" in item for item in preview["skip_diagnostics"])
