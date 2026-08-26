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
