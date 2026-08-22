"""Tests for project and inventory-backed completion candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.core.project_lifecycle_facade as project_lifecycle_facade
from sase.bead.model import IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.completion.candidates.protocol import Candidate
from sase.completion.candidates.providers import candidates_for
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    monkeypatch.delenv("SASE_SDD_BEADS_DIR", raising=False)
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)


def test_project_candidates_render_display_name_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme_widgets",
        project_dir="/tmp/acme_widgets",
        project_file="/tmp/acme_widgets/acme_widgets.sase",
        archive_file=None,
        workspace_dir="/tmp/acme_widgets/ws",
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Acme Widgets",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )

    result = candidates_for("project", "", project=None, limit=200)

    assert result == [Candidate("Acme Widgets", "enabled")]


def test_project_candidates_falls_back_to_key_without_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme_widgets",
        project_dir="/tmp/acme_widgets",
        project_file="/tmp/acme_widgets/acme_widgets.sase",
        archive_file=None,
        workspace_dir="/tmp/acme_widgets/ws",
        state="disabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=False,
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )

    result = candidates_for("project", "", project=None, limit=200)

    assert result == [Candidate("acme_widgets", "disabled")]


def test_project_candidates_respects_prefix_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        ProjectRecordWire(
            schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
            project_name=name,
            project_dir=f"/tmp/{name}",
            project_file=f"/tmp/{name}/{name}.sase",
            archive_file=None,
            workspace_dir=None,
            state="enabled",
            state_explicit=True,
            system_managed=False,
            active_claim_count=0,
            launchable=False,
        )
        for name in ("alpha", "alt", "beta")
    ]
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: records,
    )

    result = candidates_for("project", "al", project=None, limit=1)

    assert result == [Candidate("alpha", "enabled")]


def test_bead_candidates_lists_ids_and_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)

    with BeadProject(tmp_path) as project:
        created = project.create(
            "Fix the thing", IssueType.TASK, task_type="bug", size=PhaseSize.SMALL
        )

    result = candidates_for("bead", "", project=None, limit=200)

    assert result == [Candidate(created.id, "Fix the thing")]


def test_bead_candidates_without_a_store_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert candidates_for("bead", "", project=None, limit=200) == []


def test_candidates_for_caches_between_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_COMPLETION_NO_CACHE", raising=False)
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme",
        project_dir="/tmp/acme",
        project_file="/tmp/acme/acme.sase",
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=False,
    )
    calls: list[int] = []

    def fake_list_project_records(
        *args: object, **kwargs: object
    ) -> list[ProjectRecordWire]:
        calls.append(1)
        return [record]

    monkeypatch.setattr(
        project_lifecycle_facade, "list_project_records", fake_list_project_records
    )

    first = candidates_for("project", "", project=None, limit=200)
    second = candidates_for("project", "", project=None, limit=200)

    assert first == second == [Candidate("acme", "enabled")]
    assert len(calls) == 1


def test_repo_candidates_use_display_name_and_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase._repo_inventory_models import RepoInventory, RepoRecord
    import sase.repo_inventory as repo_inventory

    records = [
        RepoRecord(
            name="sase",
            slug="sase",
            kind="primary",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase",
            exists=True,
            auto_clone=False,
            description=None,
            source="project",
            env_name=None,
        ),
        RepoRecord(
            name="sase-core",
            slug="sase-core",
            kind="linked",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase-core",
            exists=True,
            auto_clone=True,
            description=None,
            source="config",
            env_name=None,
        ),
        RepoRecord(
            name="sase",
            slug="sase",
            kind="sidecar",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase-sidecar",
            exists=True,
            auto_clone=False,
            description=None,
            source="sdd",
            env_name=None,
        ),
        RepoRecord(
            name="other-core",
            slug="other-core",
            kind="linked",
            project="Other",
            project_key="other",
            path="/tmp/other-core",
            exists=True,
            auto_clone=True,
            description=None,
            source="config",
            env_name=None,
        ),
    ]

    def fake_collect_repo_inventory(**kwargs: object) -> RepoInventory:
        project = kwargs.get("project")
        if project is None:
            return RepoInventory(tuple(records))
        return RepoInventory(
            tuple(
                record
                for record in records
                if project in {record.project, record.project_key}
            )
        )

    monkeypatch.setattr(
        repo_inventory,
        "collect_repo_inventory",
        fake_collect_repo_inventory,
    )

    result = candidates_for("repo", "", project=None, limit=200)
    scoped = candidates_for("repo", "", project="sase", limit=200)

    assert result == [
        Candidate("sase", "primary · sase"),
        Candidate("sase-core", "linked · sase"),
        Candidate("other-core", "linked · Other"),
    ]
    assert scoped == [
        Candidate("sase", "primary · sase"),
        Candidate("sase-core", "linked · sase"),
    ]


def test_workspace_candidates_use_display_project_and_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="demo",
        project_dir=str(tmp_path / "demo"),
        project_file=str(tmp_path / "demo" / "demo.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / "demo" / "checkout"),
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Demo",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    registry = tmp_path / "workspaces" / "demo" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        '{"workspaces": {"12": {"role": "claim"}}}',
        encoding="utf-8",
    )

    result = candidates_for("workspace", "", project=None, limit=200)

    assert result == [
        Candidate("0", "Demo primary"),
        Candidate("12", "Demo claim"),
    ]


def test_plugin_candidates_skip_the_sase_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.plugins.inventory import (
        PluginInventory,
        _PluginDistributionRecord,
        _PluginEntryPointRecord,
    )
    import sase.plugins.inventory as plugin_inventory

    inventory = PluginInventory(
        entry_points=(
            _PluginEntryPointRecord(
                group="sase_vcs",
                name="github",
                value="sase_github:plugin",
                package="sase-github",
                version="1.2.3",
                load_status="not_loaded",
            ),
            _PluginEntryPointRecord(
                group="sase_config",
                name="core",
                value="sase.config:plugin",
                package="sase",
                version="0.0.0",
                load_status="not_loaded",
            ),
        ),
        distributions=(
            _PluginDistributionRecord("sase-github", "1.2.3", ("sase_vcs:github",)),
            _PluginDistributionRecord("sase", "0.0.0", ("sase_config:core",)),
        ),
        disabled_env=(),
    )
    monkeypatch.setattr(
        plugin_inventory,
        "collect_plugin_inventory",
        lambda **kwargs: inventory,
    )

    result = candidates_for("plugin", "", project=None, limit=200)

    assert Candidate("sase-github", "1.2.3") in result
    assert Candidate("github", "sase-github") in result
    assert all(candidate.value not in {"sase", "core"} for candidate in result)
