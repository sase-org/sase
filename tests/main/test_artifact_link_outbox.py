"""Tests for durable artifact-link read outbox replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli.read import handle_read
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd._artifact_link_ignore import ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN
from sase.sdd.artifact_link_outbox import (
    drain_artifact_link_outbox,
    _read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_cli_reference_helpers import resolved_reference


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_plans_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / ".gitignore").write_text(
        f"{ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN}\n",
        encoding="utf-8",
    )
    doc = repo / "doc.md"
    doc.write_text("# Doc\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    return doc


def _commit_count(repo: Path) -> int:
    return int(_run_git(repo, "rev-list", "--count", "HEAD").strip())


def _head_files(repo: Path) -> set[str]:
    names = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    return {line for line in names.splitlines() if line.strip()}


def _read_args() -> argparse.Namespace:
    return argparse.Namespace(
        reference="plan:doc.md",
        reason="Need the design of record",
        format="markdown",
        lines=None,
    )


def _patch_read_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    doc: Path,
    store: ArtifactLinkStore,
    agent_published: bool,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "reader")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    plan_result = resolved_reference(doc, reference="plan:doc.md")
    agent_result = resolved_reference(
        None,
        reference="agent:reader",
        status="exact" if agent_published else "missing",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: plan_result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_artifact_link_store",
        lambda: store,
    )

    def resolve_for_publication(value: str):
        if value == "agent:reader":
            return agent_result
        if value == "plan:doc.md":
            return plan_result
        raise RuntimeError(f"unexpected reference: {value}")

    monkeypatch.setattr(
        "sase.artifact_cli.references.resolve_cli_reference",
        resolve_for_publication,
    )


def _index_rows(repo: Path) -> list[dict[str, object]]:
    payload = json.loads((repo / "links" / "doc.md.json").read_text())
    rows = payload["rows"]
    assert isinstance(rows, list)
    return rows


def test_drain_published_agent_commits_dirty_index_without_double_counting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(
        monkeypatch,
        doc=doc,
        store=store,
        agent_published=True,
    )
    before = _commit_count(repo)

    assert handle_read(_read_args()) == 0
    assert handle_read(_read_args()) == 0
    assert len(_read_artifact_link_outbox_entries("gh_sase-org__sase")) == 2
    assert _commit_count(repo) == before
    assert "links/doc.md.json" in _run_git(
        repo, "status", "--porcelain", "--untracked-files=all"
    )

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 2
    assert report.committed is True
    assert _commit_count(repo) == before + 1
    assert _head_files(repo) == {"links/doc.md.json"}
    assert _read_artifact_link_outbox_entries("gh_sase-org__sase") == ()
    [row] = _index_rows(repo)
    assert row["uses"] == 2
    assert _run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_drain_unpublished_agent_leaves_entry_queued_and_uncommitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(
        monkeypatch,
        doc=doc,
        store=store,
        agent_published=False,
    )
    before = _commit_count(repo)

    assert handle_read(_read_args()) == 0
    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 0
    assert report.retained == 1
    assert report.committed is False
    assert _commit_count(repo) == before
    assert len(_read_artifact_link_outbox_entries("gh_sase-org__sase")) == 1
    assert "links/doc.md.json" in _run_git(
        repo, "status", "--porcelain", "--untracked-files=all"
    )
