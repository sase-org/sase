"""Relation catalog assembly and project key resolution for artifact links."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.sdd.artifact_link_store import (
    ArtifactLinkStore,
    assembled_artifact_relations,
    resolve_artifact_link_project_key,
)
from tests._conftest_environment import redirect_sase_home


def test_assembled_relations_are_builtins_then_plugins_then_config() -> None:
    plugin = {
        "schema_version": 1,
        "slug": "plugin-rel",
        "inverse": "plugin-rel-by",
        "directed": True,
        "written_by": "plugin",
    }
    relations = assembled_artifact_relations(plugins=(plugin,), config=())
    slugs = [item["slug"] for item in relations]
    assert slugs[:6] == [
        "cites",
        "read",
        "related",
        "supersedes",
        "implements",
        "derives-from",
    ]
    assert slugs[-1] == "plugin-rel"


def test_project_key_resolution_maps_provider_slug_to_canonical_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=[],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    assert resolve_artifact_link_project_key(tmp_path) == "gh_sase-org__sase"


def test_invalid_project_key_is_rejected_before_sidecar_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = tmp_path / "plans"
    plans.mkdir()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with pytest.raises(ValueError, match="invalid project key"):
        ArtifactLinkStore(
            project_key="sase-org/sase",
            sidecar_roots={"plan": plans},
        )
    assert not list(plans.rglob("*.json"))
    assert not list(plans.rglob("*.lock"))


def test_unresolvable_provider_slug_returns_no_project_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="missing-org/missing", project_name="")
    record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=[],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    assert resolve_artifact_link_project_key(tmp_path) is None


def test_marker_display_name_does_not_become_direct_project_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = SimpleNamespace(project_key="sase-org/sase", project_name="sase")
    monkeypatch.setattr(
        "sase.workspace_provider.marker.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [],
    )

    assert resolve_artifact_link_project_key(tmp_path) is None
