from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.sdd.store import (
    SddMaterializationError,
    ensure_sdd_kind_clone,
    ensure_workspace_sdd_clone,
    write_sdd_store_record,
)
from tests.sdd_store._helpers import (
    build_separate_repo_clones,
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def test_ensure_workspace_sdd_clone_managed_separate_repo(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / ".git").is_dir()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    exclude_lines = (
        (workspace_sdd / ".git" / "info" / "exclude")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert exclude_lines.count(".sase/") == 1
    assert exclude_lines.count("/sase/repos/") == 1


def test_ensure_workspace_sdd_clone_syncs_plans_sidecar_only(
    tmp_path: Path,
    provider_patch,
) -> None:
    plans_remote = tmp_path / "plans.git"
    research_remote = tmp_path / "research.git"
    seed = tmp_path / "seed"
    init_bare_repo(plans_remote)
    init_bare_repo(research_remote)
    clone(plans_remote, seed)
    plan = seed / "202607" / "feature.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    commit_all(seed, "Add plan")
    git(["push", "-u", "origin", "main"], seed)
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": str(plans_remote),
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": str(research_remote),
                },
            },
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(workspace, 2, strict=True)

    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    assert (plans / "202607" / "feature.md").read_text(encoding="utf-8") == "# Plan\n"
    assert git(["remote", "get-url", "origin"], plans).stdout.strip() == str(
        plans_remote
    )
    plans_exclude_lines = (
        (plans / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    )
    assert plans_exclude_lines.count(".sase/") == 1
    assert plans_exclude_lines.count("/sase/repos/") == 1
    assert not research.exists()

    assert ensure_sdd_kind_clone(workspace, 2, "research", strict=True) == research
    assert (research / ".git").is_dir()
    research_exclude_lines = (
        (research / ".git" / "info" / "exclude")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert research_exclude_lines.count(".sase/") == 1
    assert research_exclude_lines.count("/sase/repos/") == 1


def test_fresh_workspace_normalizes_legacy_https_record_before_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    legacy_plans_remote = "https://github.com/acme/widget--plans.git"
    canonical_plans_remote = "git@github.com:acme/widget--plans.git"
    raw_record = {
        "schema_version": 2,
        "storage": "sidecar_repos",
        "provider": "github",
        "host": "github.com",
        "sidecars": {
            "plans": {
                "repo": "acme/widget--plans",
                "remote_url": legacy_plans_remote,
            },
            "research": {
                "repo": "acme/widget--research",
                "remote_url": "https://github.com/acme/widget--research.git",
            },
        },
    }
    record_path.write_text(json.dumps(raw_record), encoding="utf-8")
    provider_patch(None)
    clone_commands: list[list[str]] = []
    clone_terminal_prompts: list[str | None] = []
    from sase.sdd import _commit

    original_run_sdd_git = _commit.run_sdd_git

    def fake_clone(args: list[str], **kwargs):
        if args and args[0] == "clone":
            clone_commands.append(args)
            clone_terminal_prompts.append(kwargs["env"].get("GIT_TERMINAL_PROMPT"))
            target = Path(args[2])
            target.mkdir(parents=True)
            git(["init", "-q"], target)
            git(["remote", "add", "origin", args[1]], target)
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="", stderr=""
            )
        return original_run_sdd_git(args, **kwargs)

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", fake_clone)

    ensure_workspace_sdd_clone(workspace, 2, strict=True)

    plans = workspace / "sase" / "repos" / "plans"
    assert clone_commands == [["clone", canonical_plans_remote, str(plans)]]
    assert clone_terminal_prompts == ["0"]
    assert git(["remote", "get-url", "origin"], plans).stdout.strip() == (
        canonical_plans_remote
    )
    assert legacy_plans_remote not in " ".join(clone_commands[0])
    assert json.loads(record_path.read_text(encoding="utf-8")) == raw_record


def test_nested_repo_inherits_owner_sdd_record_without_nested_sidecar(
    tmp_path: Path,
    provider_patch,
) -> None:
    plans_remote = tmp_path / "plans.git"
    research_remote = tmp_path / "research.git"
    seed = tmp_path / "seed"
    init_bare_repo(plans_remote)
    init_bare_repo(research_remote)
    clone(plans_remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)

    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_10"
    nested = workspace / "sase" / "repos" / "linked" / "other"
    primary.mkdir()
    nested.mkdir(parents=True)
    marker_dir = workspace / ".sase"
    marker_dir.mkdir()
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "project_name": "repo",
                "project_key": "repo",
                "workspace_num": 10,
                "primary_workspace_dir": str(primary),
                "registry_path": str(tmp_path / "registry.json"),
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": str(plans_remote),
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": str(research_remote),
                },
            },
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(nested, 10, strict=True)

    assert (workspace / "sase" / "repos" / "plans" / "README.md").is_file()
    assert not (nested / "sase").exists()


def test_strict_clone_failure_with_no_record_names_repo_init_remedy(
    tmp_path: Path,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    (primary / ".git").mkdir()
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    provider_patch("github")

    with pytest.raises(SddMaterializationError) as excinfo:
        ensure_workspace_sdd_clone(workspace, 2, strict=True)

    message = str(excinfo.value)
    assert str(primary) in message
    assert "sase repo init" in message
    assert "is_sase_managed" in message


def test_strict_clone_failure_with_materialized_record_keeps_original_message(
    tmp_path: Path,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(tmp_path / "missing.git"),
            "discovery": "found",
        },
    )
    provider_patch(None)

    with pytest.raises(SddMaterializationError) as excinfo:
        ensure_workspace_sdd_clone(workspace, 2, strict=True)

    workspace_sdd = workspace / ".sase" / "sdd"
    assert (
        str(excinfo.value)
        == f"could not create workspace SDD sidecar clone at {workspace_sdd}"
    )
