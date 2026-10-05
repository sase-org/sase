"""Collect per-session observations and aggregate provider rows."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sase.instructions import _runs as runs
from sase.instructions import claude as claude_parser
from sase.instructions import fingerprints as fp
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport
from sase.instructions import codex as codex_parser
from sase.instructions import grok as grok_parser
from sase.instructions import muse as muse_parser


def _tri(value: bool | None) -> str:
    if value is True:
        return "✓"
    if value is False:
        return "✗"
    return "◌"


def _modal_contract(counts: list[int]) -> str:
    if not counts:
        return "0"
    tally = Counter(counts)
    modal, _ = tally.most_common(1)[0]
    if len(tally) == 1:
        return f"{modal}×" if modal != 0 else "0"
    spread = ",".join(str(value) for value in sorted(tally))
    return f"{modal}× [{spread}]"


def collect_observations(
    scored_runs: list[runs.ScoredRun],
) -> list[SessionObservation]:
    """Collect one observation per provider session."""
    observations: list[SessionObservation] = []
    home = runs.home_h1()
    for run in scored_runs:
        project = runs.project_h1(run.workspace_dir)
        if run.provider == "claude":
            observations.extend(_observe_claude(run, home, project))
        elif run.provider == "codex":
            observations.extend(_observe_codex(run, home, project))
        elif run.provider == "grok":
            observations.extend(_observe_grok(run, project))
        elif run.provider == "muse":
            observations.extend(_observe_muse(run, home, project))
        elif run.provider == "agy":
            observations.append(
                SessionObservation(
                    provider="agy",
                    run_name=run.name,
                    session_id=run.artifact_dir,
                    contract_count=0,
                    home=False,
                    project=None,
                    directive=None,
                    native_full_count=0,
                    foreign=None,
                )
            )
    return observations


def _observe_claude(
    run: runs.ScoredRun, home: str | None, project: str | None
) -> list[SessionObservation]:
    observations: list[SessionObservation] = []
    sessions = runs.find_claude_sessions(run)
    if not sessions:
        return [
            SessionObservation(
                provider="claude",
                run_name=run.name,
                session_id="unobserved",
                contract_count=0,
                home=None,
                project=None,
                directive=None,
                native_full_count=0,
            )
        ]
    for session_path in sessions:
        records, partial = runs.read_jsonl_capped(
            session_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
        fields = claude_parser.observe_claude_session(
            records, home_h1=home, project_h1=project
        )
        helpers = runs.find_claude_helpers(session_path)
        observations.append(
            SessionObservation(
                provider="claude",
                run_name=run.name,
                session_id=session_path.stem,
                contract_count=int(fields["contract_count"]),
                home=_as_tri(fields["home"]),
                project=_as_tri(fields["project"]),
                directive=_as_tri(fields["directive"]),
                native_full_count=int(fields["native_full_count"]),
                foreign=_as_str(fields["foreign"]),
                helper_type=None,
                has_helper_template=bool(fields["has_helper_template"]),
                final_attempts=int(fields["final_attempts"]),
                final_denied=int(fields["final_denied"]),
                final_accepted=int(fields["final_accepted"]),
                partial=partial,
            )
        )
        for helper_path, agent_type in helpers:
            observations.extend(
                _observe_claude_helper(run, session_path.stem, helper_path, agent_type)
            )
    return observations


def _observe_claude_helper(
    run: runs.ScoredRun, session_id: str, helper_path: Path, agent_type: str
) -> list[SessionObservation]:
    records, partial = runs.read_jsonl_capped(
        helper_path, max_bytes=runs.HELPER_TRANSCRIPT_BYTE_CAP
    )
    signals = claude_parser.helper_signals(records)
    files = claude_parser.instruction_files(records)
    contract = fp.count_contract_sources([entry["content"] for entry in files])
    return [
        SessionObservation(
            provider="claude",
            run_name=run.name,
            session_id=f"{session_id}/{helper_path.stem}",
            contract_count=contract,
            home=None,
            project=None,
            directive=None,
            native_full_count=contract,
            foreign=None,
            helper_type=agent_type,
            has_helper_template=bool(signals["has_template"]),
            final_attempts=int(signals["attempts"]),
            final_denied=int(signals["denied"]),
            final_accepted=int(signals["accepted"]),
            partial=partial,
        )
    ]


def _observe_codex(
    run: runs.ScoredRun, home: str | None, project: str | None
) -> list[SessionObservation]:
    sessions = runs.find_codex_sessions(run)
    if not sessions:
        return [
            SessionObservation(
                provider="codex",
                run_name=run.name,
                session_id="unobserved",
                contract_count=0,
                home=None,
                project=None,
                directive=None,
                native_full_count=0,
            )
        ]
    observations: list[SessionObservation] = []
    for session_path in sessions:
        records, partial = runs.read_jsonl_capped(
            session_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
        fields = codex_parser.observe_codex_session(
            records, home_h1=home, project_h1=project
        )
        observations.append(
            SessionObservation(
                provider="codex",
                run_name=run.name,
                session_id=session_path.stem,
                contract_count=int(fields["contract_count"]),
                home=_as_tri(fields["home"]),
                project=_as_tri(fields["project"]),
                directive=_as_tri(fields["directive"]),
                native_full_count=int(fields["native_full_count"]),
                partial=partial,
            )
        )
    return observations


def _observe_grok(run: runs.ScoredRun, project: str | None) -> list[SessionObservation]:
    sessions = runs.find_grok_sessions(run)
    if not sessions:
        return [
            SessionObservation(
                provider="grok",
                run_name=run.name,
                session_id="unobserved",
                contract_count=0,
                home=False,
                project=False,
                directive=False,
                native_full_count=0,
            )
        ]
    observations: list[SessionObservation] = []
    for session_dir in sessions:
        context = runs.read_json_object(session_dir / "prompt_context.json")
        system_prompt, _ = runs.read_text_capped(
            session_dir / "system_prompt.txt", max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
        fields = grok_parser.observe_grok_session(
            context, system_prompt, project_h1=project
        )
        observations.append(
            SessionObservation(
                provider="grok",
                run_name=run.name,
                session_id=session_dir.name,
                contract_count=int(fields["contract_count"]),
                home=_as_tri(fields["home"]),
                project=_as_tri(fields["project"]),
                directive=_as_tri(fields["directive"]),
                native_full_count=int(fields["native_full_count"]),
                foreign=_as_str(fields["foreign"]),
                partial=False,
            )
        )
    return observations


def _observe_muse(
    run: runs.ScoredRun, home: str | None, project: str | None
) -> list[SessionObservation]:
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    session_id = runs.find_muse_session_id(run)
    if not session_id:
        return [
            SessionObservation(
                provider="muse",
                run_name=run.name,
                session_id="unobserved",
                contract_count=0,
                home=False,
                project=None,
                directive=None,
                native_full_count=0,
            )
        ]
    log_path = find_muse_session_log(session_id)
    if log_path is None:
        return [
            SessionObservation(
                provider="muse",
                run_name=run.name,
                session_id=session_id,
                contract_count=0,
                home=False,
                project=None,
                directive=None,
                native_full_count=0,
            )
        ]
    records, partial = runs.read_jsonl_capped(
        log_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
    )
    fields = muse_parser.observe_muse_session(records, home_h1=home, project_h1=project)
    return [
        SessionObservation(
            provider="muse",
            run_name=run.name,
            session_id=session_id,
            contract_count=int(fields["contract_count"]),
            home=_as_tri(fields["home"]),
            project=_as_tri(fields["project"]),
            directive=_as_tri(fields["directive"]),
            native_full_count=int(fields["native_full_count"]),
            partial=partial,
        )
    ]


def aggregate_rows(
    observations: list[SessionObservation],
    scored_runs: list[runs.ScoredRun],
) -> list[ProviderRow]:
    """Aggregate observations into one row per provider."""
    order = ("claude", "codex", "muse", "grok", "agy")
    by_provider: dict[str, list[SessionObservation]] = {name: [] for name in order}
    for obs in observations:
        by_provider.setdefault(obs.provider, []).append(obs)
    runs_by_provider: dict[str, int] = {}
    for run in scored_runs:
        runs_by_provider[run.provider] = runs_by_provider.get(run.provider, 0) + 1
    rows: list[ProviderRow] = []
    for provider in order:
        obs_list = [
            o for o in by_provider.get(provider, []) if o.session_id != "unobserved"
        ]
        if not obs_list and provider not in runs_by_provider:
            continue
        rows.append(
            _aggregate_provider(provider, obs_list, runs_by_provider.get(provider, 0))
        )
    # Keep providers with unobserved runs so the table names the gap.
    for provider in order:
        if provider in runs_by_provider and not any(
            r.provider == provider for r in rows
        ):
            rows.append(
                ProviderRow(
                    provider=provider,
                    runs=runs_by_provider[provider],
                    sessions=0,
                )
            )
    return rows


def _aggregate_provider(
    provider: str, obs_list: list[SessionObservation], run_count: int
) -> ProviderRow:
    if not obs_list:
        return ProviderRow(provider=provider, runs=run_count, sessions=0)
    # Root sessions carry the delivery columns; helper observations feed
    # only the helpers column.
    root_obs = [o for o in obs_list if o.helper_type is None] or obs_list
    contract = _modal_contract([o.contract_count for o in root_obs])
    home = _tri(_mode_tri([o.home for o in root_obs]))
    project = _tri(_mode_tri([o.project for o in root_obs]))
    directive = _tri(_mode_tri([o.directive for o in root_obs]))
    native_counts = [o.native_full_count for o in root_obs]
    native = _modal_contract(native_counts) if any(native_counts) else "0"
    if provider == "agy":
        native = "◌"
        contract = "◌"
    foreign = _foreign_label(provider, obs_list)
    helpers = _helpers_label(provider, obs_list)
    denials = sum(1 for o in obs_list if o.root_guard_denial)
    return ProviderRow(
        provider=provider,
        runs=run_count,
        sessions=len(obs_list),
        contract=contract,
        home=home,
        project=project,
        directive=directive,
        native_full=native,
        foreign=foreign,
        helpers=helpers,
        root_denials=denials,
    )


def _mode_tri(values: list[bool | None]) -> bool | None:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return (
        True if sum(1 for v in known if v) >= sum(1 for v in known if not v) else False
    )


def _foreign_label(provider: str, obs_list: list[SessionObservation]) -> str:
    foreigns = [o.foreign for o in obs_list if o.foreign]
    if provider == "claude":
        return "auto-memory" if foreigns else "—"
    if provider == "grok":
        return foreigns[0] if foreigns else "—"
    return "—"


def _helpers_label(provider: str, obs_list: list[SessionObservation]) -> str:
    helper_obs = [o for o in obs_list if o.helper_type]
    if provider == "agy":
        return "—"
    if not helper_obs:
        return (
            "0 spawns" if provider == "codex" else ("—" if provider == "muse" else "—")
        )
    attempts = sum(o.final_attempts for o in helper_obs)
    accepted = sum(o.final_accepted for o in helper_obs)
    types = sorted({str(o.helper_type) for o in helper_obs})
    if provider == "claude":
        return f"{','.join(types)}: {attempts} attempts, {accepted} accepted"
    return f"{len(helper_obs)} helpers"


def _as_tri(value: object) -> bool | None:
    return value if isinstance(value, bool) or value is None else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def build_report(
    scored_runs: list[runs.ScoredRun],
    observations: list[SessionObservation],
    *,
    filters: dict[str, object],
) -> VerifyReport:
    """Build a ``VerifyReport`` from runs and observations."""
    rows = aggregate_rows(observations, scored_runs)
    return VerifyReport(
        provider_rows=tuple(rows),
        observations=tuple(observations),
        filters=dict(filters),
        generated_at=datetime.now(tz=UTC).isoformat(),
    )


__all__ = [
    "aggregate_rows",
    "build_report",
    "collect_observations",
]
