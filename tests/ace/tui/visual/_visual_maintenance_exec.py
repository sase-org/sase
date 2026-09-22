"""Governed pytest execution and capture verification for visual maintenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from tests.ace.tui.visual._visual_capture import load_inventory
from tests.ace.tui.visual._visual_maintenance_baseline import (
    default_ace_root,
    default_pager_root,
)
from tests.ace.tui.visual._visual_maintenance_compare import (
    compare_verification_captures,
)
from tests.ace.tui.visual._visual_maintenance_manifest import posix_relative
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_UPDATED,
    ChangeRecord,
    GoldenBaseline,
    MaintenanceError,
    MaintenanceHooks,
)


def build_run_pytest_command(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    ace_root: Path,
    pager_root: Path,
) -> list[str]:
    """Return the governed visual runner command for candidate capture."""
    command = [
        sys.executable,
        str(repo_root / "tools" / "run_pytest"),
        "visual",
        "--sase-visual-capture-dir",
        str(capture_dir),
        "--sase-visual-capture-run-id",
        run_id,
        "--sase-visual-capture-scope",
        scope,
        "--sase-visual-capture-ace-root",
        posix_relative(ace_root, repo_root),
        "--sase-visual-capture-pager-root",
        posix_relative(pager_root, repo_root),
        *pytest_args,
    ]
    return command


WORKERS_ENV_VAR = "SASE_PYTEST_WORKERS"


def run_governed_visual_pytest(
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
    ace_root: Path,
    pager_root: Path,
    workers: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Invoke ``tools/run_pytest visual`` with candidate capture enabled.

    When *workers* is set, the child runs with ``SASE_PYTEST_WORKERS=<n>``
    in a copy of the process environment. ``None`` keeps the governed
    default.
    """
    command = build_run_pytest_command(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        ace_root=ace_root,
        pager_root=pager_root,
    )
    child_env: Mapping[str, str] | None = None
    if workers is not None:
        base = dict(os.environ if environ is None else environ)
        base[WORKERS_ENV_VAR] = str(workers)
        child_env = base
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(child_env) if child_env is not None else None,
        )
        assert proc.stdout is not None
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                log.write(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            return int(proc.wait())
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise


def run_pytest(
    hooks: MaintenanceHooks,
    *,
    repo_root: Path,
    capture_dir: Path,
    run_id: str,
    scope: str,
    pytest_args: Sequence[str],
    log_path: Path,
    workers: int | None = None,
) -> int:
    runner = hooks.run_pytest or run_governed_visual_pytest
    return runner(
        repo_root=repo_root,
        capture_dir=capture_dir,
        run_id=run_id,
        scope=scope,
        pytest_args=pytest_args,
        log_path=log_path,
        ace_root=default_ace_root(repo_root),
        pager_root=default_pager_root(repo_root),
        workers=workers,
    )


def verify_changes(
    hooks: MaintenanceHooks,
    *,
    repo_root: Path,
    first: Any,
    changes: Sequence[ChangeRecord],
    verify_dir: Path,
    run_id: str,
    log_path: Path,
) -> None:
    node_ids = sorted(
        {
            change.node_id
            for change in changes
            if change.kind in {KIND_CREATED, KIND_UPDATED} and change.node_id
        }
    )
    if not node_ids:
        return
    child_exit = run_pytest(
        hooks,
        repo_root=repo_root,
        capture_dir=verify_dir,
        run_id=f"{run_id}-verify",
        scope="targeted",
        pytest_args=tuple(node_ids),
        log_path=log_path,
    )
    inventory_path = verify_dir / "inventory.json"
    if child_exit != 0 or not inventory_path.is_file():
        raise MaintenanceError(
            "determinism verification pytest failed; goldens were not changed "
            f"(child_exit_code={child_exit})"
        )
    second = load_inventory(inventory_path)
    if not second.complete:
        reasons = ", ".join(second.reasons) or "incomplete"
        raise MaintenanceError(
            f"determinism verification inventory is incomplete ({reasons})"
        )
    mismatches = compare_verification_captures(first, second, node_ids)
    if mismatches:
        raise MaintenanceError(
            "determinism verification disagreed with the first capture: "
            + "; ".join(mismatches)
        )


def assert_pruning_safe(inventory: Any, baseline: GoldenBaseline) -> None:
    """Refuse orphan deletion when a full run produced no captures for a root."""
    if not inventory.pruning_allowed:
        return
    if not inventory.captures:
        raise MaintenanceError(
            "full inventory produced no screenshot captures; refusing stale "
            "deletion so a failed capture plugin cannot wipe goldens"
        )
    captured_roots = {record.root_identity for record in inventory.captures}
    for identity in ("ace", "pager"):
        has_goldens = any(
            state.root_identity == identity for state in baseline.files.values()
        )
        if has_goldens and identity not in captured_roots:
            raise MaintenanceError(
                f"full inventory captured no {identity} screenshots; "
                "refusing stale deletion for that root"
            )
