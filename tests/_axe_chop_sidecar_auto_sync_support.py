"""Shared fixtures for sidecar auto-sync chop tests.

This is a private helper module: the names it defines are public on
purpose so the split ``test_axe_chop_sidecar_auto_sync_*`` modules can
import them without crossing a ``_``-prefixed boundary. Helpers used by
a single module live in that module instead.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import sase.scripts.sase_chop_sidecar_auto_sync as sidecar_sync_chop
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger


def make_runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="sidecar_auto_sync",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="waits",
            state_dir=str(tmp_path / "state"),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def make_project(
    tmp_path: Path,
    *,
    name: str = "proj",
) -> SimpleNamespace:
    workspace_dir = tmp_path / "projects" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    project_file = tmp_path / "projects" / f"{name}.project"
    project_file.write_text(
        "WORKSPACE_DIR=" + str(workspace_dir) + "\n", encoding="utf-8"
    )
    return SimpleNamespace(
        is_project=True,
        workspace_dir=str(workspace_dir),
        project_name=name,
        project_file=str(project_file),
    )


def configure_sidecar_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    records: list[SimpleNamespace],
    roles_by_project: dict[str, tuple[str, ...]],
    hinted_by_project: dict[str, tuple[str, ...]] | None = None,
    live_bead_wait_projects: frozenset[str] = frozenset(),
    bead_refresh_mode: str = "background",
) -> None:
    monkeypatch.setattr(sidecar_sync_chop, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(
        sidecar_sync_chop, "list_project_records", lambda *_a, **_kw: records
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "auto_sync_roles",
        lambda primary: roles_by_project.get(Path(primary).name, ()),
    )
    hinted = hinted_by_project or {}
    monkeypatch.setattr(
        sidecar_sync_chop,
        "pending_sidecar_sync_roles",
        lambda project_key: hinted.get(project_key, ()),
    )
    monkeypatch.setattr(
        sidecar_sync_chop, "bead_refresh_mode", lambda: bead_refresh_mode
    )
    monkeypatch.setattr(
        sidecar_sync_chop,
        "_projects_with_live_bead_waits",
        lambda _root: live_bead_wait_projects,
    )
    monkeypatch.setattr(sidecar_sync_chop, "mark_sidecar_sync_hint", MagicMock())
    # The scheduler maintenance legs touch host state (hidden clones,
    # ~/.sase/bead_push_logs); stub them so these tests stay hermetic.
    # Leg-specific tests below re-enable the seam they exercise.
    monkeypatch.setattr(
        sidecar_sync_chop, "_maintain_hidden_sidecar_clones", lambda *a, **k: 0
    )
    monkeypatch.setattr(sidecar_sync_chop, "_prune_bead_push_logs", lambda *a, **k: 0)


__all__ = [
    "configure_sidecar_sync",
    "make_project",
    "make_runtime",
]
