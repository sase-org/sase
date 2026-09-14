"""Tests for artifact-link doctor inspection reports."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main._artifact_cli_link_health_helpers import stub_resolve_cli_reference


def test_inspect_reports_store_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: (_ for _ in ()).throw(RuntimeError("bad project key")),
    )
    report = inspect_artifact_link_health()
    assert report.skipped is False
    assert report.errors == ("bad project key",)
    assert report.healthy is False


def test_inspect_treats_existing_bead_refs_as_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path / "beads") as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={},
            beads_dir=project.beads_dir,
        )
        store.upsert_row(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "source_ref": f"bead:{left.id}",
                "relation": "related",
                "target_ref": f"bead:{right.id}",
                "description": "same root cause",
                "origin": "manual",
                "created_by": "agent",
                "created_at": "2026-08-21T00:00:00Z",
                "uses": 1,
            }
        )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    stub_resolve_cli_reference(
        monkeypatch,
        lambda _ref, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("no generated page")
        ),
    )

    report = inspect_artifact_link_health()

    assert report.dangling == ()
    assert report.healthy is True


def test_inspect_fix_reconciles_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Store:
        project_key = "gh_sase-org__sase"
        sidecar_roots: dict[str, Path] = {}
        beads_dir = None

        def reconcile_aggregate(self) -> dict[str, object]:
            calls.append("reconcile")
            return {"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}

        def load_aggregate(self) -> dict[str, object]:
            return {"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}

        def preview_aggregate(self) -> dict[str, object]:
            return {"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}

        def load_durable_rows(self) -> tuple[dict[str, object], ...]:
            return ()

        def durable_sidecar_rows(self) -> tuple[dict[str, object], ...]:
            return ()

    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: Store(),
    )

    report = inspect_artifact_link_health(fix=True)

    assert calls == ["reconcile"]
    assert report.rebuilt is True
    assert report.healthy is True


def test_inspect_reports_invalid_event_objects_as_unhealthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    root = tmp_path / "plans"
    root.mkdir()
    invalid = root / "link-events" / "v1" / "aa" / "bad.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{}\n", encoding="utf-8")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": root},
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )

    report = inspect_artifact_link_health()

    assert report.healthy is False
    assert report.event_validation_failures
    assert "link-events/v1/aa/bad.json" in report.event_validation_failures[0]


def test_unpublished_agent_refs_are_informational(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    (plans / "202608").mkdir(parents=True)
    (plans / "202608" / "a.md").write_text("# A\n", encoding="utf-8")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "agent:pending.athena.worker",
            "relation": "cites",
            "target_ref": "plan:202608/a.md",
            "description": "prompt citation",
            "origin": "prompt_ref",
            "created_by": "pending.athena.worker",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        }
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )

    def resolve(ref: str, **_kwargs: object) -> object:
        status = "missing" if ref.startswith("agent:") else "exact"
        return SimpleNamespace(
            resolution=SimpleNamespace(status=status, resolved_path=None)
        )

    stub_resolve_cli_reference(monkeypatch, resolve)

    report = inspect_artifact_link_health()

    assert report.dangling == ()
    assert report.unpublished_agent_refs == ("agent:pending.athena.worker",)
    assert report.healthy is True


def test_missing_sidecar_roots_are_skipped_for_head_index_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"research": tmp_path / "missing-research"},
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )

    report = inspect_artifact_link_health()

    assert report.missing_head_indexes == ()
    assert report.healthy is True


def test_inspect_reports_row_level_aggregate_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "agent:pending.athena.worker",
            "relation": "cites",
            "target_ref": "plan:202608/a.md",
            "description": "prompt citation",
            "origin": "prompt_ref",
            "created_by": "agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        }
    )
    store._write_aggregate({"rows": []})  # noqa: SLF001 - simulate stale index
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    stub_resolve_cli_reference(
        monkeypatch,
        lambda _ref, **_kwargs: SimpleNamespace(
            resolution=SimpleNamespace(status="exact", resolved_path=None)
        ),
    )

    report = inspect_artifact_link_health()

    assert report.healthy is False
    assert report.aggregate_drift.missing.total == 1
    assert report.aggregate_drift.missing.by_relation == (("cites", 1),)
    assert report.aggregate_drift.missing.by_origin == (("prompt_ref", 1),)
    assert report.aggregate_drift.missing.rows[0].source_ref == (
        "agent:pending.athena.worker"
    )
