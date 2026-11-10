"""Real local repositories reproduce the enclosing-checkout corruption incident."""

from pathlib import Path
import json
import subprocess

import pytest

from sase._git_worktree import is_worktree_root, require_worktree_root
from sase._linked_repo_workspaces import (
    materialize_linked_repo_workspace,
    refresh_clean_linked_checkout,
)
from sase.workspace_provider._utils_origin import heal_clone_origin_if_needed
from sase.workspace_provider.push_guard import require_push_identity
from sase.vcs_provider.plugins.bare_git import BareGitPlugin
from tests.sdd_store._helpers import clone, commit_all, init_bare_repo


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


def repo(tmp_path: Path, name: str) -> tuple[Path, Path]:
    remote = tmp_path / f"{name}.git"
    primary = tmp_path / name
    init_bare_repo(remote)
    clone(remote, primary)
    (primary / "README").write_text(name)
    commit_all(primary, "seed")
    git(primary, "push", "origin", "main")
    return primary, remote


def host_state(host: Path) -> tuple[str, str, bytes]:
    return (
        git(host, "remote", "get-url", "origin"),
        git(host, "show-ref"),
        (host / ".git/info/exclude").read_bytes(),
    )


@pytest.mark.parametrize("sidecar", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_materialization_never_mutates_enclosing_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool, sidecar: bool
) -> None:
    host, _ = repo(tmp_path, "host")
    primary, remote = repo(tmp_path, "source")
    target = host / "sase/repos" / ("research" if sidecar else "linked/source")
    target.mkdir(parents=True)
    if not empty:
        (target / "keep.txt").write_text("irreplaceable")
    monkeypatch.setattr("sase.sdd.store.ensure_workspace_sdd_clone", lambda *a: None)
    before = host_state(host)

    def materialize() -> str:
        return materialize_linked_repo_workspace(
            primary_dir=str(primary),
            workspace_dir=str(target),
            workspace_num=10,
            expected_remote_url=str(remote) if sidecar else None,
        )

    if empty:
        assert materialize() == str(target)
        assert is_worktree_root(target)
        assert git(target, "remote", "get-url", "origin") == str(remote)
    else:
        with pytest.raises(RuntimeError, match="not its own Git worktree") as exc:
            materialize()
        assert str(host) in str(exc.value)
        assert "manually" in str(exc.value)
        assert (target / "keep.txt").read_text() == "irreplaceable"
    assert host_state(host) == before


def test_mutation_helpers_reject_nested_non_checkout(tmp_path: Path) -> None:
    host, _ = repo(tmp_path, "host")
    primary, _ = repo(tmp_path, "source")
    target = host / "child"
    target.mkdir()
    before = host_state(host)
    assert not is_worktree_root(target)
    assert refresh_clean_linked_checkout(str(target)) is None
    with pytest.raises(RuntimeError, match="not its own Git worktree"):
        heal_clone_origin_if_needed(
            primary_workspace_dir=str(primary), target_checkout_dir=str(target)
        )
    assert host_state(host) == before


def test_worktree_gitfile_and_symlink_are_accepted(tmp_path: Path) -> None:
    primary, _ = repo(tmp_path, "source")
    worktree = tmp_path / "worktree"
    git(primary, "worktree", "add", "-b", "topic", str(worktree))
    alias = tmp_path / "alias"
    alias.symlink_to(worktree, target_is_directory=True)
    require_worktree_root(worktree)
    require_worktree_root(alias)


@pytest.mark.parametrize("pushurl", [False, True])
def test_push_refuses_rewritten_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pushurl: bool
) -> None:
    primary, remote = repo(tmp_path, "source")
    _, wrong = repo(tmp_path, "wrong")
    target = tmp_path / "clone"
    clone(remote, target)
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"workspace_dir": str(target), "primary_dir": str(primary)}]),
    )
    require_push_identity(str(target))
    git(
        target,
        "remote",
        "set-url",
        *(["--push"] if pushurl else []),
        "origin",
        str(wrong),
    )
    before = git(wrong, "show-ref")
    ok, error = BareGitPlugin().vcs_mail("main", str(target))
    assert not ok
    assert error and "Refusing Git push" in error
    assert str(remote) in error and str(wrong) in error
    assert git(wrong, "show-ref") == before


def test_push_refuses_enclosing_repository(tmp_path: Path) -> None:
    host, remote = repo(tmp_path, "host")
    target = host / "child"
    target.mkdir()
    before = git(remote, "show-ref")
    ok, error = BareGitPlugin().vcs_mail("main", str(target))
    assert not ok
    assert error and "not its own Git worktree" in error
    assert git(remote, "show-ref") == before


@pytest.mark.parametrize(
    "actual",
    [
        "https://github.com/acme/source",
        "ssh://git@github.com/acme/source.git",
        "git@github.com:acme/source.git",
    ],
)
def test_push_accepts_equivalent_remote_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, actual: str
) -> None:
    primary, _ = repo(tmp_path, "source")
    git(primary, "remote", "set-url", "origin", actual)
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps(
            [
                {
                    "workspace_dir": str(primary),
                    "remote_url": "git@github.com:acme/source.git",
                }
            ]
        ),
    )
    require_push_identity(str(primary))


