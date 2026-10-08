"""Per-session and per-purpose coverage scoring."""

from __future__ import annotations

from dataclasses import dataclass

from sase.instructions import run_index as runs
from sase.instructions.coverage_records import ManifestRecord, matching_manifests
from sase.instructions.coverage_sessions import RootSession

#: Cap on uncovered ``(agent, session)`` pairs per ``-c`` row.
MAX_UNCOVERED_PAIRS = 10


@dataclass(frozen=True)
class AgyRunCoverage:
    """Manifest coverage verdict for one agy run (no observable sessions)."""

    run_name: str
    artifact_dir: str
    covered: bool


def cover_agy_runs(
    scored_runs: list[runs.ScoredRun], records: list[ManifestRecord]
) -> list[AgyRunCoverage]:
    """Score each agy run covered when it holds at least one agy manifest."""
    verdicts: list[AgyRunCoverage] = []
    for run in scored_runs:
        if run.provider != "agy":
            continue
        covered = any(
            record.artifact_dir == run.artifact_dir and record.provider == "agy"
            for record in records
        )
        verdicts.append(
            AgyRunCoverage(
                run_name=run.name,
                artifact_dir=run.artifact_dir,
                covered=covered,
            )
        )
    return verdicts


@dataclass(frozen=True)
class SessionCoverage:
    """Coverage verdict for one observed root session."""

    provider: str
    run_name: str
    session_id: str
    covered: bool
    purpose: str | None = None
    manifest_seq: int | None = None


def cover_sessions(
    sessions: list[RootSession], records: list[ManifestRecord]
) -> list[SessionCoverage]:
    """Match each session against its run's manifests."""
    by_run: dict[str, list[ManifestRecord]] = {}
    for record in records:
        by_run.setdefault(record.artifact_dir, []).append(record)
    verdicts: list[SessionCoverage] = []
    for session in sessions:
        matches = matching_manifests(session, by_run.get(session.artifact_dir, []))
        if matches:
            verdicts.append(
                SessionCoverage(
                    provider=session.provider,
                    run_name=session.run_name,
                    session_id=session.session_id,
                    covered=True,
                    purpose=matches[0].purpose or None,
                    manifest_seq=matches[0].seq,
                )
            )
        else:
            verdicts.append(
                SessionCoverage(
                    provider=session.provider,
                    run_name=session.run_name,
                    session_id=session.session_id,
                    covered=False,
                )
            )
    return verdicts


def coverage_label(covered: int, total: int) -> str:
    """Return the ``k/N`` manifest coverage label."""
    return f"{covered}/{total}"


def provider_session_coverage(
    provider: str,
    sessions: list[RootSession],
    verdicts: list[SessionCoverage],
) -> tuple[int, int]:
    """Return ``(covered, total)`` root sessions for *provider*."""
    wanted = {
        (item.run_name, item.session_id)
        for item in sessions
        if item.provider == provider
    }
    total = len(wanted)
    covered = sum(
        1
        for item in verdicts
        if item.provider == provider
        and (item.run_name, item.session_id) in wanted
        and item.covered
    )
    return covered, total


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = pct / 100.0 * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


@dataclass(frozen=True)
class PurposeCoverageRow:
    """One ``-c`` coverage row for a provider and manifest purpose."""

    provider: str
    purpose: str
    manifests: int
    sessions: int
    covered: int
    uncovered: tuple[tuple[str, str], ...] = ()
    errors: int = 0
    warm_p50: float | None = None
    warm_p95: float | None = None
    cold_p50: float | None = None
    cold_p95: float | None = None


def purpose_coverage_rows(
    sessions: list[RootSession],
    records: list[ManifestRecord],
    *,
    error_counts: dict[str, int] | None = None,
) -> list[PurposeCoverageRow]:
    """Build per-provider-purpose ``-c`` rows with latency stats."""
    by_provider_sessions: dict[str, list[RootSession]] = {}
    for session in sessions:
        by_provider_sessions.setdefault(session.provider, []).append(session)
    by_provider_records: dict[str, list[ManifestRecord]] = {}
    for record in records:
        by_provider_records.setdefault(record.provider, []).append(record)
    rows: list[PurposeCoverageRow] = []
    providers = sorted(set(by_provider_sessions) | set(by_provider_records))
    for provider in providers:
        provider_sessions = by_provider_sessions.get(provider, [])
        provider_records = by_provider_records.get(provider, [])
        purposes = sorted({record.purpose for record in provider_records})
        if not purposes:
            purposes = [""]
        by_session_covered: dict[tuple[str, str], set[str]] = {}
        for session in provider_sessions:
            key = (session.run_name, session.session_id)
            covered_purposes = {
                record.purpose
                for record in matching_manifests(
                    session,
                    [
                        record
                        for record in provider_records
                        if record.artifact_dir == session.artifact_dir
                    ],
                )
            }
            by_session_covered[key] = covered_purposes
        for purpose in purposes:
            purpose_records = [
                record for record in provider_records if record.purpose == purpose
            ]
            covered_keys = {
                key
                for key, covered_purposes in by_session_covered.items()
                if purpose in covered_purposes
            }
            uncovered = sorted(
                key for key in by_session_covered if key not in covered_keys
            )[:MAX_UNCOVERED_PAIRS]
            warm = sorted(
                record.render_ms
                for record in purpose_records
                if record.render_ms is not None and record.cache == "hit"
            )
            cold = sorted(
                record.render_ms
                for record in purpose_records
                if record.render_ms is not None and record.cache != "hit"
            )
            rows.append(
                PurposeCoverageRow(
                    provider=provider,
                    purpose=purpose or "—",
                    manifests=len(purpose_records),
                    sessions=len(provider_sessions),
                    covered=len(covered_keys),
                    uncovered=tuple(uncovered),
                    errors=(error_counts or {}).get(provider, 0),
                    warm_p50=_percentile(warm, 50),
                    warm_p95=_percentile(warm, 95),
                    cold_p50=_percentile(cold, 50),
                    cold_p95=_percentile(cold, 95),
                )
            )
    return rows


def count_run_errors(scored_runs: list[runs.ScoredRun]) -> dict[str, int]:
    """Count ``.error.json`` shadow failures per provider over *scored_runs*."""
    from sase.instructions.manifests import read_run_manifests

    counts: dict[str, int] = {}
    for run in scored_runs:
        for entry in read_run_manifests(run.artifact_dir):
            if entry.error is not None:
                counts[run.provider] = counts.get(run.provider, 0) + 1
    return counts


__all__ = [
    "MAX_UNCOVERED_PAIRS",
    "AgyRunCoverage",
    "PurposeCoverageRow",
    "SessionCoverage",
    "count_run_errors",
    "cover_agy_runs",
    "cover_sessions",
    "coverage_label",
    "provider_session_coverage",
    "purpose_coverage_rows",
]
