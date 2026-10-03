"""Off-thread materialization for view-file hint requests."""

from __future__ import annotations

import os
from typing import Any

from sase.memory.legacy_glossary_read_report import (
    GlossaryReadReportSpec,
    write_glossary_read_report,
)
from sase.memory.memory_read_report import (
    MemoryReadReportSpec,
    memory_read_file_paths,
    write_memory_read_report,
)
from sase.pager.document import PagerSection
from sase.pager.resolve import resolve_link

from ...artifact_reads import ArtifactReadRefSpec
from ...llm_calls.report import write_tool_call_report
from ._artifact_ref_repair import repair_artifact_read_path
from ._link_context_capture import CapturedLinkContext, link_context_from_capture
from ._view_models import HintReportSpec, MaterializedReports


def memory_version_pin_sections(
    pins: tuple[Any, ...],
) -> tuple[list[Any], list[str]]:
    """Build one pager section per version-pinned memory hint (off-thread).

    Returns ``(sections, failures)``. Committed pins open through
    ``build_history_document`` at the version read; not-in-git launch
    snapshots open as read-only documents from the stored snapshot
    bytes. Mirrors ``materialize_tool_run_log_documents``: real I/O
    here, UI effects in the caller.
    """
    from pathlib import Path as _Path

    sections: list[Any] = []
    failures: list[str] = []
    if not pins:
        return (sections, failures)
    try:
        from sase.memory.history.service import shared_history_service

        service = shared_history_service()
    except Exception as exc:
        return (sections, [f"memory history unavailable: {exc}"])
    for pin in pins:
        title = str(getattr(pin, "title", "") or "memory version")
        snapshot_path = getattr(pin, "snapshot_path", None)
        if getattr(pin, "revision", "") == "snapshot" or snapshot_path:
            snapshot_title = str(
                getattr(pin, "snapshot_title", None) or f"{title} · not in git"
            )
            section = _snapshot_section(snapshot_path, snapshot_title, title)
            if section is None:
                failures.append(f"{title}: snapshot unavailable")
                continue
            sections.append(section)
            continue
        scope_key = str(getattr(pin, "scope_key", "") or "")
        repo_root = str(getattr(pin, "repo_root", "") or "")
        subject = str(getattr(pin, "subject", "") or "")
        revision = str(getattr(pin, "revision", "") or "now")
        try:
            if scope_key == "home":
                scope = service.home_scope()
                if scope is None:
                    raise ValueError("home memory is not in git (NO VCS)")
            else:
                scope = service.project_scope(_Path(repo_root))
        except Exception as exc:
            failures.append(f"{title}: cannot resolve scope: {exc}")
            continue
        try:
            from sase.memory.history.pager_provider import (
                build_history_document,
            )

            document = build_history_document(
                scope=scope,
                subject=subject,
                initial_revision=revision,
                view="read",
                service=service,
                title=title,
            )
        except Exception as exc:
            failures.append(f"{title}: cannot open {revision}: {exc}")
            continue
        try:
            sections.extend(document.sections)
        except Exception:
            failures.append(f"{title}: cannot open {revision}")
    return (sections, failures)


def _snapshot_section(
    snapshot_path: Any, snapshot_title: str, title: str
) -> Any | None:
    """Return a read-only pager section for stored snapshot bytes."""
    if not snapshot_path:
        return None
    try:
        from pathlib import Path as _Path

        body = _Path(str(snapshot_path)).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        from sase.pager.document import PagerOrigin, PagerSection
        from sase.pager.syntax_policy import classify_source
    except Exception:
        return None
    return PagerSection(
        identity=f"memory-launch-snapshot:{title}",
        title=snapshot_title,
        kind="file",
        body=body,
        subject_ref=str(snapshot_path),
        raw_source=classify_source(
            category="raw_file", logical_filename="AGENTS.md", source=body
        ),
        origin=PagerOrigin.FILE,
    )