def test_clone_failure_cannot_reuse_enclosing_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.workspace_provider.utils import ensure_git_clone_at

    host, _ = repo(tmp_path, "host")
    primary, _ = repo(tmp_path, "source")
    target = host / "child"
    before = host_state(host)
    real_run = subprocess.run

    def fail_clone(cmd: list[str], *args: object, **kwargs: object):
        if cmd[:2] == ["git", "clone"]:
            target.mkdir()
            (target / "partial").write_text("preserve")
            raise subprocess.CalledProcessError(1, cmd, stderr="clone interrupted")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_clone)
    with pytest.raises(RuntimeError, match="not its own Git worktree"):
        ensure_git_clone_at(str(primary), 2, str(target))
    assert host_state(host) == before
    assert (target / "partial").read_text() == "preserve"


def test_workspace_marker_checks_primary_origin(tmp_path: Path) -> None:
    primary, remote = repo(tmp_path, "source")
    _, wrong = repo(tmp_path, "wrong")
    target = tmp_path / "clone"
    clone(remote, target)
    (target / ".sase").mkdir()
    (target / ".sase/checkout.json").write_text(
        json.dumps(
            {
                "primary_workspace_dir": str(primary),
                "workspace_num": 10,
            }
        )
    )
    git(target, "remote", "set-url", "origin", str(wrong))
    with pytest.raises(RuntimeError, match="Refusing Git push"):
        require_push_identity(str(target))


def test_nested_checkout_does_not_inherit_host_origin_marker(tmp_path: Path) -> None:
    from sase.workspace_provider._utils_origin import reconcile_managed_checkout_origin

    host, _ = repo(tmp_path, "host")
    primary, remote = repo(tmp_path, "source")
    (host / ".sase").mkdir()
    (host / ".sase/checkout.json").write_text(
        json.dumps(
            {
                "primary_workspace_dir": str(host),
                "workspace_num": 10,
            }
        )
    )
    target = host / "child"
    clone(remote, target)
    assert not reconcile_managed_checkout_origin(str(target))
    assert git(target, "remote", "get-url", "origin") == str(remote)


@pytest.mark.parametrize("kind", ["primary", "linked", "sidecar", "external"])
def test_push_uses_inventory_identity_without_agent_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord

    primary, remote = repo(tmp_path, "source")
    _, wrong = repo(tmp_path, "wrong")
    target = tmp_path / "clone"
    clone(remote, target)
    source = RepoRecord(
        name="source",
        kind="primary",
        project="source",
        project_key="source",
        path=str(primary),
        exists=True,
        auto_clone=False,
        description=None,
        source="project",
        env_name=None,
    )
    from dataclasses import replace

    candidate = replace(
        source,
        kind=kind,
        path=str(target) if kind == "external" else str(primary),
        remote_url=str(remote) if kind == "sidecar" else None,
        clones=(RepoCloneRecord(workspace_num=10, path=str(target), exists=True),),
    )
    inventory = RepoInventory(records=(candidate, source))
    monkeypatch.setattr(
        "sase.repo_inventory.collect_repo_inventory", lambda **kw: inventory
    )
    require_push_identity(str(target))
    git(target, "remote", "set-url", "origin", str(wrong))
    with pytest.raises(RuntimeError, match="Refusing Git push") as exc:
        require_push_identity(str(target))
    assert str(remote) in str(exc.value) and str(wrong) in str(exc.value)


def test_submit_and_retry_do_not_push_or_fetch_after_identity_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.workspace_provider.plugins.bare_git_submit import _run_git

    primary, remote = repo(tmp_path, "source")
    _, wrong = repo(tmp_path, "wrong")
    target = tmp_path / "clone"
    clone(remote, target)
    monkeypatch.setenv(
        "SASE_LINKED_REPOS_JSON",
        json.dumps([{"workspace_dir": str(target), "primary_dir": str(primary)}]),
    )
    git(target, "remote", "set-url", "origin", str(wrong))
    before = git(wrong, "show-ref")
    result = _run_git(["push", "origin", "main"], cwd=str(target))
    assert result.returncode == 1 and "Refusing Git push" in result.stderr
    ok, error = BareGitPlugin()._push_with_retry(str(target))
    assert not ok and error and "Refusing Git push" in error
    assert not (target / ".git/FETCH_HEAD").exists()
    assert git(wrong, "show-ref") == before


def test_corrupt_bare_sidecar_never_rewrites_host_origin(tmp_path: Path) -> None:
    from sase.sdd._sidecar_bare import _set_public_origin, is_bare_sidecar_clone
    from sase.sdd._store_git import set_sdd_origin
    from sase.sdd._store_types import SddMaterializationError

    host, _ = repo(tmp_path, "host")
    target = host / "child"
    target.mkdir()
    (target / "HEAD").write_text("broken\n")
    (target / "objects").mkdir()
    before = host_state(host)
    assert not is_bare_sidecar_clone(target)
    with pytest.raises(SddMaterializationError, match="Not a bare sidecar clone"):
        _set_public_origin(target, "git@github.com:example/wrong.git")
    with pytest.raises(RuntimeError, match="not its own Git worktree"):
        set_sdd_origin(target, str(tmp_path / "wrong.git"))
    assert host_state(host) == before
