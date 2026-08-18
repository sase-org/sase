"""Current-project resolver over the isolated VCS xprompt MRU store."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.current_project import (
    CurrentProject,
    peek_current_project_change_token,
    resolve_current_project,
)
from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage, vcs_xprompt_mru_path
from sase import current_project as current_project_mod


@pytest.fixture(autouse=True)
def reset_peek_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_project_mod, "_token_cache_deadline", 0.0)
    monkeypatch.setattr(current_project_mod, "_token_cache_value", ())


def _record(
    tmp_path: Path,
    project_key: str,
    *,
    display_name: str | None = None,
    aliases: tuple[str, ...] = (),
    state: str = "enabled",
) -> ProjectRecordWire:
    workspace = tmp_path / "workspaces" / project_key
    workspace.mkdir(parents=True, exist_ok=True)
    project_dir = tmp_path / "projects" / project_key
    project_dir.mkdir(parents=True, exist_ok=True)
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_key,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_key}.sase"),
        archive_file=str(project_dir / f"{project_key}-archive.sase"),
        workspace_dir=str(workspace),
        state=state,
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled",
        aliases=list(aliases),
        display_name=display_name,
    )


def _write_mru(prefixes: list[str]) -> Path:
    path = vcs_xprompt_mru_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": prefixes}), encoding="utf-8")
    return path


def _install_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire],
    patches: list[object] | None = None,
) -> dict[str, int]:
    calls = {"records": 0, "patches": 0}

    def list_records(*_args: object, **_kwargs: object) -> list[ProjectRecordWire]:
        calls["records"] += 1
        return records

    def list_patches(*_args: object, **_kwargs: object) -> list[object]:
        calls["patches"] += 1
        return list(patches or [])

    monkeypatch.setattr(current_project_mod, "list_project_records", list_records)
    monkeypatch.setattr(current_project_mod, "find_all_patches_cached", list_patches)
    return calls


def test_head_project_ref_resolves_with_project_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, "gh_sase-org__sase", display_name="sase")
    _install_snapshots(monkeypatch, [record])
    _write_mru(["#gh:gh_sase-org__sase", "#gh:other"])

    assert resolve_current_project(
        projects_dir=tmp_path / "projects"
    ) == CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="gh_sase-org__sase",
        workflow_type="gh",
    )


def test_head_patch_name_resolves_owning_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, "gh_sase-org__sase", display_name="sase")
    _install_snapshots(
        monkeypatch,
        [record],
        [SimpleNamespace(name="my_patch", project_name="gh_sase-org__sase")],
    )
    _write_mru(["#gh:my_patch"])

    assert resolve_current_project(
        projects_dir=tmp_path / "projects"
    ) == CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="patch",
        origin_ref="my_patch",
        workflow_type="gh",
    )


@pytest.mark.parametrize(
    "head",
    ("#gh:owner/repo", "#git:~/src/app", "#git:home"),
)
def test_structural_head_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head: str
) -> None:
    record = _record(tmp_path, "sase", display_name="sase")
    _install_snapshots(monkeypatch, [record])
    _write_mru([head, "#gh:sase"])

    resolved = resolve_current_project(projects_dir=tmp_path / "projects")

    assert resolved is not None
    assert resolved.project_key == "sase"
    assert resolved.origin == "project"
    assert resolved.origin_ref == "sase"


def test_disabled_head_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disabled = _record(tmp_path, "old", display_name="old", state="disabled")
    enabled = _record(tmp_path, "sase", display_name="sase")
    _install_snapshots(monkeypatch, [disabled, enabled])
    _write_mru(["#gh:old", "#gh:sase"])

    resolved = resolve_current_project(projects_dir=tmp_path / "projects")

    assert resolved == CurrentProject(
        project_key="sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def test_alias_and_display_name_resolve_to_canonical_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(
        tmp_path,
        "gh_acme__widgets",
        display_name="widgets",
        aliases=("docs",),
    )
    _install_snapshots(monkeypatch, [record])
    _write_mru(["#gh:docs"])

    resolved = resolve_current_project(projects_dir=tmp_path / "projects")

    assert resolved == CurrentProject(
        project_key="gh_acme__widgets",
        display_name="widgets",
        origin="project",
        origin_ref="docs",
        workflow_type="gh",
    )

    _write_mru(["#gh:widgets"])
    resolved = resolve_current_project(projects_dir=tmp_path / "projects")
    assert resolved is not None
    assert resolved.project_key == "gh_acme__widgets"
    assert resolved.origin_ref == "widgets"


def test_empty_mru_and_unresolvable_mru_yield_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path, "sase", display_name="sase")
    _install_snapshots(monkeypatch, [record])

    assert resolve_current_project(projects_dir=tmp_path / "projects") is None

    _write_mru(["#gh:owner/repo", "#git:home", "#gh:gone"])
    assert resolve_current_project(projects_dir=tmp_path / "projects") is None


def test_resolve_reads_records_and_patches_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _record(tmp_path, "alpha", display_name="alpha")
    second = _record(tmp_path, "sase", display_name="sase")
    calls = _install_snapshots(
        monkeypatch,
        [first, second],
        [SimpleNamespace(name="my_patch", project_name="sase")],
    )
    _write_mru(["#gh:owner/repo", "#gh:gone", "#gh:sase", "#gh:alpha"])

    resolved = resolve_current_project(projects_dir=tmp_path / "projects")

    assert resolved is not None
    assert resolved.project_key == "sase"
    assert calls["records"] == 1
    assert calls["patches"] == 1


def test_peek_token_is_stable_across_repeated_calls() -> None:
    first = peek_current_project_change_token()
    current_project_mod._token_cache_deadline = 0.0

    assert peek_current_project_change_token() == first


def test_peek_token_changes_after_record_rewrites_the_file() -> None:
    before = peek_current_project_change_token()

    record_vcs_xprompt_usage("#gh:sase")
    current_project_mod._token_cache_deadline = 0.0

    after = peek_current_project_change_token()

    assert after != before
    assert vcs_xprompt_mru_path().is_file()


def test_peek_stat_error_degrades_to_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(path: Path) -> object:
        del path
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "stat", boom)

    assert (
        peek_current_project_change_token() == current_project_mod._TOKEN_ERROR_SENTINEL
    )
