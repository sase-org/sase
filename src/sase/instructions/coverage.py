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

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.instructions import _runs as runs

#: Allowance for writer clock ordering between the shadow render and the
#: provider session start (plan: scoreboard coverage column).
COVERAGE_SKEW = timedelta(seconds=5)

#: Cap on uncovered ``(agent, session)`` pairs per ``-c`` row.
MAX_UNCOVERED_PAIRS = 10


def parse_time(value: object) -> datetime | None:
    """Parse an ISO timestamp or epoch to UTC, or ``None``."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first_json_timestamp(path: Path, *, max_lines: int = 10) -> datetime | None:
    """Return the first ``timestamp`` field in a JSONL file, or ``None``."""
    try:
        with open(path, encoding="utf-8") as stream:
            for _ in range(max_lines):
                line = stream.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for key in ("timestamp", "build_timestamp_utc"):
                    parsed = parse_time(event.get(key))
                    if parsed is not None:
                        return parsed
    except OSError:
        return None
    return None


def claude_session_start(session_path: Path) -> datetime | None:
    """Return a Claude root transcript's first event timestamp."""
    return _first_json_timestamp(session_path)


def codex_session_start(rollout_path: Path) -> datetime | None:
    """Return a Codex rollout's ``session_meta`` timestamp."""
    try:
        with open(rollout_path, encoding="utf-8") as stream:
            first = stream.readline()
    except OSError:
        return None
    try:
        event = json.loads(first)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    payload = event.get("payload")
    if isinstance(payload, dict):
        parsed = parse_time(payload.get("timestamp"))
        if parsed is not None:
            return parsed
    return _first_json_timestamp(rollout_path)


def grok_session_start(session_dir: Path) -> datetime | None:
    """Return a Grok session dir's build timestamp (mtime fallback)."""
    context = runs.read_json_object(session_dir / "prompt_context.json")
    parsed = parse_time(context.get("build_timestamp_utc"))
    if parsed is not None:
        return parsed
    try:
        return datetime.fromtimestamp(session_dir.stat().st_mtime, tz=UTC)
    except OSError:
        return None


def muse_session_start(log_path: Path) -> datetime | None:
    """Return a Muse session log's first timestamp (mtime fallback)."""
    found = _first_json_timestamp(log_path)
    if found is not None:
        return found
    try:
        return datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)
    except OSError:
        return None


@dataclass(frozen=True)
class RootSession:
    """One observable root session and its start."""

    provider: str
    run_name: str
    artifact_dir: str
    workspace_dir: str
    session_id: str
    session_start: datetime | None
    partial: bool = False


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


def root_sessions(scored_runs: list[runs.ScoredRun]) -> list[RootSession]:
    """List observable root sessions with starts for *scored_runs*."""
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    found: list[RootSession] = []
    for run in scored_runs:
        if run.provider == "claude":
            for path in runs.find_claude_sessions(run):
                found.append(
                    RootSession(
                        provider="claude",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=path.stem,
                        session_start=claude_session_start(path),
                    )
                )
        elif run.provider == "codex":
            for path in runs.find_codex_sessions(run):
                found.append(
                    RootSession(
                        provider="codex",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=path.stem,
                        session_start=codex_session_start(path),
                    )
                )
        elif run.provider == "grok":
            for directory in runs.find_grok_sessions(run):
                found.append(
                    RootSession(
                        provider="grok",
                        run_name=run.name,
                        artifact_dir=run.artifact_dir,
                        workspace_dir=run.workspace_dir,
                        session_id=directory.name,
                        session_start=grok_session_start(directory),
                    )
                )
        elif run.provider == "muse":
            session_id = runs.find_muse_session_id(run)
            if session_id is None:
                continue
            log_path = find_muse_session_log(session_id)
            found.append(
                RootSession(
                    provider="muse",
                    run_name=run.name,
                    artifact_dir=run.artifact_dir,
                    workspace_dir=run.workspace_dir,
                    session_id=session_id,
                    session_start=(
                        muse_session_start(log_path) if log_path is not None else None
                    ),
                )
            )
    return found


@dataclass(frozen=True)
class ManifestRecord:
    """One readable shadow manifest with its match fields."""

    artifact_dir: str
    seq: int
    provider: str
    purpose: str
    rendered_at: datetime | None
    render_ms: float | None
    cache: str | None
    manifest_path: str
    manifest: dict[str, Any] = field(compare=False)


