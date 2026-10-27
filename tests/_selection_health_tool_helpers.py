"""Shared fixtures and synthetic record helpers for selection-health tool tests."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    allocate_record_path,
    full_run_record,
    write_record,
)

ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "selection_health"
NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
WORKSPACE = "/workspaces/sase_11"
FLAKE_NODE = "tests/test_flaky.py::test_x"
AUDIT_NODE = (
    "tests/test_agent_artifact_marker_path_passing_audit.py"
    "::test_tracked_marker_path_passing_sites_are_reviewed"
)


def load_tool() -> ModuleType:
    loader = SourceFileLoader("selection_health_tool", str(TOOL_PATH))
    spec = importlib.util.spec_from_file_location(
        "selection_health_tool", TOOL_PATH, loader=loader
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_full_run(
    store: Path,
    *,
    minute: int,
    changed_files: list[str],
    failures: list[str],
    tree_dirty: bool | None = None,
) -> None:
    when = NOW + timedelta(minutes=minute)
    path = allocate_record_path(
        store, KIND_FULL_RUN, head=f"h{minute}", pid=minute, now=when
    )
    write_record(
        path,
        full_run_record(
            head=f"h{minute}",
            mode="fast",
            failures=failures,
            exit_status=1,
            workspace=WORKSPACE,
            changed_files=changed_files,
            tree_dirty=tree_dirty,
            now=when,
        ),
    )


def write_baseline(
    path: Path,
    *,
    nodeids: tuple[str, ...] = (),
    effective_after: str | None = None,
    retirements: tuple[tuple[str, str], ...] = (),
) -> Path:
    lines = [
        "# Reproducible-flake baseline for tests.",
        "# Entries are debt to remove.",
    ]
    if effective_after is not None:
        lines.append(f"# effective-after: {effective_after}")
    lines.extend(
        f"# fixed-at: {timestamp} {nodeid}" for timestamp, nodeid in retirements
    )
    lines.extend(nodeids)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
