"""Cross-workspace aggregate reconciliation for the artifact link store."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

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
