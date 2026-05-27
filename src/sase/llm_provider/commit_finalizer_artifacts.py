"""Artifact persistence helpers for commit finalization."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .commit_finalizer_types import CommitFinalizerResult


def artifact_root(artifacts_dir: str | None) -> Path | None:
    root = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    return Path(root) if root else None


def write_text(root: Path | None, filename: str, content: str) -> None:
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / filename).write_text(content, encoding="utf-8")
    except OSError:
        pass


def write_result(
    root: Path | None,
    result: CommitFinalizerResult,
) -> None:
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "commit_finalizer_result.json").write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
