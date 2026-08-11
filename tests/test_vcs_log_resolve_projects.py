"""Tests for ``sase stitch list`` resolution across project inventories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import sase.vcs_log.resolve as resolve_module
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.vcs_log.resolve import resolve_log_repos


@dataclass(frozen=True)
class _FakeLinked:
    name: str
    primary_dir: str
    workspace_dir: str = ""
    kind: str = "linked"


@dataclass(frozen=True)
class _FakeLinkedResolution:
    repos: tuple[_FakeLinked, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FakeRecord:
    repo: str | None


def _global_record(
    tmp_path: Path,
    project_name: str,
    *,
    state: str = "enabled",
    display_name: str | None = None,
    aliases: list[str] | None = None,
    warnings: list[str] | None = None,
    parse_warnings: list[str] | None = None,
) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    workspace_dir = tmp_path / "workspaces" / project_name
    workspace_dir.mkdir(parents=True)
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: {project_name}\n",
        encoding="utf-8",
    )
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(workspace_dir),
        state=state,
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled",
        aliases=aliases or [],
        warnings=warnings or [],
        parse_warnings=parse_warnings or [],
        display_name=display_name,
    )


def _configure_global_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    records: list[ProjectRecordWire],
    *,
    linked: dict[str, _FakeLinkedResolution] | None = None,
    sdd: dict[str, Path | None] | None = None,
    sdd_records: dict[str, _FakeRecord] | None = None,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        resolve_module, "sase_projects_dir", lambda: tmp_path / "projects"
    )

    def fake_list(root, states, *, include_home):  # type: ignore[no-untyped-def]
        calls.append({"root": root, "states": states, "include_home": include_home})
        selected = (
            {"enabled", "disabled", "sibling"}
            if states == "all"
            else ({states} if isinstance(states, str) else set(states))
        )
        return [record for record in records if record.state in selected]

    monkeypatch.setattr(resolve_module, "list_project_records", fake_list)

    import sase.linked_repos as linked_mod
    import sase.sdd as sdd_mod

    linked = linked or {}
    sdd = sdd or {}
    sdd_records = sdd_records or {}

    def fake_linked(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(kwargs))
        project_name = Path(kwargs["project_file"]).stem
        return linked.get(project_name, _FakeLinkedResolution(repos=()))

    def fake_sdd(primary_dir):  # type: ignore[no-untyped-def]
        calls.append({"sdd_primary_dir": primary_dir})
        project_name = Path(primary_dir).name
        return sdd.get(project_name)

    def fake_sdd_record(primary_dir):  # type: ignore[no-untyped-def]
        return sdd_records.get(Path(primary_dir).name)

    monkeypatch.setattr(linked_mod, "resolve_linked_repos_for_project", fake_linked)
    monkeypatch.setattr(sdd_mod, "materialized_sdd_clone", fake_sdd)
    monkeypatch.setattr(sdd_mod, "read_sdd_store_record", fake_sdd_record)
    return calls


def test_explicit_project_scope_resolves_only_that_constellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alpha = _global_record(
        tmp_path,
        "alpha",
        display_name="Alpha Display",
        aliases=["a"],
    )
    beta = _global_record(tmp_path, "beta")
    core = tmp_path / "repos" / "core"
    core.mkdir(parents=True)
    plans = tmp_path / "repos" / "plans"
    plans.mkdir(parents=True)
    alpha_sdd = tmp_path / "stores" / "alpha-sdd"
    alpha_sdd.mkdir(parents=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [alpha, beta],
        linked={
            "alpha": _FakeLinkedResolution(
                repos=(
                    _FakeLinked("sase-core", str(core)),
                    _FakeLinked("plans", str(plans), kind="sidecar"),
                )
            )
        },
        sdd={"alpha": alpha_sdd},
        sdd_records={"alpha": _FakeRecord(repo="alpha-sdd")},
    )

    resolved = resolve_log_repos(
        cwd="/unrelated",
        project_scope="a",
        include_sidecars=True,
    )

    assert [(repo.name, repo.kind) for repo in resolved.repos] == [
        ("Alpha Display", "primary"),
        ("sase-core", "linked"),
        ("alpha-sdd", "sidecar"),
        ("plans", "sidecar"),
    ]
    assert all("beta" not in repo.path for repo in resolved.repos)


def test_explicit_project_scope_reports_unknown_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [_global_record(tmp_path, "alpha")],
    )

    resolved = resolve_log_repos(cwd="/unrelated", project_scope="missing")

    assert resolved.repos == []
    assert resolved.warnings == ["project 'missing' was not found"]


def test_all_projects_uses_full_inventory_outside_a_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records = [
        _global_record(tmp_path, "gamma", state="sibling"),
        _global_record(tmp_path, "alpha", display_name="Alpha"),
        _global_record(tmp_path, "beta", state="disabled"),
    ]
    core = tmp_path / "repos" / "core"
    core.mkdir(parents=True)
    plans = tmp_path / "repos" / "plans"
    plans.mkdir(parents=True)
    sdd_dir = tmp_path / "stores" / "alpha-sdd"
    sdd_dir.mkdir(parents=True)
    calls = _configure_global_resolution(
        monkeypatch,
        tmp_path,
        records,
        linked={
            "alpha": _FakeLinkedResolution(
                repos=(
                    _FakeLinked("gamma", records[0].workspace_dir or ""),
                    _FakeLinked("sase-core", str(core)),
                    _FakeLinked("plans", str(plans), kind="sidecar"),
                )
            )
        },
        sdd={"alpha": sdd_dir},
        sdd_records={"alpha": _FakeRecord(repo="alpha-sdd")},
    )

    default = resolve_log_repos(cwd="/not/a/workspace", all_projects=True)

    assert [repo.kind for repo in default.repos] == [
        "primary",
        "primary",
        "linked",
        "linked",
    ]
    assert not any("sdd_primary_dir" in call for call in calls)

    calls.clear()
    resolved = resolve_log_repos(
        cwd="/not/a/workspace", all_projects=True, include_sidecars=True
    )

    assert [(repo.name, repo.kind) for repo in resolved.repos] == [
        ("Alpha", "primary"),
        ("beta", "primary"),
        ("gamma", "linked"),
        ("sase-core", "linked"),
        ("alpha-sdd", "sidecar"),
        ("plans", "sidecar"),
    ]
    assert calls[0] == {
        "root": tmp_path / "projects",
        "states": ("enabled", "disabled"),
        "include_home": False,
    }
    linked_calls = [call for call in calls[1:] if "materialize" in call]
    assert len(linked_calls) == 2
    assert all(call["materialize"] is False for call in linked_calls)
    sdd_calls = [call for call in calls[1:] if "sdd_primary_dir" in call]
    assert len(sdd_calls) == 2


def test_all_projects_skips_bad_records_and_deduplicates_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    healthy = _global_record(tmp_path, "healthy")
    broken = _global_record(
        tmp_path,
        "broken",
        warnings=["malformed metadata", "malformed metadata"],
        parse_warnings=["malformed metadata"],
    )
    Path(broken.project_file).unlink()
    missing = _global_record(tmp_path, "missing")
    Path(missing.workspace_dir or "").rmdir()
    _configure_global_resolution(monkeypatch, tmp_path, [broken, healthy, missing])

    resolved = resolve_log_repos(cwd="/anywhere", all_projects=True)

    assert [repo.name for repo in resolved.repos] == ["healthy"]
    assert resolved.warnings.count("broken: malformed metadata") == 1
    assert any(
        "broken: project file is unavailable" in warning
        for warning in resolved.warnings
    )
    assert any(
        "missing: primary workspace is unavailable" in warning
        for warning in resolved.warnings
    )


def test_all_projects_deduplicates_symlinks_and_promotes_registered_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _global_record(tmp_path, "root")
    other = _global_record(tmp_path, "other")
    core = _global_record(tmp_path, "core", display_name="sase-core")
    core_alias = tmp_path / "repos" / "core-alias"
    core_alias.parent.mkdir(parents=True)
    core_alias.symlink_to(Path(core.workspace_dir or ""), target_is_directory=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [root, other, core],
        linked={
            "root": _FakeLinkedResolution(
                repos=(_FakeLinked("core", str(core_alias), kind="sidecar"),),
                warnings=(
                    "Skipping linked repo 'sase-core': primary path does not exist: /old/core",
                ),
            ),
            "other": _FakeLinkedResolution(
                repos=(_FakeLinked("sase-core", str(core_alias)),),
                warnings=(
                    "Skipping linked repo 'sase-core': primary path does not exist: /other/core",
                ),
            ),
        },
    )

    resolved = resolve_log_repos(
        cwd="/anywhere",
        all_projects=True,
        include_sidecars=True,
        repo_filters=["core"],
    )

    assert [(repo.name, repo.kind, repo.path) for repo in resolved.repos] == [
        ("sase-core", "primary", str(Path(core.workspace_dir or "").resolve()))
    ]
    assert resolved.warnings == []


def test_all_projects_qualifies_colliding_labels_and_rejects_ambiguous_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alpha = _global_record(tmp_path, "alpha")
    beta = _global_record(tmp_path, "beta")
    alpha_shared = tmp_path / "repos" / "alpha-shared"
    beta_shared = tmp_path / "repos" / "beta-shared"
    alpha_shared.mkdir(parents=True)
    beta_shared.mkdir(parents=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [beta, alpha],
        linked={
            "alpha": _FakeLinkedResolution(
                repos=(_FakeLinked("shared", str(alpha_shared)),)
            ),
            "beta": _FakeLinkedResolution(
                repos=(_FakeLinked("shared", str(beta_shared)),)
            ),
        },
    )

    all_repos = resolve_log_repos(cwd="/anywhere", all_projects=True)
    ambiguous = resolve_log_repos(
        cwd="/anywhere", all_projects=True, repo_filters=["shared"]
    )
    selected = resolve_log_repos(
        cwd="/anywhere", all_projects=True, repo_filters=["beta/shared"]
    )

    assert [repo.name for repo in all_repos.repos] == [
        "alpha",
        "beta",
        "alpha/shared",
        "beta/shared",
    ]
    assert ambiguous.repos == []
    assert ambiguous.warnings == [
        "--repo 'shared' is ambiguous; use one of: alpha/shared, beta/shared"
    ]
    assert [repo.name for repo in selected.repos] == ["beta/shared"]


def test_all_projects_exclusion_removes_every_shared_alias_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alpha = _global_record(tmp_path, "alpha")
    beta = _global_record(tmp_path, "beta")
    alpha_shared = tmp_path / "repos" / "alpha-shared"
    beta_shared = tmp_path / "repos" / "beta-shared"
    alpha_shared.mkdir(parents=True)
    beta_shared.mkdir(parents=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [alpha, beta],
        linked={
            "alpha": _FakeLinkedResolution(
                repos=(_FakeLinked("shared", str(alpha_shared)),)
            ),
            "beta": _FakeLinkedResolution(
                repos=(_FakeLinked("shared", str(beta_shared)),)
            ),
        },
    )

    resolved = resolve_log_repos(
        cwd="/anywhere",
        all_projects=True,
        exclude_repo_filters=["SHARED"],
    )

    assert [repo.name for repo in resolved.repos] == ["alpha", "beta"]
    assert resolved.warnings == []


def test_all_projects_qualifies_colliding_sdd_labels_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alpha = _global_record(tmp_path, "alpha")
    beta = _global_record(tmp_path, "beta")
    alpha_sdd = tmp_path / "stores" / "alpha-sdd"
    beta_sdd = tmp_path / "stores" / "beta-sdd"
    alpha_sdd.mkdir(parents=True)
    beta_sdd.mkdir(parents=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [alpha, beta],
        sdd={
            "alpha": alpha_sdd,
            "beta": beta_sdd,
        },
    )

    resolved = resolve_log_repos(
        cwd="/anywhere", all_projects=True, include_sidecars=True
    )
    ambiguous = resolve_log_repos(
        cwd="/anywhere",
        all_projects=True,
        include_sidecars=True,
        repo_filters=["sdd"],
    )

    assert [repo.name for repo in resolved.repos] == [
        "alpha",
        "beta",
        "alpha/sdd",
        "beta/sdd",
    ]
    assert ambiguous.repos == []
    assert ambiguous.warnings == [
        "--repo 'sdd' is ambiguous; use one of: alpha/sdd, beta/sdd"
    ]


def test_all_projects_deduplicates_shared_sdd_checkout_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alpha = _global_record(tmp_path, "alpha")
    beta = _global_record(tmp_path, "beta")
    shared_sdd = tmp_path / "stores" / "shared-sdd"
    shared_sdd.mkdir(parents=True)
    _configure_global_resolution(
        monkeypatch,
        tmp_path,
        [alpha, beta],
        sdd={
            "alpha": shared_sdd,
            "beta": shared_sdd,
        },
    )

    resolved = resolve_log_repos(
        cwd="/anywhere", all_projects=True, include_sidecars=True
    )

    sdd_repos = [repo for repo in resolved.repos if repo.kind == "sidecar"]
    assert len(sdd_repos) == 1
    assert sdd_repos[0].path == str(shared_sdd.resolve())
    assert [owner.project for owner in sdd_repos[0].plan_workspaces] == [
        "alpha",
        "beta",
    ]