def materialize_tool_run_log_documents(
    run_ids: tuple[str, ...],
) -> tuple[list[Any], list[str]]:
    """Build one pager document per retained run log (runs off-thread).

    Returns ``(documents, failures)``. Each document holds a single
    text section from the run's bounded tail, read through the detail
    LRU so a visible block never re-reads.
    """

    from sase.ace.tui.tool_runs.detail import load_tool_run_detail_blocking
    from sase.ace.tui.tool_runs.hints import build_tool_run_log_pager_document

    documents: list[Any] = []
    failures: list[str] = []
    for run_id in run_ids:
        try:
            loaded = load_tool_run_detail_blocking(run_id)
        except Exception:
            loaded = None
        tail = getattr(loaded, "tail", None) if loaded is not None else None
        lines = tuple(getattr(tail, "lines", ()) or ()) if tail is not None else ()
        if not lines:
            failures.append(f"⚒ run log {run_id[:8]} has no retained log")
            continue
        brief = getattr(loaded, "detail", None)
        brief = getattr(brief, "brief", None) if brief is not None else None
        label = (
            str(getattr(brief, "label", "") or "run") if brief is not None else "run"
        )
        try:
            documents.append(
                build_tool_run_log_pager_document(
                    run_id,
                    label,
                    lines,
                    availability=str(getattr(tail, "availability", "available") or ""),
                    truncated=bool(getattr(tail, "truncated", False)),
                )
            )
        except Exception:
            failures.append(f"⚒ run log {run_id[:8]} could not be opened")
    return (documents, failures)


def materialize_selected_view_files(
    files: tuple[str, ...],
    report_items: tuple[tuple[str, HintReportSpec], ...],
    artifact_read_ref_items: tuple[tuple[str, ArtifactReadRefSpec], ...],
    captured_link_context: CapturedLinkContext,
    bead_ids: tuple[str, ...] = (),
) -> MaterializedReports:
    """Materialize reports, repair artifact-read paths, and drop stale files."""
    link_context = link_context_from_capture(captured_link_context)
    bead_sections: list[PagerSection] = []
    bead_failures: list[str] = []
    for bead_id in bead_ids:
        resolution = resolve_link(f"bead:{bead_id}", context=link_context)
        target = resolution.target
        if target is not None and target.document is not None:
            bead_sections.extend(target.document.sections)
        else:
            bead_failures.append(
                resolution.unresolved_message or f"bead:{bead_id} could not be resolved"
            )
    reports = dict(report_items)
    artifact_read_refs = dict(artifact_read_ref_items)
    materialized: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    for file_path in files:
        spec = reports.get(file_path)
        if spec is None:
            resolved_path = file_path
        else:
            if isinstance(spec, MemoryReadReportSpec):
                requested_paths = memory_read_file_paths(spec.event)
                existing_paths = [
                    path for path in requested_paths if os.path.exists(path)
                ]
                if existing_paths:
                    for path in requested_paths:
                        if os.path.exists(path):
                            materialized.append(path)
                        else:
                            missing.append(path)
                    continue
                report_path = write_memory_read_report(spec)
            elif isinstance(spec, GlossaryReadReportSpec):
                report_path = write_glossary_read_report(spec)
            else:
                report_path = write_tool_call_report(spec)
            if report_path is None:
                failed.append(file_path)
                continue
            resolved_path = report_path
        if os.path.exists(resolved_path):
            materialized.append(resolved_path)
            continue
        ref_spec = artifact_read_refs.get(file_path)
        if ref_spec is not None:
            repaired_path = repair_artifact_read_path(ref_spec)
            if repaired_path is not None and os.path.exists(repaired_path):
                materialized.append(repaired_path)
                continue
        missing.append(resolved_path)
    return MaterializedReports(
        tuple(dict.fromkeys(materialized)),
        tuple(failed),
        tuple(missing),
        link_context,
        tuple(bead_sections),
        tuple(bead_failures),
    )
