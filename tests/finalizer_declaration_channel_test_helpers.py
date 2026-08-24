"""Shared helpers for finalizer declaration-channel tests."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalContextPublication,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.xprompt.directives import PromptDirectives

APP_FINGERPRINTS: dict[str, tuple[str, str]] = {"src/app.py": ("M", "abc123")}


def prepare_agent_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")


def dirty_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )


def clean_state(repo: Path) -> DirtyState:
    return DirtyState(project_dir=str(repo), repos=(), details="")


def persist_default_plan(tmp_path: Path) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(tmp_path),
    )


def valid_manifest(publication: FinalContextPublication) -> dict[str, object]:
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    repositories[0]["message"] = "fix(final): submit declaration"
    return manifest


def attempt_records(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (root / FINAL_SUBMISSION_ATTEMPTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def patch_dirty(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    *,
    fingerprints: dict[str, tuple[str, str]] | None = None,
    collect: Callable[[object], DirtyState] | None = None,
) -> dict[str, tuple[str, str]]:
    if fingerprints is None:
        fingerprints = dict(APP_FINGERPRINTS)
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        collect if collect is not None else (lambda _root: dirty_state(repo)),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: dict(fingerprints),
    )
    return fingerprints


def prepare_dirty_declaration(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    *,
    fingerprints: dict[str, tuple[str, str]] | None = None,
    collect: Callable[[object], DirtyState] | None = None,
) -> dict[str, tuple[str, str]]:
    prepare_agent_env(monkeypatch, repo)
    resolved = patch_dirty(
        monkeypatch,
        repo,
        fingerprints=fingerprints,
        collect=collect,
    )
    persist_default_plan(repo)
    return resolved
