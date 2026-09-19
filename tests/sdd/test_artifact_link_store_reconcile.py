"""Cross-workspace aggregate reconciliation for the artifact link store."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoCloneRecord, RepoInventory, RepoRecord
from sase.sdd._artifact_link_cutover_state import _ArtifactLinkCutoverInspection
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
    artifact_link_aggregate_path,
)
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, _store


def test_reconcile_aggregate_collects_sidecar_rows_from_known_workspace_stores(
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
    aggregate = artifact_link_aggregate_path("gh_sase-org__sase")
    aggregate.write_text(
        json.dumps({"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )

    reconciled = store_a.reconcile_aggregate()

    assert {(row["source_ref"], row["target_ref"]) for row in reconciled["rows"]} == {
        ("plan:202608/a.md", "plan:202608/b.md"),
        ("plan:202608/c.md", "plan:202608/d.md"),
    }


def test_reconcile_aggregate_skips_unreadable_sibling_workspace_sidecar(
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
    stale = plans_b / "links" / "202608" / "old.md.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(
        json.dumps({"schema_version": 1, "artifact_ref": "plan:202608/old.md"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )

    reconciled = store_a.reconcile_aggregate()

    assert [(row["source_ref"], row["target_ref"]) for row in reconciled["rows"]] == [
        ("plan:202608/a.md", "plan:202608/b.md")
    ]
    assert len(store_a.durable_sidecar_rows()) == 1


def test_reconcile_aggregate_keeps_rows_with_unpublished_agent_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishability gates the outbox, not the local read model.

    Regression test for the defect diagnosed in
    plan:202608/link_rail_every_tab.md: `reconcile_aggregate` used to drop
    every row with an unpublished `agent:` endpoint from the aggregate, so
    an hourly chop running from a context that cannot resolve agent refs
    would silently erase the `cites`/`read` rows a workspace's own
    `rebuild_aggregate` had just written. `durable_sidecar_rows` -- the
    publication-facing view -- still filters these out.
    """

    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="agent:pending.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="prompt_ref",
            description="prompt citation",
        )
    )
    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference",
        lambda _ref, **_kwargs: SimpleNamespace(
            resolution=SimpleNamespace(status="missing")
        ),
    )

    reconciled = store.reconcile_aggregate()

    assert [(row["source_ref"], row["target_ref"]) for row in reconciled["rows"]] == [
        ("agent:pending.athena.worker", "plan:202608/a.md")
    ]
    assert store.durable_sidecar_rows() == ()


def test_reconcile_agent_rows_use_store_workspace_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    workspace = tmp_path / "workspace"
    plans = workspace / "plans"
    plans.mkdir(parents=True)
    marker = SimpleNamespace(workspace_num=12)
    context = object()
    seen: list[tuple[str, object | None]] = []
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
        sdd_store=SimpleNamespace(repo_root=workspace),  # type: ignore[arg-type]
    )
    store.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="derived",
            description="derived from a prompt header reference",
        )
    )

    monkeypatch.setattr(
        "sase.workspace_provider.find_marker_from_cwd",
        lambda cwd: (str(workspace), marker) if Path(cwd) == workspace else None,
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        lambda root, workspace_num, project=None: context,
    )

    def fake_resolve(ref: str, *, context: object | None = None, **_kwargs: object):
        seen.append((ref, context))
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference",
        fake_resolve,
    )

    rows = store.durable_sidecar_rows()

    assert len(rows) == 1
    assert seen == [("agent:alice.athena.worker", context)]


def test_durable_sidecar_rows_builds_pass_context_once(
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
    store_a.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="derived",
            description="derived from a prompt header reference",
        )
    )
    store_b.upsert_row(
        _row(
            source="agent:bob.athena.worker",
            relation="cites",
            target="plan:202608/b.md",
            origin="derived",
            description="derived from a prompt header reference",
        )
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )
    context = object()
    launch_calls = {"count": 0}

    def fake_launch(*, is_home_mode: bool) -> object:
        launch_calls["count"] += 1
        return context

    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context", fake_launch
    )
    seen_contexts: list[object | None] = []

    def fake_resolve(ref: str, *, context: object | None = None, **_kwargs: object):
        seen_contexts.append(context)
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )

    rows = store_a.durable_sidecar_rows()

    assert len(rows) == 2
    assert launch_calls["count"] == 1
    assert seen_contexts == [context, context]
    assert None not in seen_contexts


def test_durable_sidecar_rows_resolves_each_distinct_agent_ref_once(
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
    store_a.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="derived",
            description="first citation of alice",
        )
    )
    store_a.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/b.md",
            origin="derived",
            description="second citation of alice",
        )
    )
    store_b.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/c.md",
            origin="derived",
            description="third citation of alice",
        )
    )
    store_b.upsert_row(
        _row(
            source="agent:bob.athena.worker",
            relation="cites",
            target="plan:202608/d.md",
            origin="derived",
            description="citation of bob",
        )
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda *, is_home_mode: object(),
    )
    resolved_refs: list[str] = []

    def fake_resolve(ref: str, *, context: object | None = None, **_kwargs: object):
        resolved_refs.append(ref)
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )

    rows = store_a.durable_sidecar_rows()

    assert len(rows) == 4
    assert len(resolved_refs) == 2
    assert set(resolved_refs) == {
        "agent:alice.athena.worker",
        "agent:bob.athena.worker",
    }


def test_durable_sidecar_rows_dedupe_before_filter_does_not_weaken_publishability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(
        _row(
            source="agent:published.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="derived",
            description="a published citation",
        )
    )
    store.upsert_row(
        _row(
            source="agent:pending.athena.worker",
            relation="cites",
            target="plan:202608/b.md",
            origin="derived",
            description="a pending citation",
        )
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda *, is_home_mode: object(),
    )

    def fake_resolve(ref: str, *, context: object | None = None, **_kwargs: object):
        status = "exact" if ref == "agent:published.athena.worker" else "missing"
        return SimpleNamespace(resolution=SimpleNamespace(status=status))

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )

    rows = store.durable_sidecar_rows()

    assert [(row["source_ref"], row["target_ref"]) for row in rows] == [
        ("agent:published.athena.worker", "plan:202608/a.md")
    ]


def test_durable_sidecar_rows_resolves_each_agent_ref_once(
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
    store_a.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/a.md",
            origin="derived",
            description="first citation of alice",
        )
    )
    store_b.upsert_row(
        _row(
            source="agent:alice.athena.worker",
            relation="cites",
            target="plan:202608/b.md",
            origin="derived",
            description="second citation of alice",
        )
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store_a, store_b)),
    )
    launch_calls = {"count": 0}

    def fake_launch(*, is_home_mode: bool) -> object:
        launch_calls["count"] += 1
        return object()

    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context", fake_launch
    )
    resolved_refs: list[str] = []

    def fake_resolve(ref: str, *, context: object | None = None, **_kwargs: object):
        resolved_refs.append(ref)
        return SimpleNamespace(resolution=SimpleNamespace(status="exact"))

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference", fake_resolve
    )

    rows = store_a.durable_sidecar_rows()

    assert len(rows) == 2
    assert launch_calls["count"] == 1
    assert resolved_refs == ["agent:alice.athena.worker"]


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
