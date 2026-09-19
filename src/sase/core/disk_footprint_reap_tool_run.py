"""ToolRun ledger owner step for ``sase disk reap``."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

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


def tool_run_reap_step(*, apply: bool) -> DiskReapStep:
    """Preview or apply ToolRun retention without a second reaper."""

    store_path = str(tool_run_store_path())
    try:
        schema_version = tool_run_wire_schema_version()
        stats = tool_run_store_stats(store_path=store_path)
        report = (
            tool_run_retention_apply({"schema_version": 1}, store_path=store_path)
            if apply
            else tool_run_retention_preview(
                {"schema_version": 1}, store_path=store_path
            )
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
    summary_rows = int(report.get("summary_rows") or 0)
    detail_rows = int(report.get("detail_rows") or 0)
    protected = int(report.get("protected_unsettled") or 0)
    if apply:
        summary = (
            f"removed {summary_rows} summary row(s), {detail_rows} detail row(s), "
            f"{removed} file(s); protected unsettled={protected}"
        )
    else:
        summary = (
            f"would remove {summary_rows} summary row(s), {detail_rows} detail row(s), "
            f"{len(file_candidates)} file(s); protected unsettled={protected}"
        )
    return DiskReapStep(
        owner="tool_run_retention",
        mode="apply" if apply else "dry_run",
        summary=summary,
        reclaimed_bytes=deleted_bytes if apply else 0,
        changed=bool(apply and (summary_rows or detail_rows or removed)),
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
            "removed_files": removed,
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
