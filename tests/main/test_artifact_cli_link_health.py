"""Tests for artifact-link doctor health."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.artifact_cli.doctor import handle_doctor
from sase.artifact_cli.link_health import ArtifactLinkHealthReport
from sase.artifact_cli.link_health import _ArtifactLinkCoveragePopulation
from sase.artifact_cli.link_health import _ArtifactLinkCoverageReport
from sase.artifact_cli.link_health import _curated_peer_keys
from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.artifact_file_facade import ArtifactFileIndexInspection
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


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
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
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


def test_inspect_fix_repairs_historical_research_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    root = tmp_path / "research"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=root,
        check=True,
    )
    source = root / "202608" / "source.md"
    lead = root / "202608" / "lead.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    lead.write_text("# Lead\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"research": root},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "research:202608/lead.md",
            "relation": "derives-from",
            "target_ref": "research:202608/source.md",
            "description": "lead consolidation includes the source report",
            "origin": "manual",
            "created_by": "agent",
            "created_at": "2026-08-21T00:00:00Z",
            "uses": 1,
        }
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add links"], cwd=root, check=True)
    subprocess.run(
        ["git", "mv", "202608/source.md", "202608/source_renamed.md"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-am", "rename source"], cwd=root, check=True
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )

    def resolve(ref: str, **_kwargs: object) -> object:
        status = "missing" if ref.endswith("source.md") else "exact"
        return SimpleNamespace(
            resolution=SimpleNamespace(status=status, resolved_path=None)
        )

    monkeypatch.setattr("sase.artifact_cli.link_health.resolve_cli_reference", resolve)

    report = inspect_artifact_link_health(fix=True)

    assert report.dangling == ()
    assert report.orphaned_companions == ()
    assert report.repaired_renames == 1
    assert report.healthy is True
    assert not (root / "links" / "202608" / "source.md.json").exists()
    payload = json.loads(
        (root / "links" / "202608" / "source_renamed.md.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["artifact_ref"] == "research:202608/source_renamed.md"
    assert payload["rows"][0]["target_ref"] == "research:202608/source_renamed.md"


def test_inspect_fix_does_not_reintroduce_renamed_rows_from_sibling_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    root = tmp_path / "research"
    sibling = tmp_path / "sibling-research"
    root.mkdir()
    sibling.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=root,
        check=True,
    )
    source = root / "202608" / "source.md"
    lead = root / "202608" / "lead.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    lead.write_text("# Lead\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    row = {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "research:202608/lead.md",
        "relation": "derives-from",
        "target_ref": "research:202608/source.md",
        "description": "lead consolidation includes the source report",
        "origin": "manual",
        "created_by": "agent",
        "created_at": "2026-08-21T00:00:00Z",
        "uses": 1,
    }
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"research": root},
    )
    sibling_store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"research": sibling},
    )
    store.upsert_row(row)
    sibling_store.upsert_row(row)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add links"], cwd=root, check=True)
    subprocess.run(
        ["git", "mv", "202608/source.md", "202608/source_renamed.md"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-am", "rename source"], cwd=root, check=True
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        ArtifactLinkStore,
        "_iter_reconciliation_stores",
        lambda _self: iter((store, sibling_store)),
    )

    def resolve(ref: str, **_kwargs: object) -> object:
        status = "missing" if ref.endswith("source.md") else "exact"
        return SimpleNamespace(
            resolution=SimpleNamespace(status=status, resolved_path=None)
        )

    monkeypatch.setattr("sase.artifact_cli.link_health.resolve_cli_reference", resolve)

    report = inspect_artifact_link_health(fix=True)

    assert report.dangling == ()
    aggregate_targets = {row["target_ref"] for row in store.load_aggregate()["rows"]}
    assert "research:202608/source.md" not in aggregate_targets
    assert "research:202608/source_renamed.md" in aggregate_targets


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

    monkeypatch.setattr("sase.artifact_cli.link_health.resolve_cli_reference", resolve)

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
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
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


def test_doctor_reports_link_divergence_counters(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        lambda: ArtifactFileIndexInspection(
            total_rows=0,
            supported_rows=0,
            vcs_reference_rows=0,
            missing_enrichment_ids=(),
            missing_stored_path_ids=(),
            missing_source_path_ids=(),
            vcs_provenance_incomplete_ids=(),
            duplicate_ids=(),
            unrecognized_schema_versions=(),
            malformed_rows=0,
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_link_health",
        lambda *, fix=False: ArtifactLinkHealthReport(
            skipped=False,
            read_events=3,
            recorded_read_events=2,
            durable_read_rows=1,
            durable_sidecar_rows=4,
            aggregate_rows=5,
            coverage=_ArtifactLinkCoverageReport(
                populations=(
                    _ArtifactLinkCoveragePopulation(
                        name="research-swarm filename lineage",
                        linked=1,
                        total=2,
                    ),
                ),
                rows_by_origin=(("derived", 2), ("manual", 3)),
                rows_by_relation=(("derives-from", 2), ("related", 3)),
            ),
        ),
    )

    assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "Sidecar vs aggregate links" in output
    assert "4 durable / 5 aggregate" in output
    assert "Read events vs durable rows" in output
    assert "2 recorded / 1 durable" in output
    assert "Derived coverage" in output
    assert "1 linked / 2 candidates" in output
    assert "Rows by origin" in output
    assert "derived: 2, manual: 3" in output
    assert "Rows by relation" in output
    assert "derives-from: 2, related: 3" in output


def test_curated_peer_keys_treats_derived_origin_as_curated() -> None:
    rows = [
        {
            "source_ref": "plan:202608/x.md",
            "relation": "implements",
            "target_ref": "bead:sase-tw",
            "origin": "derived",
        }
    ]
    assert _curated_peer_keys("plan:202608/x.md", rows) == {
        ("implements", "bead:sase-tw")
    }


def test_derived_row_rendered_in_links_table_is_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    document = plans / "x.md"
    table = {
        "schema_version": 1,
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
        ],
        "rows": [
            {
                "values": {
                    "relation": "implements",
                    "artifact": "bead:sase-tw",
                    "why": "derived from plan bead_id: frontmatter",
                },
                "link_targets": {},
            }
        ],
        "omitted": 0,
    }
    seeded = str(require_rust_binding("links_block_upsert")("# X\n", table))
    document.write_text(seeded, encoding="utf-8")

    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "plan:x.md",
            "relation": "implements",
            "target_ref": "bead:sase-tw",
            "description": "derived from plan bead_id: frontmatter",
            "origin": "derived",
            "created_by": "sase",
            "created_at": "2026-08-25T00:00:00Z",
            "uses": 1,
        }
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
        lambda _ref, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("no generated page")
        ),
    )

    report = inspect_artifact_link_health()

    assert report.stale_tables == ()


def test_missing_derived_row_projection_is_reported_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    document = plans / "x.md"
    stale_table = {
        "schema_version": 1,
        "columns": [
            {"key": "relation", "label": "Relation", "numeric": False},
            {"key": "artifact", "label": "Artifact", "numeric": False},
            {"key": "why", "label": "Why", "numeric": False},
        ],
        "rows": [
            {
                "values": {
                    "relation": "related",
                    "artifact": "plan:other.md",
                    "why": "stale projection",
                },
                "link_targets": {},
            }
        ],
        "omitted": 0,
    }
    seeded = str(require_rust_binding("links_block_upsert")("# X\n", stale_table))
    document.write_text(seeded, encoding="utf-8")

    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "plan:x.md",
            "relation": "implements",
            "target_ref": "bead:sase-tw",
            "description": "derived from plan bead_id: frontmatter",
            "origin": "derived",
            "created_by": "sase",
            "created_at": "2026-08-25T00:00:00Z",
            "uses": 1,
        }
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
        lambda _ref, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("no generated page")
        ),
    )

    report = inspect_artifact_link_health()

    assert report.stale_tables == ("plan:x.md",)


def test_fix_does_not_rewrite_when_marker_text_is_unmanaged_prose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    plans.mkdir()
    document = plans / "x.md"
    original = (
        "# X\n\n"
        "| Layer | Contract |\n"
        "| --- | --- |\n"
        "| Projection | `<!-- sase:links:start -->` appears in docs prose |\n\n"
        "Body that must stay intact.\n"
    )
    document.write_text(original, encoding="utf-8")
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    store.upsert_row(
        {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "source_ref": "plan:x.md",
            "relation": "implements",
            "target_ref": "bead:sase-tw",
            "description": "derived from plan bead_id: frontmatter",
            "origin": "derived",
            "created_by": "sase",
            "created_at": "2026-08-25T00:00:00Z",
            "uses": 1,
        }
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_health.resolve_cli_reference",
        lambda _ref, **_kwargs: SimpleNamespace(
            resolution=SimpleNamespace(status="exact", resolved_path=None)
        ),
    )

    inspect_artifact_link_health(fix=True)

    assert document.read_text(encoding="utf-8") == original


def test_doctor_reports_skipped_link_checks_for_missing_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_file_index",
        lambda: ArtifactFileIndexInspection(
            total_rows=0,
            supported_rows=0,
            vcs_reference_rows=0,
            missing_enrichment_ids=(),
            missing_stored_path_ids=(),
            missing_source_path_ids=(),
            vcs_provenance_incomplete_ids=(),
            duplicate_ids=(),
            unrecognized_schema_versions=(),
            malformed_rows=0,
        ),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.doctor.inspect_artifact_link_health",
        lambda *, fix=False: ArtifactLinkHealthReport(skipped=True),
    )
    assert handle_doctor(argparse.Namespace(fix=False, verify=False)) == 0
    output = capsys.readouterr().out
    assert "healthy" in output
    assert "skipped (no store)" in output
