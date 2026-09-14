"""Tests for artifact-link doctor rename repair."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.artifact_cli.link_health import inspect_artifact_link_health
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main._artifact_cli_link_health_helpers import stub_resolve_cli_reference


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

    stub_resolve_cli_reference(monkeypatch, resolve)

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

    stub_resolve_cli_reference(monkeypatch, resolve)

    report = inspect_artifact_link_health(fix=True)

    assert report.dangling == ()
    aggregate_targets = {row["target_ref"] for row in store.load_aggregate()["rows"]}
    assert "research:202608/source.md" not in aggregate_targets
    assert "research:202608/source_renamed.md" in aggregate_targets
