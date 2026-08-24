"""Shared helpers for chop proposal-launch test modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sase.axe.config import AxeConfig

from tests.axe_chop_runner_helpers import make_script


def result_script(tmp_path: Path, name: str, document: dict[str, object]) -> None:
    payload = json.dumps(document)
    make_script(
        tmp_path,
        name,
        f"printf '%s' '{payload}' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )


def config(tmp_path: Path) -> AxeConfig:
    return AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")])


def known_project_resolver(repo: Path) -> object:
    return SimpleNamespace(
        workflow_type="git",
        ref="sase",
        workspace_dir=str(repo),
        project_file="/tmp/projects/sase/sase.sase",
    )