def record_from_entry(entry: Any, artifact_dir: str | Path) -> ManifestRecord | None:
    """Return the match fields for one reader entry, or ``None``."""
    if entry.manifest is None:
        return None
    facts = entry.manifest.get("facts")
    provider = ""
    purpose = ""
    if isinstance(facts, dict):
        raw_provider = facts.get("provider")
        if isinstance(raw_provider, str):
            provider = raw_provider.lower()
        raw_purpose = facts.get("purpose")
        if isinstance(raw_purpose, str):
            purpose = raw_purpose
    delivery = entry.manifest.get("delivery")
    rendered: datetime | None = None
    render_ms: float | None = None
    cache: str | None = None
    if isinstance(delivery, dict):
        rendered = parse_time(delivery.get("rendered_at"))
        raw_ms = delivery.get("render_ms")
        if isinstance(raw_ms, (int, float)):
            render_ms = float(raw_ms)
        raw_cache = delivery.get("cache")
        if isinstance(raw_cache, str):
            cache = raw_cache
    manifest_path = getattr(entry, "manifest_path", None)
    return ManifestRecord(
        artifact_dir=str(artifact_dir),
        seq=entry.seq,
        provider=provider,
        purpose=purpose,
        rendered_at=rendered,
        render_ms=render_ms,
        cache=cache,
        manifest_path=str(manifest_path) if manifest_path else "",
        manifest=entry.manifest,
    )


def run_manifest_records(artifact_dir: str | Path) -> list[ManifestRecord]:
    """Return readable shadow manifests under *artifact_dir*."""
    from sase.instructions.manifests import read_run_manifests

    records: list[ManifestRecord] = []
    for entry in read_run_manifests(artifact_dir):
        record = record_from_entry(entry, artifact_dir)
        if record is not None:
            records.append(record)
    return records


def _rendered_covers(rendered: datetime | None, start: datetime | None) -> bool:
    """Return whether *rendered* precedes *start* within skew allowance."""
    if rendered is None or start is None:
        return False
    return rendered <= start + COVERAGE_SKEW


