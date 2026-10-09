"""Tests for pager bead-ID prefix discovery."""

from __future__ import annotations

import pytest

from sase.bead import cross_project
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.pager.bead_prefixes import _bead_id_prefix_of, pager_bead_id_prefixes


def test_bead_id_prefix_of() -> None:
    assert _bead_id_prefix_of("bob-cli-5s.10") == "bob-cli"
    assert _bead_id_prefix_of("sase-1h8") == "sase"
    assert _bead_id_prefix_of("nodash") is None
    assert _bead_id_prefix_of("") is None


def test_pager_bead_id_prefixes_unions_enabled_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead.cross_project.enabled_project_ref_prefixes",
        lambda: ("sase", "bob-cli"),
    )
    assert pager_bead_id_prefixes(("sase-1h8",)) == ("bob-cli", "sase")


def test_pager_bead_id_prefixes_degrades_when_lookup_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> tuple[str, ...]:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr("sase.bead.cross_project.enabled_project_ref_prefixes", _boom)
    assert pager_bead_id_prefixes(("bob-cli-5s.1",)) == ("bob-cli",)


def _record(
    project_name: str,
    *,
    display_name: str | None = None,
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=1,
        project_name=project_name,
        project_dir=f"/projects/{project_name}",
        project_file=f"/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=f"/projects/{project_name}",
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=aliases or [],
        display_name=display_name,
    )


def test_enabled_project_ref_prefixes_unions_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("gh_bobs-org__bob-cli", display_name="bob-cli", aliases=["bob"]),
        _record("sase", display_name=None, aliases=[]),
    ]
    monkeypatch.setattr(cross_project, "list_project_records", lambda *a, **k: records)
    assert cross_project.enabled_project_ref_prefixes() == (
        "bob",
        "bob-cli",
        "gh_bobs-org__bob-cli",
        "sase",
    )
