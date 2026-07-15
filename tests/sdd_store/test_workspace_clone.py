from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_types import SddMaterializationError
from sase.sdd.store import (
    _write_sdd_store_record,
    ensure_sdd_kind_clone,
    ensure_workspace_sdd_clone,
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
    _write_sdd_store_record(
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
    _write_sdd_store_record(
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
    _write_sdd_store_record(
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


def test_moved_sidecar_clone_with_matching_remote_is_accepted(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    old_clone = tmp_path / "repo--plans"
    moved_clone = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, old_clone)
    old_clone.rename(moved_clone)
    (moved_clone / "local-untracked.md").write_text("keep\n", encoding="utf-8")

    ensure_sidecar_sdd_clone(moved_clone, str(remote), strict=True)

    assert not old_clone.exists()
    assert (moved_clone / "local-untracked.md").read_text(encoding="utf-8") == "keep\n"
    assert git(["remote", "get-url", "origin"], moved_clone).stdout.strip() == str(
        remote
    )


def test_retained_https_sidecar_clone_is_rewritten_without_losing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    clone_dir.mkdir(parents=True)
    git(["init", "-q"], clone_dir)
    git(
        [
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widget--plans.git",
        ],
        clone_dir,
    )
    local = clone_dir / "local-untracked.md"
    local.write_text("preserve me\n", encoding="utf-8")
    monkeypatch.setattr("sase.sdd._store_link._pull_sdd_clone", lambda _path: True)
    monkeypatch.setattr(
        "sase.sdd._store_link._replace_workspace_sdd_clone",
        lambda *_args: pytest.fail("matching HTTPS clone was replaced"),
    )

    ensure_sidecar_sdd_clone(
        clone_dir,
        "git@github.com:acme/widget--plans.git",
        strict=True,
    )

    assert local.read_text(encoding="utf-8") == "preserve me\n"
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == (
        "git@github.com:acme/widget--plans.git"
    )


def test_sidecar_clone_uses_authoritative_remote_not_durable_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    durable_primary = tmp_path / "primary" / "sase" / "repos" / "plans"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    readme = seed / "README.md"
    readme.write_text("initial\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, durable_primary)

    (durable_primary / "README.md").write_text(
        "durable primary only\n", encoding="utf-8"
    )
    commit_all(durable_primary, "Unpushed durable-primary change")
    primary_only_head = git(["rev-parse", "HEAD"], durable_primary).stdout.strip()

    readme.write_text("authoritative remote\n", encoding="utf-8")
    commit_all(seed, "Advance authoritative remote incompatibly")
    git(["push"], seed)
    remote_head = git(["rev-parse", "HEAD"], seed).stdout.strip()
    clone_commands: list[list[str]] = []
    clone_terminal_prompts: list[str | None] = []
    from sase.sdd import _commit

    original_run_sdd_git = _commit.run_sdd_git

    def record_git(args: list[str], **kwargs):
        if args and args[0] == "clone":
            clone_commands.append(args)
            clone_terminal_prompts.append(kwargs["env"].get("GIT_TERMINAL_PROMPT"))
        return original_run_sdd_git(args, **kwargs)

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", record_git)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("durable primary seeded fresh sidecar"),
    )

    ensure_sidecar_sdd_clone(clone_dir, str(remote), strict=True)

    assert clone_commands == [["clone", str(remote), str(clone_dir)]]
    assert clone_terminal_prompts == ["0"]
    assert git(["rev-parse", "HEAD"], clone_dir).stdout.strip() == remote_head
    assert git(["rev-parse", "@{upstream}"], clone_dir).stdout.strip() == remote_head
    assert (clone_dir / "README.md").read_text(encoding="utf-8") == (
        "authoritative remote\n"
    )
    assert git(["status", "--porcelain"], clone_dir).stdout == ""
    assert (
        primary_only_head
        not in git(["rev-list", "--all"], clone_dir).stdout.splitlines()
    )
    assert not (clone_dir / ".git" / "rebase-merge").exists()
    assert not (clone_dir / ".git" / "rebase-apply").exists()
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(remote)


def test_sidecar_clone_failure_removes_partial_target_and_surfaces_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = "git@example.test:private/plans.git"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"

    def failed_clone(*_args, **_kwargs):
        clone_dir.mkdir(parents=True)
        (clone_dir / "partial").write_text("incomplete", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=128,
            stdout="",
            stderr="authentication failed for plans remote",
        )

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", failed_clone)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("clone failure used a local fallback"),
    )

    with pytest.raises(
        SddMaterializationError, match="authentication failed for plans remote"
    ):
        ensure_sidecar_sdd_clone(clone_dir, remote, strict=True)

    assert not clone_dir.exists()


@pytest.mark.parametrize("strict", [False, True])
def test_http_sidecar_remote_is_rejected_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    strict: bool,
) -> None:
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    git_calls: list[list[str]] = []

    def record_git(args: list[str], **_kwargs):
        git_calls.append(args)
        raise AssertionError("Git must not run for HTTP(S) sidecar remotes")

    monkeypatch.setattr("sase.sdd._commit.run_sdd_git", record_git)

    if strict:
        with pytest.raises(
            SddMaterializationError,
            match=r"refusing HTTP\(S\).*Git was not invoked",
        ):
            ensure_sidecar_sdd_clone(
                clone_dir,
                "https://example.test/acme/widget--plans.git",
                strict=True,
            )
    else:
        ensure_sidecar_sdd_clone(
            clone_dir,
            "http://example.test/acme/widget--plans.git",
        )
        assert "Git was not invoked" in caplog.text

    assert git_calls == []
    assert not clone_dir.exists()


def test_ensure_workspace_sdd_clone_in_tree_noop(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    (tmp_path / "repo").mkdir()
    workspace.mkdir()
    provider_patch("bare_git")

    ensure_workspace_sdd_clone(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_clone_local_noop(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    provider_patch(None)

    ensure_workspace_sdd_clone(workspace, 1)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_clone_preserves_non_store_real_dir(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace_sdd = workspace / ".sase" / "sdd"
    workspace_sdd.mkdir(parents=True)
    (workspace_sdd / "keep.md").write_text("# Keep\n", encoding="utf-8")
    provider_patch("github")

    ensure_workspace_sdd_clone(workspace, 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "keep.md").read_text(encoding="utf-8") == "# Keep\n"


def test_ensure_workspace_sdd_clone_pulls_stale_clean_clone(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
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
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_clone_is_idempotent(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
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
    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert not list((tmp_path / "repo_2" / ".sase").glob("sdd.stale-backup*"))


def test_ensure_workspace_sdd_clone_store_clone_with_commits_ahead_is_rebased(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_work.md").write_text("wip\n", encoding="utf-8")
    commit_all(workspace_sdd, "Local work")
    _write_sdd_store_record(
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

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "local_work.md").read_text(encoding="utf-8") == "wip\n"
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_clone_store_clone_with_dirty_tree_is_preserved(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_notes.md").write_text("draft\n", encoding="utf-8")
    _write_sdd_store_record(
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

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "local_notes.md").read_text(encoding="utf-8") == "draft\n"
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_clone_non_matching_remote_clone_is_preserved(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    other = tmp_path / "other.git"
    init_bare_repo(other)
    clone(other, workspace_sdd)
    (workspace_sdd / "unrelated.md").write_text("unrelated\n", encoding="utf-8")
    _write_sdd_store_record(
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

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "unrelated.md").read_text(encoding="utf-8") == "unrelated\n"


def test_ensure_workspace_sdd_clone_stale_clone_makes_relative_prompt_ref_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    from sase.file_references import process_file_references

    sidecar, _primary_sdd, _workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
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
    monkeypatch.chdir(tmp_path / "repo_2")

    prompt = "@.sase/sdd/plans/202607/feature.md\nImplement it now."
    assert process_file_references(prompt) == prompt


def test_ensure_workspace_sdd_clone_replaces_stale_symlink(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    stale_target = tmp_path / "old-sdd"
    stale_target.mkdir()
    workspace_sdd.parent.mkdir(parents=True, exist_ok=True)
    workspace_sdd.symlink_to(stale_target, target_is_directory=True)
    _write_sdd_store_record(
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
    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").exists()


def test_ensure_workspace_sdd_clone_remote_failure_uses_primary_fallback(
    tmp_path: Path,
    provider_patch,
) -> None:
    _sidecar, primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(tmp_path / "missing.git"),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    assert git(["remote", "get-url", "origin"], workspace_sdd).stdout.strip() == str(
        tmp_path / "missing.git"
    )
    assert (primary_sdd / "plans" / "202607" / "feature.md").exists()


def test_ensure_workspace_sdd_clone_missing_store_is_best_effort(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    provider_patch("github")

    ensure_workspace_sdd_clone(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()
