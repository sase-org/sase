"""Tests for ``sase artifact link add`` / ``rm``.

Split from ``test_artifact_cli_link``; shared helpers live in
``_artifact_cli_link_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli.link_ops import (
    add_artifact_link,
    handle_link_add,
    handle_link_list,
    handle_link_rm,
    remove_artifact_link,
)
from sase.bead._sync_publication import PushOutcome
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main._artifact_cli_link_helpers import (
    make_store,
    patch_link_ops_store,
)


def _store_with_remotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kinds: tuple[str, ...] = ("plan",),
) -> ArtifactLinkStore:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    roots: dict[str, Path] = {}
    for kind in kinds:
        remote = tmp_path / "remotes" / f"{kind}.git"
        repo = tmp_path / kind
        remote.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", "-q", "-b", "main", str(remote)],
            check=True,
        )
        subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True)
        subprocess.run(
            ["git", "config", "user.name", "SASE Test"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "sase-test@example.invalid"],
            cwd=repo,
            check=True,
        )
        document = repo / "202608" / "a.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(f"# {kind}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True)
        roots[kind] = repo
    return ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots=roots,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def test_add_list_rm_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    add_args = argparse.Namespace(
        source_ref="@plan:202608/a.md",
        relation="implements",
        target_ref="plan:202608/b.md",
        why="extends the ref contract this epic landed",
    )
    assert handle_link_add(add_args) == 0
    first = capsys.readouterr().out
    assert "added" in first
    assert handle_link_add(add_args) == 0
    second = capsys.readouterr().out
    assert "unchanged" in second
    assert (
        handle_link_list(
            argparse.Namespace(
                reference="plan:202608/a.md",
                direction="both",
                json=True,
                limit=50,
                origin=None,
                relation=None,
            )
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["relation"] == "implements"
    assert (
        handle_link_rm(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                target_ref="plan:202608/b.md",
                relation=None,
            )
        )
        == 0
    )
    assert "removed implements" in capsys.readouterr().out
    assert store.load_artifact_rows("plan:202608/a.md") == ()


def test_unchanged_add_retries_unpublished_partial_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store_with_remotes(tmp_path, monkeypatch, kinds=("plan", "research"))
    patch_link_ops_store(monkeypatch, store)
    plan = store.sidecar_roots["plan"]
    research = store.sidecar_roots["research"]
    from sase.bead.sync import push_bead_work_launch

    def fail_research_push(root: Path, **kwargs: object) -> PushOutcome:
        if Path(root).resolve() == research.resolve():
            return PushOutcome(
                pushed=False,
                skipped_no_remote=False,
                error="simulated research publication failure",
            )
        return push_bead_work_launch(root, **kwargs)

    args = {
        "source_ref": "plan:202608/a.md",
        "relation": "related",
        "target_ref": "research:202608/a.md",
        "why": "shares recovery evidence",
    }
    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", fail_research_push)
        with pytest.raises(RuntimeError, match="NOT published"):
            add_artifact_link(**args)

    result = add_artifact_link(**args)

    assert result["kind"] == "unchanged"
    assert _git(plan, "rev-parse", "HEAD") == _git(plan, "rev-parse", "origin/main")
    assert _git(research, "rev-parse", "HEAD") == _git(
        research, "rev-parse", "origin/main"
    )


def test_absent_remove_retries_unpublished_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store_with_remotes(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    [plan] = store.sidecar_roots.values()
    args = {
        "source_ref": "plan:202608/a.md",
        "relation": "related",
        "target_ref": "plan:202608/b.md",
        "why": "temporary relation",
    }
    add_artifact_link(**args)

    def fail_push(root: Path, **_kwargs: object) -> PushOutcome:
        assert Path(root).resolve() == plan.resolve()
        return PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="simulated tombstone publication failure",
        )

    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", fail_push)
        with pytest.raises(RuntimeError, match="NOT published"):
            remove_artifact_link(
                source_ref=args["source_ref"],
                target_ref=args["target_ref"],
                relation=args["relation"],
            )

    retry = remove_artifact_link(
        source_ref=args["source_ref"],
        target_ref=args["target_ref"],
        relation=args["relation"],
    )

    assert retry["rows"] == ()
    assert _git(plan, "rev-parse", "HEAD") == _git(plan, "rev-parse", "origin/main")


def test_add_and_rm_work_without_feature_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                relation="related",
                target_ref="plan:202608/b.md",
                why="shares a root cause",
            )
        )
        == 0
    )
    assert (
        handle_link_rm(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                target_ref="plan:202608/b.md",
                relation=None,
            )
        )
        == 0
    )
    assert capsys.readouterr().err == ""


def test_add_artifact_link_requires_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    with pytest.raises(ValueError, match="reason is required"):
        add_artifact_link(
            source_ref="plan:202608/a.md",
            relation="related",
            target_ref="plan:202608/b.md",
            why=" ",
        )
    assert store.load_artifact_rows("plan:202608/a.md") == ()


def test_add_rejects_reserved_and_machine_relations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(tmp_path, monkeypatch)
    patch_link_ops_store(monkeypatch, store)
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="bead:sase-a",
                relation="blocks",
                target_ref="bead:sase-b",
                why="ordering",
            )
        )
        == 1
    )
    assert "sase bead dep" in capsys.readouterr().err
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="agent:one",
                relation="cites",
                target_ref="plan:202608/a.md",
                why="from a prompt",
            )
        )
        == 1
    )
    assert "prompt-ref" in capsys.readouterr().err
    assert (
        handle_link_add(
            argparse.Namespace(
                source_ref="agent:alice.athena.9w",
                relation="awaits",
                target_ref="bead:sase-xx",
                why="waited on it",
            )
        )
        == 1
    )
    assert "not writable" in capsys.readouterr().err
