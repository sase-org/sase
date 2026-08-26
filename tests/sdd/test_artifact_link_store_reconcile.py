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


def test_reconcile_aggregate_skips_unpublished_agent_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        lambda _ref: SimpleNamespace(resolution=SimpleNamespace(status="missing")),
    )

    reconciled = store.reconcile_aggregate()

    assert reconciled["rows"] == []


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
