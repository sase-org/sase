"""Shared helpers for plugins_required chop script tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

import pytest

import sase.scripts.sase_chop_plugins_required as plugins_required
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger

from tests.test_plugins_required_gate_helpers import missing_entry


def make_runtime(tmp_path: Path, *, dry_run: bool = False) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="plugins_required",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            dry_run=dry_run,
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def patch_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_by_project: dict[str, list[dict[str, str]]] | list[dict[str, str]],
    *,
    gate_state: str = "pending",
    skipped_projects: frozenset[str] = frozenset(),
    sweep_allowed: bool = True,
) -> None:
    if isinstance(missing_by_project, list):
        missing_by_project = {"sase": missing_by_project}
    checkouts = [(name, tmp_path / name) for name in missing_by_project]
    monkeypatch.setattr(
        plugins_required,
        "_enabled_project_checkouts",
        lambda _log: plugins_required._ProjectInventory(
            checkouts=tuple(checkouts),
            skipped_projects=skipped_projects,
            sweep_allowed=sweep_allowed,
        ),
    )
    monkeypatch.setattr(
        plugins_required,
        "collect_plugin_inventory",
        lambda **_kwargs: object(),
    )
    by_path = {
        tmp_path / name: list(entries) for name, entries in missing_by_project.items()
    }

    def collect(
        checkout: Path, *, inventory: object
    ) -> tuple[list[dict[str, str]], None]:
        del inventory
        if checkout not in by_path:
            raise OSError(f"no fixture for {checkout}")
        return list(by_path[checkout]), None

    monkeypatch.setattr(plugins_required, "_collect_missing", collect)
    monkeypatch.setattr(plugins_required, "_gate_state", lambda _request_id: gate_state)


def capture_created(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        plugins_required,
        "create_plugins_required_gate",
        lambda **kwargs: created.append(kwargs),
    )
    return created


def capture_canceled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    canceled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        plugins_required,
        "_cancel_pending_gate",
        lambda request_id, *, reason: canceled.append((request_id, reason)) or True,
    )
    return canceled


def expected_counters(
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    missing: int = 0,
    projects: int = 1,
    swept_projects: int = 0,
    untracked_canceled: int = 0,
) -> dict[str, int]:
    return {
        "gated": gated,
        "canceled": canceled,
        "skipped": skipped,
        "missing": missing,
        "projects": projects,
        "swept_projects": swept_projects,
        "untracked_canceled": untracked_canceled,
    }


__all__ = [
    "capture_canceled",
    "capture_created",
    "expected_counters",
    "make_runtime",
    "missing_entry",
    "patch_projects",
]
