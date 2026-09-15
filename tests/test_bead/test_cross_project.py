"""Unit tests for cross-project bead-store routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead import cross_project
from sase.bead.cross_project import (
    AmbiguousBeadProjectError,
    origin_for_project_ref,
)
from sase.bead.jsonl import _issue_to_dict
from sase.bead.model import Issue, IssueType
from sase.core.bead_target_routing_facade import BeadTargetRoute
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


def _store(
    tmp_path: Path,
    name: str,
    prefix: str,
    *issue_ids: str,
) -> Path:
    beads_dir = tmp_path / name / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text(
        json.dumps({"issue_prefix": prefix}),
        encoding="utf-8",
    )
    (beads_dir / "issues.jsonl").write_text(
        "".join(
            json.dumps(
                _issue_to_dict(
                    Issue(
                        id=issue_id,
                        title=issue_id,
                        issue_type=IssueType.TASK,
                    )
                ),
                separators=(",", ":"),
            )
            + "\n"
            for issue_id in issue_ids
        ),
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
    assert cross_project.bead_id_prefix(bead_id) == expected


def _route_full_id(bead_id: str) -> BeadTargetRoute:
    snapshots = cross_project.enabled_project_store_snapshots()
    route = cross_project.route_full_id_with_snapshots(bead_id, snapshots)
    assert route is not None
    return route


def test_route_full_id_matches_registry_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = _store(tmp_path, "bob", "bob-cli", "bob-cli-1e")
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

    route = _route_full_id("bob-cli-1e")

    assert route.error is None
    assert route.resolved_id == "bob-cli-1e"
    assert route.store is not None
    assert route.store.project_key == "gh_bobs-org__bob-cli"
    assert route.store.project_label == "bob-cli"
    assert route.store.beads_dir == beads_dir


def test_route_full_id_matches_custom_store_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = _store(tmp_path, "gold", "gold", "gold-a1")
    records = [
        _record("gh_acme__widgets", workspace_dir=str(tmp_path / "widgets")),
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    route = _route_full_id("gold-a1")

    assert route.error is None
    assert route.store is not None
    assert route.store.project_key == "gh_acme__widgets"
    assert route.store.project_label == "gh_acme__widgets"


def test_registry_prefix_disagreement_falls_through_to_store_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bob_dir = _store(tmp_path, "bob", "custom", "custom-1")
    custom_dir = _store(tmp_path, "custom-owner", "bob-cli", "bob-cli-1")
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

    route = _route_full_id("bob-cli-1")

    assert route.error is None
    assert route.store is not None
    assert route.store.project_key == "gh_other__custom"


def test_route_full_id_reports_exact_id_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_dir = _store(tmp_path, "one", "bob-cli", "bob-cli-1")
    second_dir = _store(tmp_path, "two", "other", "bob-cli-1")
    records = [
        _record("one", workspace_dir=str(tmp_path / "one"), display_name="bob-cli"),
        _record("two", workspace_dir=str(tmp_path / "two"), aliases=["bob-cli"]),
    ]
    stores = {"one": first_dir, "two": second_dir}
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda project: stores[project],
    )

    route = _route_full_id("bob-cli-1")

    assert route.error is not None
    assert route.error.kind == "ambiguous"
    message = route.error.message
    assert "bob-cli-1" in message
    assert "one" in message
    assert "two" in message


def test_route_full_id_reports_unknown_prefix_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record("sase", workspace_dir=str(tmp_path / "sase"))]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: None,
    )

    route = _route_full_id("bob-cli-1")

    assert route.error is not None
    assert route.error.kind == "not_found"


def test_route_full_id_reports_unmaterialized_prefix_without_exact_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record("bob-cli", workspace_dir=str(tmp_path / "bob-cli"))]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: None,
    )

    route = _route_full_id("bob-cli-1")

    assert route.error is not None
    assert route.error.kind == "unavailable"
    assert "not materialized" in route.error.message


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
