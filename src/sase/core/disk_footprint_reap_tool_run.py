"""ToolRun ledger owner step for ``sase disk reap``."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config.tools import ToolRunsConfigError, get_tool_runs_config
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_footprint_utils import normalize_path_no_follow
from sase.core.tool_run import (
    tool_run_retention_apply,
    tool_run_retention_preview,
    tool_run_store_path,
    tool_run_store_stats,
    tool_run_wire_schema_version,
    tools_dir,
)


@dataclass(frozen=True)
class EmptyLogDirSweep:
    """Result of removing or previewing empty ToolRun log directories."""

    scanned: int
    selected: int
    removed: int
    errors: tuple[str, ...]
    paths: tuple[str, ...]


def tool_run_reap_step(*, apply: bool) -> DiskReapStep:
    """Preview or apply ToolRun retention without a second reaper."""

    store_path = str(tool_run_store_path())
    try:
        schema_version = tool_run_wire_schema_version()
        stats = tool_run_store_stats(store_path=store_path)
        policy = get_tool_runs_config()
        request = {"schema_version": 1, "policy": {"schema_version": 1, **policy}}
        report = (
            tool_run_retention_apply(request, store_path=store_path)
            if apply
            else tool_run_retention_preview(request, store_path=store_path)
        )
    except ToolRunsConfigError as exc:
        return DiskReapStep(
            owner="tool_run_retention",
            mode="blocked",
            summary=f"invalid tool_runs policy: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="tool_run_retention",
            mode="blocked",
            summary=f"could not inspect tool run owner: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    file_candidates = list(report.get("file_candidates") or ())
    deleted_bytes = 0
    removed = 0
    errors: list[str] = []
    if apply:
        deleted_bytes, removed, errors = _delete_authorized_files(file_candidates)
    empty_dirs = remove_empty_tool_run_log_dirs(apply=apply)
    errors.extend(empty_dirs.errors)
    summary_rows = int(report.get("summary_rows") or 0)
    detail_rows = int(report.get("detail_rows") or 0)
    protected = int(report.get("protected_unsettled") or 0)
    over_target = int(report.get("over_target_bytes") or 0)
    empty_phrase = (
        f"{empty_dirs.removed} empty run dir(s)"
        if apply
        else f"{empty_dirs.selected} empty run dir(s)"
    )
    if apply:
        summary = (
            f"removed {summary_rows} summary row(s), {detail_rows} detail row(s), "
            f"{removed} file(s), {empty_phrase}; protected unsettled={protected}"
        )
    else:
        summary = (
            f"would remove {summary_rows} summary row(s), {detail_rows} detail row(s), "
            f"{len(file_candidates)} file(s), {empty_phrase}; "
            f"protected unsettled={protected}"
        )
    if over_target:
        summary += (
            f"; {over_target} protected byte(s) remain over the "
            f"log_max_bytes={policy['log_max_bytes']} target"
        )
    return DiskReapStep(
        owner="tool_run_retention",
        mode="apply" if apply else "dry_run",
        summary=summary,
        reclaimed_bytes=deleted_bytes if apply else 0,
        changed=bool(
            apply and (summary_rows or detail_rows or removed or empty_dirs.removed)
        ),
        command=("sase", "disk", "reap", "--apply"),
        exit_code=1 if errors else None,
        owner_error="; ".join(errors) if errors else None,
        byte_accounting_complete=not errors,
        details={
            "schema_version": schema_version,
            "store_stats": stats,
            "summary_rows": summary_rows,
            "detail_rows": detail_rows,
            "file_candidates": file_candidates,
            "protected_unsettled": protected,
            "retained_bytes": int(report.get("retained_bytes") or 0),
            "protected_bytes": int(report.get("protected_bytes") or 0),
            "over_target_bytes": over_target,
            "removed_files": removed,
            "empty_dirs_scanned": empty_dirs.scanned,
            "empty_dirs_selected": empty_dirs.selected,
            "empty_dirs_removed": empty_dirs.removed,
            "empty_dirs": list(empty_dirs.paths),
            "diagnostics": list(report.get("diagnostics") or ()),
        },
    )


def _delete_authorized_files(
    candidates: list[Any],
) -> tuple[int, int, list[str]]:
    root = normalize_path_no_follow(tools_dir())
    deleted_bytes = 0
    removed = 0
    errors: list[str] = []
    for candidate in candidates:
        raw_path = None
        if isinstance(candidate, dict):
            if candidate.get("protected"):
                continue
            raw_path = candidate.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path))
        try:
            reclaimed = _delete_confined(path, root)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        if reclaimed is not None:
            deleted_bytes += reclaimed
            removed += 1
    return deleted_bytes, removed, errors


def _delete_confined(path: Path, root: Path) -> int | None:
    """Delete one authorized file without following symlinks."""

    lexical = normalize_path_no_follow(path)
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise OSError(f"path escapes tool-run root {root}") from exc
    try:
        st = os.lstat(lexical)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode) or stat.S_ISDIR(st.st_mode):
        return None
    size = int(st.st_size)
    os.unlink(lexical)
    return size


def _tool_run_logs_dir() -> Path:
    """Return the confined ToolRun log root ``tools_dir()/logs``."""

    return tools_dir() / "logs"


def remove_empty_tool_run_log_dirs(
    *,
    apply: bool = True,
    logs_root: Path | None = None,
) -> EmptyLogDirSweep:
    """Remove empty run directories under the ToolRun logs root.

    Walks deepest-first without following symlinks and stays lexically inside
    ``logs_root``. Live directories that still contain files are kept.
    """

    root = normalize_path_no_follow(logs_root or _tool_run_logs_dir())
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return EmptyLogDirSweep(0, 0, 0, (), ())
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return EmptyLogDirSweep(0, 0, 0, (), ())

    scanned = 0
    selected_paths: list[Path] = []
    removed_paths: list[Path] = []
    errors: list[str] = []
    for dirpath, _dirnames, _filenames in os.walk(
        root, topdown=False, followlinks=False
    ):
        path = Path(dirpath)
        if path == root:
            continue
        lexical = normalize_path_no_follow(path)
        try:
            lexical.relative_to(root)
        except ValueError:
            errors.append(f"{path}: path escapes tool-run log root {root}")
            continue
        try:
            child_st = os.lstat(lexical)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{lexical}: {exc}")
            continue
        if stat.S_ISLNK(child_st.st_mode) or not stat.S_ISDIR(child_st.st_mode):
            continue
        scanned += 1
        try:
            with os.scandir(lexical) as entries:
                if next(entries, None) is not None:
                    continue
        except OSError as exc:
            errors.append(f"{lexical}: {exc}")
            continue
        selected_paths.append(lexical)
        if not apply:
            continue
        try:
            os.rmdir(lexical)
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{lexical}: {exc}")
            continue
        removed_paths.append(lexical)
    reported = removed_paths if apply else selected_paths
    return EmptyLogDirSweep(
        scanned=scanned,
        selected=len(selected_paths),
        removed=len(removed_paths),
        errors=tuple(errors),
        paths=tuple(str(path) for path in reported),
    )
