"""Helpers for repo-init creation tests."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from sase.sdd._sidecar_init import SidecarInitSpec
from sase.workspace_provider import SddSidecarPreflight


class Tty:
    def isatty(self) -> bool:
        return True


def make_args(path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "check": False,
        "diff": False,
        "no_commit": True,
        "path": str(path),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def mark_managed_project(
    path: Path,
    config: str = "is_sase_managed: true\n",
) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    config_path = path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")


def patch_agents_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )


def make_preflight(
    role: str,
    *,
    status: str = "not_found",
    visibility: str = "public",
    repo: str | None = None,
) -> SddSidecarPreflight:
    return SddSidecarPreflight(
        status=status,  # type: ignore[arg-type]
        provider="GitHub",
        host="github.com",
        repo=repo or f"acme/widget--{role}",
        visibility=visibility,
    )


def sidecar_outcome(path: Path, specs: tuple[SidecarInitSpec, ...]) -> Any:
    return SimpleNamespace(
        store=None,
        record=None,
        created=frozenset(),
        roots={spec.role: path / "sase" / "repos" / spec.role for spec in specs},
    )
