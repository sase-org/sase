"""Unit tests for cross-project bead-store routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cross_project
from sase.bead.cross_project import (
    AmbiguousBeadProjectError,
    origin_for_bead_id,
    origin_for_project_ref,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire


def _record(
    project_name: str,
    *,
    workspace_dir: str,
    display_name: str | None = None,
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=1,
        project_name=project_name,
        project_dir=f"/projects/{project_name}",
        project_file=f"/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=workspace_dir,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=aliases or [],
        display_name=display_name,
    )


def _store(tmp_path: Path, name: str, prefix: str) -> Path:
    beads_dir = tmp_path / name / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text(
        json.dumps({"issue_prefix": prefix}),
        encoding="utf-8",
    )
    return beads_dir


@pytest.mark.parametrize(
    ("bead_id", "expected"),
    [
        ("bob-cli-1e", "bob-cli"),
        ("bob-cli-1e.2", "bob-cli"),
        ("sase-a", "sase"),
        ("1e", None),
        ("bob-cli-", None),
        ("bob cli-1", None),
        ("bob-cli-1.x", None),
    ],
)
def test_bead_id_prefix(bead_id: str, expected: str | None) -> None:
    assert cross_project._bead_id_prefix(bead_id) == expected


def test_origin_for_bead_id_matches_registry_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = _store(tmp_path, "bob", "bob-cli")
    records = [
        _record(
            "gh_bobs-org__bob-cli",
            workspace_dir=str(tmp_path / "bob"),
            display_name="bob-cli",
        )
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda project: beads_dir if project == "gh_bobs-org__bob-cli" else None,
    )

    origin = origin_for_bead_id("bob-cli-1e")

    assert origin is not None
    assert origin.project_key == "gh_bobs-org__bob-cli"
    assert origin.project_label == "bob-cli"
    assert origin.beads_dir == beads_dir


def test_origin_for_bead_id_matches_custom_store_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = _store(tmp_path, "gold", "gold")
    records = [
        _record("gh_acme__widgets", workspace_dir=str(tmp_path / "widgets")),
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    origin = origin_for_bead_id("gold-a1")

    assert origin is not None
    assert origin.project_key == "gh_acme__widgets"
    assert origin.project_label == "gh_acme__widgets"


def test_registry_prefix_disagreement_falls_through_to_store_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_dir = _store(tmp_path, "bob", "custom")
    custom_dir = _store(tmp_path, "custom-owner", "bob-cli")
    records = [
        _record(
            "gh_bobs-org__bob-cli",
            workspace_dir=str(tmp_path / "bob"),
            display_name="bob-cli",
        ),
        _record(
            "gh_other__custom",
            workspace_dir=str(tmp_path / "custom-owner"),
            display_name="custom-owner",
        ),
    ]
    stores = {
        "gh_bobs-org__bob-cli": bob_dir,
        "gh_other__custom": custom_dir,
    }
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda project: stores[project],
    )

    origin = origin_for_bead_id("bob-cli-1")

    assert origin is not None
    assert origin.project_key == "gh_other__custom"


def test_origin_for_bead_id_reports_registry_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("one", workspace_dir=str(tmp_path / "one"), display_name="bob-cli"),
        _record("two", workspace_dir=str(tmp_path / "two"), aliases=["bob-cli"]),
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)

    with pytest.raises(AmbiguousBeadProjectError) as excinfo:
        origin_for_bead_id("bob-cli-1")

    message = str(excinfo.value)
    assert "bob-cli" in message
    assert "one" in message
    assert "two" in message


def test_origin_for_bead_id_returns_none_for_unknown_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record("sase", workspace_dir=str(tmp_path / "sase"))]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: None,
    )

    assert origin_for_bead_id("bob-cli-1") is None


def test_origin_for_bead_id_returns_unmaterialized_registry_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record("bob-cli", workspace_dir=str(tmp_path / "bob-cli"))]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: None,
    )

    origin = origin_for_bead_id("bob-cli-1")

    assert origin is not None
    assert origin.project_key == "bob-cli"
    assert origin.beads_dir is None


def test_origin_for_project_ref_matches_alias_case_insensitively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = _store(tmp_path, "bob", "bob-cli")
    records = [
        _record(
            "gh_bobs-org__bob-cli",
            workspace_dir=str(tmp_path / "bob"),
            display_name="bob-cli",
            aliases=["Bob"],
        )
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    origin = origin_for_project_ref("bob")

    assert origin is not None
    assert origin.project_key == "gh_bobs-org__bob-cli"


def test_origin_for_project_ref_returns_none_for_unknown_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: [])

    assert origin_for_project_ref("missing") is None
