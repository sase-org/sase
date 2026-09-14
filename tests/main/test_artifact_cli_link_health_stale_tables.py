"""Tests for artifact-link doctor stale-table detection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.artifact_cli._link_health_tables import _curated_peer_keys
from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main._artifact_cli_link_health_helpers import stub_resolve_cli_reference


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
    stub_resolve_cli_reference(
        monkeypatch,
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
    stub_resolve_cli_reference(
        monkeypatch,
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
    stub_resolve_cli_reference(
        monkeypatch,
        lambda _ref, **_kwargs: SimpleNamespace(
            resolution=SimpleNamespace(status="exact", resolved_path=None)
        ),
    )

    inspect_artifact_link_health(fix=True)

    assert document.read_text(encoding="utf-8") == original
