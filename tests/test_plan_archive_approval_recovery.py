"""Approval-time archive recovers the leased SDD store, not the checkout."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

import sase.workspace_provider.reset_replay as reset_replay
from sase._plan_archive_approval import (
    archive_approved_plan,
    report_plan_archive_failure,
)
from sase.bead._sync_publication import PushOutcome, head_is_published
from sase.bead.sync import push_bead_work_launch
from sase.sdd.plan_archive import archive_plan_file
from sase.sdd.store import SddStore
from sase.workspace_provider.reset_replay import ResetReplayError
from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo
from tests.workspace_lease_helpers import patched_operational_lease

_MONTH = "202608"
_ACCEPT_PLAN = """---
tier: tale
title: Accept-path plan
goal: Divergent content from the archive rewrite
size: small
create_time: 2026-08-16 09:20:00
status: wip
---
# Plan

Accept-path version of the same file.
"""


def _git(args: list[str], cwd: Path) -> str:
    return git(args, cwd).stdout.strip()


def _head(repo: Path) -> str:
    return _git(["rev-parse", "HEAD"], repo)


def _reset_refs(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/sase/reset_replay"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _seed_plans_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "plans.git"
    init_bare_repo(origin)
    seed = tmp_path / "seed-plans"
    clone(origin, seed)
    (seed / "README.md").write_text("plans\n", encoding="utf-8")
    commit_all(seed, "init plans")
    git(["push", "-u", "origin", "main"], seed)
    return origin


def _push_origin_file(origin: Path, tmp_path: Path, relpath: str, content: str) -> None:
    writer = tmp_path / f"origin-writer-{relpath.replace('/', '_')}"
    clone(origin, writer)
    path = writer / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    commit_all(writer, f"Add SDD files for {Path(relpath).stem}")
    git(["push"], writer)


def _write_local_commit(repo: Path, relpath: str, content: str, message: str) -> str:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    commit_all(repo, message)
    return _head(repo)


@contextmanager
def _archive_harness(
    tmp_path: Path,
    *,
    origin: Path,
    checkout: Path,
    plans: Path,
) -> Iterator[SddStore]:
    project_file = tmp_path / "projects" / "demo" / "demo.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("", encoding="utf-8")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=str(origin),
        sidecar_role="plans",
    )
    plan = tmp_path / "approved_plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    with (
        patched_operational_lease(checkout, primary_checkout=tmp_path / "primary"),
        patch("sase.sdd.store.materialize_sdd_store", return_value=store),
        patch("sase.sdd.files.get_yyyymm", return_value=_MONTH),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda content: content,
        ),
    ):
        yield store


def _archive(
    tmp_path: Path,
    src_name: str = "approved_plan.md",
) -> str:
    return archive_approved_plan(
        {"agent_project_file": str(tmp_path / "projects" / "demo" / "demo.sase")},
        tmp_path / src_name,
        tier="tale",
    )


def test_archive_resets_store_repo_not_workspace_on_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _seed_plans_origin(tmp_path)
    checkout = tmp_path / "proj_10"
    checkout.mkdir()
    (checkout / "workspace-marker").write_text("checkout local\n", encoding="utf-8")
    plans = checkout / "sase" / "repos" / "plans"
    clone(origin, plans)
    _push_origin_file(origin, tmp_path, f"{_MONTH}/approved_plan.md", _ACCEPT_PLAN)
    assert head_is_published(plans)
    checkout_marker = (checkout / "workspace-marker").read_text(encoding="utf-8")
    reset_roots: list[Path] = []
    original = reset_replay._reset_leased_checkout

    def _spy(repo_root: Path, **kwargs: object) -> str | None:
        reset_roots.append(Path(repo_root).resolve())
        return original(repo_root, **kwargs)

    monkeypatch.setattr(reset_replay, "_reset_leased_checkout", _spy)
    archive_calls = {"n": 0}

    def _count_archive(*args: object, **kwargs: object) -> object:
        archive_calls["n"] += 1
        return archive_plan_file(*args, **kwargs)

    monkeypatch.setattr("sase.sdd.plan_archive.archive_plan_file", _count_archive)

    with _archive_harness(tmp_path, origin=origin, checkout=checkout, plans=plans):
        archived = _archive(tmp_path)

    assert Path(archived) == plans / _MONTH / "approved_plan.md"
    assert archive_calls["n"] == 2
    assert reset_roots == [plans.resolve()]
    assert (checkout / "workspace-marker").read_text(
        encoding="utf-8"
    ) == checkout_marker
    git(["fetch", "origin"], plans)
    assert head_is_published(plans)
    assert _head(plans) == _git(["rev-parse", "origin/main"], plans)


def test_unpublished_poison_commit_does_not_fail_unrelated_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _seed_plans_origin(tmp_path)
    checkout = tmp_path / "proj_10"
    checkout.mkdir()
    plans = checkout / "sase" / "repos" / "plans"
    clone(origin, plans)
    _write_local_commit(
        plans,
        f"{_MONTH}/poison.md",
        "local unpublished poison\n",
        "Archive approved plan poison",
    )
    _push_origin_file(
        origin,
        tmp_path,
        f"{_MONTH}/poison.md",
        "upstream poison from the other writer\n",
    )
    assert not head_is_published(plans)
    archive_calls = {"n": 0}

    def _count_archive(*args: object, **kwargs: object) -> object:
        archive_calls["n"] += 1
        return archive_plan_file(*args, **kwargs)

    monkeypatch.setattr("sase.sdd.plan_archive.archive_plan_file", _count_archive)

    with _archive_harness(tmp_path, origin=origin, checkout=checkout, plans=plans):
        archived = _archive(tmp_path)

    assert Path(archived) == plans / _MONTH / "approved_plan.md"
    assert archive_calls["n"] == 1
    assert (plans / _MONTH / "poison.md").read_text(encoding="utf-8") == (
        "upstream poison from the other writer\n"
    )
    assert head_is_published(plans)
    assert (plans / _MONTH / "approved_plan.md").is_file()


def test_exhausted_archive_budget_resets_store_and_names_recovery_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _seed_plans_origin(tmp_path)
    checkout = tmp_path / "proj_10"
    checkout.mkdir()
    plans = checkout / "sase" / "repos" / "plans"
    clone(origin, plans)
    published = _head(plans)

    def _fail_push(_repo: Path, **_kwargs: object) -> PushOutcome:
        return PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="non-fast-forward rejected",
        )

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", _fail_push)

    with _archive_harness(tmp_path, origin=origin, checkout=checkout, plans=plans):
        with pytest.raises(
            ResetReplayError, match="abandoned HEAD preserved at"
        ) as exc:
            _archive(tmp_path)

    error = exc.value
    assert error.recovery_ref is not None
    assert error.recovery_ref in str(error)
    assert _head(plans) == published
    assert _git(["rev-parse", error.recovery_ref], plans) != published
    assert (
        subprocess.run(
            ["git", "cat-file", "-e", error.recovery_ref],
            cwd=plans,
            check=False,
        ).returncode
        == 0
    )

    with patch("sase.notifications.notify_workflow_complete") as notify:
        report_plan_archive_failure(
            tmp_path / "approved_plan.md",
            {"agent_cl_name": "demo"},
            error,
        )
    notes = notify.call_args.args[3]
    assert any(error.recovery_ref in note for note in notes)


def test_skipped_locked_push_defers_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _seed_plans_origin(tmp_path)
    checkout = tmp_path / "proj_10"
    checkout.mkdir()
    plans = checkout / "sase" / "repos" / "plans"
    clone(origin, plans)
    real_push = push_bead_work_launch
    calls = {"n": 0}

    def _push(repo: Path, **kwargs: object) -> PushOutcome:
        calls["n"] += 1
        if calls["n"] == 1:
            return PushOutcome(
                pushed=False,
                skipped_no_remote=False,
                error=None,
                skipped_locked=True,
            )
        return real_push(repo, **kwargs)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", _push)

    with _archive_harness(tmp_path, origin=origin, checkout=checkout, plans=plans):
        archived = _archive(tmp_path)

    assert Path(archived) == plans / _MONTH / "approved_plan.md"
    assert calls["n"] >= 2
    assert _reset_refs(plans) == []
    assert head_is_published(plans)
