"""Recovery-ref retention and reaping regression coverage."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._repository_recovery_git import already_locked
from sase.sdd._repository_recovery_reaper import _reap_sdd_recovery_snapshots
from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def test_recovery_reaper_drops_stale_reachable_recovery_ref(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    target = git(["rev-parse", "HEAD"], clone_dir).stdout.strip()
    recovery_ref = "refs/sase/recovery/20260101T000000Z-main-reachable"
    git(["update-ref", recovery_ref, target], clone_dir)

    result = _reap_sdd_recovery_snapshots(
        clone_dir,
        now=4102444800.0,
        retention_seconds=1.0,
        lock_factory=already_locked,
    )

    assert result.removed_refs == (recovery_ref,)
    assert result.retained_unreachable == ()
    assert (
        git(
            ["for-each-ref", "--format=%(refname)", "refs/sase/recovery"], clone_dir
        ).stdout.strip()
        == ""
    )


def test_recovery_reaper_keeps_stale_ref_with_unpushed_commit(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (clone_dir / "local.md").write_text("local\n", encoding="utf-8")
    commit_all(clone_dir, "local only")
    target = git(["rev-parse", "HEAD"], clone_dir).stdout.strip()
    recovery_ref = "refs/sase/recovery/20260101T000000Z-main-local"
    git(["update-ref", recovery_ref, target], clone_dir)

    result = _reap_sdd_recovery_snapshots(
        clone_dir,
        now=4102444800.0,
        retention_seconds=1.0,
        lock_factory=already_locked,
    )

    assert result.removed_refs == ()
    assert result.retained_unreachable == (recovery_ref,)
    assert git(["rev-parse", "--verify", recovery_ref], clone_dir).stdout.strip() == (
        target
    )


def test_recovery_reaper_drops_stale_recovery_stash_with_reachable_base(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    recovery_ref = "refs/sase/recovery/20260101T000000Z-main-stash"
    (clone_dir / "README.md").write_text("dirty\n", encoding="utf-8")
    git(["stash", "push", "--message", f"sase recovery {recovery_ref}"], clone_dir)
    stash_sha = git(["rev-parse", "refs/stash"], clone_dir).stdout.strip()
    git(["update-ref", recovery_ref, stash_sha], clone_dir)

    result = _reap_sdd_recovery_snapshots(
        clone_dir,
        now=4102444800.0,
        retention_seconds=1.0,
        lock_factory=already_locked,
    )

    assert result.removed_refs == (recovery_ref,)
    assert result.removed_stashes == ("stash@{0}",)
    assert git(["stash", "list"], clone_dir).stdout == ""
    assert (
        git(
            ["for-each-ref", "--format=%(refname)", "refs/sase/recovery"], clone_dir
        ).stdout.strip()
        == ""
    )


def test_recovery_reaper_keeps_recovery_stash_with_unpushed_base(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (clone_dir / "local.md").write_text("local\n", encoding="utf-8")
    commit_all(clone_dir, "local only")
    recovery_ref = "refs/sase/recovery/20260101T000000Z-main-local-stash"
    (clone_dir / "README.md").write_text("dirty\n", encoding="utf-8")
    git(["stash", "push", "--message", f"sase recovery {recovery_ref}"], clone_dir)
    stash_sha = git(["rev-parse", "refs/stash"], clone_dir).stdout.strip()
    git(["update-ref", recovery_ref, stash_sha], clone_dir)

    result = _reap_sdd_recovery_snapshots(
        clone_dir,
        now=4102444800.0,
        retention_seconds=1.0,
        lock_factory=already_locked,
    )

    assert result.removed_refs == ()
    assert result.removed_stashes == ()
    assert set(result.retained_unreachable) == {recovery_ref, "stash@{0}"}
    assert git(["rev-parse", "--verify", recovery_ref], clone_dir).stdout.strip() == (
        stash_sha
    )
    assert f"sase recovery {recovery_ref}" in git(["stash", "list"], clone_dir).stdout
