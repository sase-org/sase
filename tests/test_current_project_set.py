"""Write-path tests for ``set_current_project``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.current_project import (
    CurrentProject,
    resolve_current_project,
    set_current_project,
)
from sase import current_project as current_project_mod
from tests._vcs_xprompt_mru_helpers import patched_mru_file, write_named_project
from tests.test_vcs_xprompt_mru_pruning import _patch_git_and_gh_metadata


def _record(
    tmp_path: Path,
    project_key: str,
    *,
    display_name: str | None = None,
    aliases: tuple[str, ...] = (),
    state: str = "enabled",
    launchable: bool | None = None,
    vcs_kind: str | None = None,
    project_file: str | None = None,
    workspace_dir: Path | None = None,
) -> ProjectRecordWire:
    workspace = workspace_dir or (tmp_path / "workspaces" / project_key)
    workspace.mkdir(parents=True, exist_ok=True)
    project_dir = tmp_path / "projects" / project_key
    project_dir.mkdir(parents=True, exist_ok=True)
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_key,
        project_dir=str(project_dir),
        project_file=project_file or str(project_dir / f"{project_key}.sase"),
        archive_file=str(project_dir / f"{project_key}-archive.sase"),
        workspace_dir=str(workspace),
        state=state,
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled" if launchable is None else launchable,
        aliases=list(aliases),
        display_name=display_name,
        vcs_kind=vcs_kind,
    )


def _write_mru(prefixes: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": prefixes}), encoding="utf-8")
    return path


def _install_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire],
) -> None:
    monkeypatch.setattr(
        current_project_mod,
        "list_project_records",
        lambda *_a, **_k: records,
    )
    monkeypatch.setattr(
        current_project_mod,
        "find_all_patches_cached",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _path: "gh",
    )


def test_set_promotes_tail_project_to_resolver_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = _record(tmp_path, "alpha", display_name="alpha")
    tail = _record(tmp_path, "beta", display_name="beta")
    _install_snapshots(monkeypatch, [head, tail])
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru(["#gh:alpha", "#gh:beta"], mru)

    with patched_mru_file(mru):
        outcome = set_current_project("beta", projects_dir=tmp_path / "projects")
        resolved = resolve_current_project(projects_dir=tmp_path / "projects")

    assert outcome.status == "set"
    assert outcome.project is not None
    assert outcome.project.project_key == "beta"
    assert "beta is now the current project." in outcome.message
    assert resolved == CurrentProject(
        project_key="beta",
        display_name="beta",
        origin="project",
        origin_ref="beta",
        workflow_type="gh",
    )
    assert json.loads(mru.read_text(encoding="utf-8"))["entries"][0] == "#gh:beta"


def test_alias_and_display_name_write_one_canonical_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(
        tmp_path,
        "gh_acme__widgets",
        display_name="widgets",
        aliases=("docs",),
    )
    other = _record(tmp_path, "other", display_name="other")
    _install_snapshots(monkeypatch, [record, other])
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru(["#gh:other"], mru)

    with patched_mru_file(mru):
        via_alias = set_current_project("docs", projects_dir=tmp_path / "projects")
        via_display = set_current_project("widgets", projects_dir=tmp_path / "projects")

    assert via_alias.status == "set"
    assert via_alias.project is not None
    assert via_alias.project.project_key == "gh_acme__widgets"
    assert via_display.status == "unchanged"
    assert json.loads(mru.read_text(encoding="utf-8"))["entries"] == [
        "#gh:gh_acme__widgets",
        "#gh:other",
    ]


def test_already_current_leaves_mru_mtime_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, "alpha", display_name="alpha")
    _install_snapshots(monkeypatch, [record])
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru(["#gh:alpha"], mru)
    before = mru.stat().st_mtime_ns

    with patched_mru_file(mru):
        outcome = set_current_project("alpha", projects_dir=tmp_path / "projects")

    assert outcome.status == "unchanged"
    assert outcome.project is not None
    assert outcome.project.project_key == "alpha"
    assert "already the current project" in outcome.message
    assert mru.stat().st_mtime_ns == before


def test_disabled_project_is_ineligible_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enabled = _record(tmp_path, "alpha", display_name="alpha")
    disabled = _record(tmp_path, "old", display_name="old", state="disabled")
    _install_snapshots(monkeypatch, [enabled, disabled])
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru(["#gh:alpha"], mru)
    before = mru.read_text(encoding="utf-8")

    with patched_mru_file(mru):
        outcome = set_current_project("old", projects_dir=tmp_path / "projects")

    assert outcome.status == "ineligible"
    assert outcome.project is None
    assert outcome.message == "old is disabled; enable it first."
    assert mru.read_text(encoding="utf-8") == before


def test_detected_provider_survives_record_when_vcs_kind_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_and_gh_metadata(monkeypatch)
    workspace = tmp_path / "widgets-ws"
    workspace.mkdir()
    projects_dir = sase_projects_dir()
    write_named_project(projects_dir, "gh_acme__widgets", "widgets", workspace)
    spec = projects_dir / "gh_acme__widgets" / "gh_acme__widgets.sase"
    record = _record(
        tmp_path,
        "gh_acme__widgets",
        display_name="widgets",
        vcs_kind="git",
        project_file=str(spec),
        workspace_dir=workspace,
    )
    _install_snapshots(monkeypatch, [record])
    monkeypatch.setattr(
        "sase.xprompt.loader.get_known_project_workspaces",
        lambda *_a, **_k: {"gh_acme__widgets": workspace},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _path: "gh",
    )
    monkeypatch.setattr(
        "sase.ace.patch.cache.find_all_patches_cached",
        lambda *_a, **_k: [],
    )
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru(["#gh:gone"], mru)

    with patched_mru_file(mru):
        outcome = set_current_project(
            "gh_acme__widgets", projects_dir=tmp_path / "projects"
        )

    assert outcome.status == "set"
    assert outcome.project is not None
    assert outcome.project.project_key == "gh_acme__widgets"
    assert json.loads(mru.read_text(encoding="utf-8"))["entries"][0] == (
        "#gh:gh_acme__widgets"
    )


def test_unverified_reports_the_project_the_resolver_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _record(tmp_path, "alpha", display_name="alpha")
    _install_snapshots(monkeypatch, [target])
    other = CurrentProject(
        project_key="other",
        display_name="other",
        origin="project",
        origin_ref="other",
        workflow_type="gh",
    )
    monkeypatch.setattr(
        current_project_mod,
        "resolve_current_project",
        lambda **_kwargs: other,
    )
    mru = tmp_path / "vcs_xprompt_mru.json"
    _write_mru([], mru)

    with patched_mru_file(mru):
        outcome = set_current_project("alpha", projects_dir=tmp_path / "projects")

    assert outcome.status == "unverified"
    assert outcome.project == other
    assert "the resolver chose other" in outcome.message
