"""Manifest coverage and intended-vs-observed section diff (E2 scoreboard).

Coverage matches each observed root session against the shadow manifests in
its run's ``<artifacts>/instructions/`` dir: a session is covered when the
run holds a manifest for the same execution provider with ``rendered_at``
no later than the session start (plus a small skew allowance for writer
clock ordering). agy has no observable sessions, so it is scored per run.

Section diff compares one session's loaded sources against its matching
manifest's included sections. Source texts are loaded only when a diff is
requested; the scoreboard path never holds them in memory.
"""

from __future__ import annotations

from sase.instructions.coverage_diff import (
    SectionDiff,
    SectionDiffRow,
    loaded_source_texts,
    section_diff_for_session,
)
from sase.instructions.coverage_records import (
    COVERAGE_SKEW,
    ManifestRecord,
    matching_manifests,
    record_from_entry,
    run_manifest_records,
)
from sase.instructions.coverage_sessions import (
    RootSession,
    claude_session_start,
    codex_session_start,
    grok_session_start,
    muse_session_start,
    parse_time,
    root_sessions,
)
from sase.instructions.coverage_summary import (
    MAX_UNCOVERED_PAIRS,
    AgyRunCoverage,
    PurposeCoverageRow,
    SessionCoverage,
    count_run_errors,
    cover_agy_runs,
    cover_sessions,
    coverage_label,
    provider_session_coverage,
    purpose_coverage_rows,
)

__all__ = [
    "COVERAGE_SKEW",
    "MAX_UNCOVERED_PAIRS",
    "AgyRunCoverage",
    "ManifestRecord",
    "PurposeCoverageRow",
    "RootSession",
    "SectionDiff",
    "SectionDiffRow",
    "SessionCoverage",
    "claude_session_start",
    "codex_session_start",
    "count_run_errors",
    "cover_agy_runs",
    "cover_sessions",
    "coverage_label",
    "grok_session_start",
    "loaded_source_texts",
    "matching_manifests",
    "muse_session_start",
    "parse_time",
    "provider_session_coverage",
    "purpose_coverage_rows",
    "record_from_entry",
    "root_sessions",
    "run_manifest_records",
    "section_diff_for_session",
]
