"""Shared helpers for chop proposal-launch test modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.axe.config import AxeConfig

from tests.axe_chop_runner_helpers import make_script
from tests.workspace_lease_helpers import fake_operational_lease


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


def patch_condition_workspace_lease(monkeypatch: Any, checkout: Path) -> None:
    def fake_acquire(
        project: str,
        *,
        workflow: str,
        holder: str,
        **_kwargs: object,
    ) -> object:
        return fake_operational_lease(
            checkout,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.acquire_operational_lease",
        fake_acquire,
    )
    monkeypatch.setattr(
        "sase.agent.launch_condition_workspace.release_operational_lease",
        lambda _policy: None,
    )
