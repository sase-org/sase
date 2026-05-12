"""Archive lifecycle operations for dismissed agent bundles."""

from __future__ import annotations

import json
import os
import tarfile
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any


def purge_dismissed_archive(
    ctx: Any,
    *,
    before: str | None = None,
    agent_id: str | None = None,
    query: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Purge archived bundle rows selected by a lifecycle selector."""
    rows = select_archive_lifecycle_rows(
        ctx,
        before=before,
        agent_id=agent_id,
        query=query,
    )
    row_refs = [archive_row_ref(row) for row in rows]
    report: dict[str, Any] = {
        "ok": True,
        "operation": "purge",
        "dry_run": dry_run,
        "matched": len(rows),
        "purged": 0,
        "failed": [],
        "rows": row_refs,
        "summary_rows_removed": 0,
        "fts_rows_removed": 0,
        "visibility_rows_removed": 0,
        "annotation_rows_removed": 0,
    }
    if dry_run or not rows:
        return report

    from .dismissed_bundle_index import (
        archive_maintenance_lock,
        delete_bundle_summaries_for_paths,
    )

    removed_paths: set[str] = set()
    removed_suffixes: set[str] = set()
    failures: list[dict[str, str]] = []
    with archive_maintenance_lock(ctx._DISMISSED_BUNDLES_DIR):
        for row in rows:
            path = Path(row.bundle_path)
            try:
                path.unlink()
                if path.name == "bundle.json" and path.parent.name.count(".") >= 1:
                    try:
                        path.parent.rmdir()
                    except OSError:
                        pass
                removed_paths.add(row.bundle_path)
                removed_suffixes.add(row.raw_suffix)
            except FileNotFoundError:
                removed_paths.add(row.bundle_path)
                removed_suffixes.add(row.raw_suffix)
            except OSError as exc:
                failures.append(
                    {
                        "agent_id": row.agent_id,
                        "bundle_path": row.bundle_path,
                        "error": str(exc),
                    }
                )
        if removed_paths:
            if delete_bundle_summaries_for_paths(
                ctx._DISMISSED_BUNDLES_DIR, removed_paths
            ):
                report["summary_rows_removed"] = len(removed_paths)
                report["fts_rows_removed"] = len(removed_paths)
            else:
                failures.append(
                    {
                        "agent_id": "",
                        "bundle_path": "",
                        "error": "failed to remove archive index rows",
                    }
                )
        if removed_suffixes:
            dismissed = ctx.load_dismissed_agents()
            next_dismissed = {
                identity
                for identity in dismissed
                if identity[2] is None or identity[2] not in removed_suffixes
            }
            if next_dismissed != dismissed and ctx.save_dismissed_agents(
                next_dismissed
            ):
                report["visibility_rows_removed"] = len(dismissed - next_dismissed)

    report["purged"] = len(removed_paths)
    report["failed"] = failures
    report["ok"] = not failures
    append_archive_audit_event(ctx, report)
    return report


def scrub_dismissed_archive(
    ctx: Any,
    *,
    before: str | None = None,
    query: str | None = None,
    since_scrubber_version: int | None = None,
) -> dict[str, Any]:
    """Redact archive search projections for selected bundles."""
    from .archive_search_text import (
        ARCHIVE_SEARCH_SCRUBBER_VERSION,
        normalize_archive_bundle_projection,
        scrub_archive_text,
    )
    from .dismissed_bundle_index import (
        archive_payload_hash,
        upsert_bundle_summary,
    )

    rows = select_archive_lifecycle_rows(ctx, before=before, query=query)
    target_version = max(
        ARCHIVE_SEARCH_SCRUBBER_VERSION,
        since_scrubber_version or ARCHIVE_SEARCH_SCRUBBER_VERSION,
    )
    scrubbed = 0
    unchanged = 0
    failures: list[dict[str, str]] = []
    for row in rows:
        path = Path(row.bundle_path)
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(bundle, dict):
                raise ValueError("bundle JSON must be an object")
            current_version = nonnegative_int(
                bundle.get("archive_search_scrubber_version")
            )
            if (
                since_scrubber_version is not None
                and current_version >= since_scrubber_version
            ):
                unchanged += 1
                continue
            before_bundle = json.dumps(bundle, sort_keys=True)
            normalize_archive_bundle_projection(bundle)
            text = bundle.get("archive_search_text")
            if isinstance(text, str):
                bundle["archive_search_text"] = scrub_archive_text(text)
            bundle["archive_search_scrubber_version"] = target_version
            bundle["archive_payload_sha256"] = archive_payload_hash(bundle)
            if json.dumps(bundle, sort_keys=True) == before_bundle:
                unchanged += 1
                continue
            ctx._write_json_file_atomic(path, bundle)
            upsert_bundle_summary(ctx._DISMISSED_BUNDLES_DIR, path, bundle)
            scrubbed += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(
                {
                    "agent_id": row.agent_id,
                    "bundle_path": row.bundle_path,
                    "error": str(exc),
                }
            )

    report: dict[str, Any] = {
        "ok": not failures,
        "operation": "scrub",
        "matched": len(rows),
        "scrubbed": scrubbed,
        "unchanged": unchanged,
        "scrubber_version": target_version,
        "failed": failures,
        "rows": [archive_row_ref(row) for row in rows],
    }
    append_archive_audit_event(ctx, report)
    return report


def export_dismissed_archive(ctx: Any, *, query: str, out: Path) -> dict[str, Any]:
    """Export matching archive bundles to a restorable tar artifact."""
    rows = select_archive_lifecycle_rows(ctx, query=query)
    out = out.expanduser()
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(),
        "query": query,
        "bundle_count": len(rows),
        "rows": [archive_row_ref(row) for row in rows],
    }
    failures: list[dict[str, str]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out.with_name(f".{out.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        with tarfile.open(tmp_path, "w:gz") as archive:
            manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode(
                "utf-8"
            )
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(manifest_bytes)
            archive.addfile(manifest_info, fileobj=BytesIO(manifest_bytes))
            for row in rows:
                path = Path(row.bundle_path)
                try:
                    arcname = f"bundles/{row.agent_id}.{row.raw_suffix}.json"
                    archive.add(path, arcname=arcname, recursive=False)
                except OSError as exc:
                    failures.append(
                        {
                            "agent_id": row.agent_id,
                            "bundle_path": row.bundle_path,
                            "error": str(exc),
                        }
                    )
        os.replace(tmp_path, out)
        ctx._fsync_dir(out.parent)
    except OSError as exc:
        failures.append({"agent_id": "", "bundle_path": str(out), "error": str(exc)})
        try:
            tmp_path.unlink()
        except OSError:
            pass

    report: dict[str, Any] = {
        "ok": not failures,
        "operation": "export",
        "query": query,
        "out": str(out),
        "matched": len(rows),
        "exported": len(rows) - len(failures),
        "failed": failures,
        "rows": manifest["rows"],
    }
    append_archive_audit_event(ctx, report)
    return report


def select_archive_lifecycle_rows(
    ctx: Any,
    *,
    before: str | None = None,
    agent_id: str | None = None,
    query: str | None = None,
) -> list[Any]:
    """Return archive summary rows matching one lifecycle selector."""
    from .agent_query.archive_planner import search_archive, select_archive_results
    from .dismissed_bundle_index import archive_index_exists, rebuild_index

    if not archive_index_exists(ctx._DISMISSED_BUNDLES_DIR):
        rebuild_index(ctx._DISMISSED_BUNDLES_DIR)
    if agent_id:
        return select_archive_results(
            ctx._DISMISSED_BUNDLES_DIR,
            agent_id=agent_id,
            limit=100000,
        )
    query_text = query or ""
    if before:
        query_text = f"archived_before:{before}"

    rows: list[Any] = []
    cursor: int | None = None
    while True:
        page = search_archive(
            ctx._DISMISSED_BUNDLES_DIR,
            query_text,
            limit=1000,
            cursor=cursor,
        )
        rows.extend(page.results)
        if page.next_cursor is None:
            return rows
        cursor = page.next_cursor


def archive_row_ref(row: Any) -> dict[str, Any]:
    return {
        "agent_id": row.agent_id,
        "raw_suffix": row.raw_suffix,
        "bundle_path": row.bundle_path,
        "cl_name": row.cl_name,
        "agent_name": row.agent_name,
        "status": row.status,
        "dismissed_at": row.dismissed_at,
    }


def append_archive_audit_event(ctx: Any, report: dict[str, Any]) -> None:
    """Append a redacted lifecycle audit event under the archive root."""
    try:
        ctx._DISMISSED_BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = ctx._DISMISSED_BUNDLES_DIR / "archive_audit.jsonl"
        event = redact_audit_value(
            {
                "time": datetime.now().isoformat(),
                "operation": report.get("operation"),
                "ok": report.get("ok"),
                "matched": report.get("matched"),
                "dry_run": report.get("dry_run"),
                "out": report.get("out"),
                "query": report.get("query"),
                "failed": report.get("failed"),
            }
        )
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True))
            handle.write("\n")
    except OSError:
        pass


def redact_audit_value(value: Any) -> Any:
    from .archive_search_text import scrub_archive_text

    if isinstance(value, str):
        return scrub_archive_text(value)
    if isinstance(value, dict):
        return {str(k): redact_audit_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_audit_value(item) for item in value]
    return value


def nonnegative_int(value: object) -> int:
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            return 0
    return 0
