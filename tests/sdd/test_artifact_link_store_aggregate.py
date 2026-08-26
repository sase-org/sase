"""Aggregate rebuild behavior for the artifact link store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _plan_index, _row, _store


def test_rebuild_carries_forward_rows_from_invisible_sidecar_clone(
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
    store_a.upsert_row(_row())

    rebuilt = store_b.rebuild_aggregate()

    assert len(rebuilt["rows"]) == 1
    assert rebuilt["rows"][0]["source_ref"] == "plan:202608/a.md"


def test_rebuild_drops_rows_deleted_from_visible_sidecar_companion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, monkeypatch)
    store.upsert_row(_row())
    for path in (_plan_index(tmp_path, "a.md"), _plan_index(tmp_path, "b.md")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["rows"] = []
        path.write_text(json.dumps(payload), encoding="utf-8")

    rebuilt = store.rebuild_aggregate()

    assert rebuilt["rows"] == []
    assert store.load_aggregate()["rows"] == []


def test_remove_rows_prunes_aggregate_even_when_sidecar_is_invisible(
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
    store_a.upsert_row(_row())

    removed = store_b.remove_rows("plan:202608/a.md", "plan:202608/b.md")

    assert [row["relation"] for row in removed] == ["implements"]
    assert store_b.load_aggregate()["rows"] == []
