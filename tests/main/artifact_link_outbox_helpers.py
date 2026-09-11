"""Shared helpers for artifact-link outbox tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd._artifact_link_ignore import ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN
from sase.sdd.artifact_link_outbox import ARTIFACT_LINK_OUTBOX_FILENAME
from sase.sdd.artifact_link_store import ArtifactLinkStore
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
    run_id: str = "run-1",
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "reader")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", run_id)
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    plan_result = resolved_reference(doc, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: plan_result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_artifact_link_store",
        lambda: store,
    )


def _outbox_lines(home: Path, project_key: str) -> list[dict[str, object]]:
    path = home / "projects" / project_key / ARTIFACT_LINK_OUTBOX_FILENAME
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