def matching_manifests(
    session: RootSession, records: list[ManifestRecord]
) -> list[ManifestRecord]:
    """Return same-provider manifests covering *session*, latest first."""
    matches = [
        record
        for record in records
        if record.provider == session.provider
        and _rendered_covers(record.rendered_at, session.session_start)
    ]
    matches.sort(
        key=lambda record: record.rendered_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return matches


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


def _strip_heading(section_text: str) -> str:
    """Return *section_text* without its first (heading) line."""
    _, _, rest = section_text.partition("\n")
    return rest


def _bundle_section_text(
    artifact_dir: str, record: ManifestRecord, *, bundle_text: str | None = None
) -> dict[str, str]:
    """Map included section id to body text from the run bundle file."""
    from sase.instructions.manifests import read_run_manifests

    texts: dict[str, str] = {}
    if bundle_text is None:
        for entry in read_run_manifests(artifact_dir):
            if entry.manifest is None or entry.bundle_path is None:
                continue
            facts = entry.manifest.get("facts")
            provider = ""
            if isinstance(facts, dict) and isinstance(facts.get("provider"), str):
                provider = str(facts["provider"]).lower()
            if provider != record.provider or entry.seq != record.seq:
                continue
            try:
                bundle_text = entry.bundle_path.read_text(encoding="utf-8")
            except OSError:
                return {}
            break
    if bundle_text is None:
        return {}
    sections = record.manifest.get("sections")
    if not isinstance(sections, list):
        return {}
    blob = bundle_text.encode("utf-8")
    for section in sections:
        if not isinstance(section, dict) or section.get("status") != "included":
            continue
        section_id = section.get("id")
        offset = section.get("offset")
        length = section.get("length")
        if (
            not isinstance(section_id, str)
            or not isinstance(offset, int)
            or not isinstance(length, int)
        ):
            continue
        try:
            texts[section_id] = blob[offset : offset + length].decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
    return texts


def loaded_source_texts(
    provider: str, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    """Return ``(native, explicit)`` loaded source texts for one session.

    Session files are read only when a diff is requested; the plain
    scoreboard path never calls this.
    """
    from sase.instructions import claude as claude_parser
    from sase.instructions import codex as codex_parser
    from sase.instructions import grok as grok_parser
    from sase.instructions import muse as muse_parser
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    if provider == "claude":
        return _claude_texts(claude_parser, run, session_id)
    if provider == "codex":
        return _codex_texts(codex_parser, run, session_id)
    if provider == "grok":
        return _grok_texts(grok_parser, run, session_id)
    if provider == "muse":
        return _muse_texts(muse_parser, find_muse_session_log, session_id)
    return [], []


def _claude_texts(
    claude_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    candidate = runs.claude_project_dir(run.workspace_dir) / f"{session_id}.jsonl"
    records: list[dict[str, Any]] = []
    if candidate.is_file():
        records, _ = runs.read_jsonl_capped(
            candidate, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
    files = claude_parser.instruction_files(records)
    native = [entry["content"] for entry in files]
    snapshot = claude_parser.system_prompt_text(records)
    return native, [snapshot] if snapshot else []


def _codex_texts(
    codex_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    records: list[dict[str, Any]] = []
    for path in runs.find_codex_sessions(run):
        if path.stem == session_id:
            records, _ = runs.read_jsonl_capped(
                path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
            )
            break
    native = codex_parser.block_sources(codex_parser.agents_blocks(records))
    explicit = codex_parser.developer_texts(records)
    return native, explicit


def _grok_texts(
    grok_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    session_dir: Path | None = None
    for child in runs.find_grok_sessions(run):
        if child.name == session_id:
            session_dir = child
            break
    if session_dir is None:
        return [], []
    context = runs.read_json_object(session_dir / "prompt_context.json")
    system_prompt, _ = runs.read_text_capped(
        session_dir / "system_prompt.txt", max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
    )
    native: list[str] = []
    raw_agents = context.get("agents_md_files", [])
    if isinstance(raw_agents, list):
        for entry in raw_agents:
            if isinstance(entry, dict) and isinstance(entry.get("content"), str):
                native.append(str(entry["content"]))
            elif isinstance(entry, str):
                native.append(entry)
    rules = grok_parser.human_rules_block(system_prompt)
    return native, [rules] if rules else []


def _muse_texts(
    muse_parser: Any, find_log: Any, session_id: str
) -> tuple[list[str], list[str]]:
    log_path = find_log(session_id)
    if log_path is None:
        return [], []
    records, _ = runs.read_jsonl_capped(
        log_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
    )
    native = muse_parser.rules_texts(records)
    explicit = muse_parser.prompt_texts(records)
    return native, explicit


@dataclass(frozen=True)
class SectionDiffRow:
    """One intended-vs-observed section row."""

    id: str
    layer: str
    observed: int
    native: int
    explicit: int


@dataclass(frozen=True)
class SectionDiff:
    """Intended-vs-observed diff for one session and manifest."""

    session_id: str
    run_name: str
    manifest_path: str | None
    purpose: str | None
    unavailable: bool
    rows: tuple[SectionDiffRow, ...] = ()


def section_diff_for_session(
    session: RootSession,
    run: runs.ScoredRun,
    records: list[ManifestRecord],
    *,
    partial: bool = False,
    bundle_text: str | None = None,
) -> SectionDiff:
    """Diff *session*'s loaded sources against its matching manifest."""
    from sase.instructions import fingerprints as fp

    matches = matching_manifests(session, records)
    if session.provider == "agy" or not matches:
        return SectionDiff(
            session_id=session.session_id,
            run_name=session.run_name,
            manifest_path=None,
            purpose=None,
            unavailable=True,
        )
    record = matches[0]
    section_texts = _bundle_section_text(
        session.artifact_dir, record, bundle_text=bundle_text
    )
    native, explicit = loaded_source_texts(session.provider, run, session.session_id)
    flat_native = [fp.flatten_ws(text) for text in native]
    flat_explicit = [fp.flatten_ws(text) for text in explicit]
    sections = record.manifest.get("sections")
    layer_by_id: dict[str, str] = {}
    if isinstance(sections, list):
        for section in sections:
            if (
                isinstance(section, dict)
                and isinstance(section.get("id"), str)
                and isinstance(section.get("layer"), str)
            ):
                layer_by_id[str(section["id"])] = str(section["layer"])
    rows: list[SectionDiffRow] = []
    for section_id, body in sorted(section_texts.items()):
        layer = layer_by_id.get(section_id, "")
        if layer == "frame":
            continue
        flat_body = fp.flatten_ws(_strip_heading(body)).strip()
        if not flat_body:
            continue
        native_hits = sum(1 for text in flat_native if flat_body in text)
        explicit_hits = sum(1 for text in flat_explicit if flat_body in text)
        rows.append(
            SectionDiffRow(
                id=section_id,
                layer=layer,
                observed=0 if partial else native_hits + explicit_hits,
                native=0 if partial else native_hits,
                explicit=0 if partial else explicit_hits,
            )
        )
    return SectionDiff(
        session_id=session.session_id,
        run_name=session.run_name,
        manifest_path=record.manifest_path or None,
        purpose=record.purpose or None,
        unavailable=partial,
        rows=tuple(rows),
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
