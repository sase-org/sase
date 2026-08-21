"""Artifact path helpers for commit finalization."""

from __future__ import annotations

import os
from pathlib import Path


def artifact_root(artifacts_dir: str | None) -> Path | None:
    root = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    return Path(root) if root else None


__all__ = ["artifact_root"]
