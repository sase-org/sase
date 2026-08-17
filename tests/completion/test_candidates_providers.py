"""Tests for kind -> provider dispatch of pre-argparse completion candidates."""

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


def test_candidates_for_unknown_kind_returns_empty_list() -> None:
    assert candidates_for("bogus", "", project=None, limit=200) == []


def test_candidates_for_kind_without_shipped_provider_returns_empty_list() -> None:
    # "repo" is a declared ValueKind but has no provider in this phase.
    assert candidates_for("repo", "", project=None, limit=200) == []


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
        created = project.create("Fix the thing", IssueType.TASK, size=PhaseSize.SMALL)

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
