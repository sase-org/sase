"""Collect per-session observations and aggregate provider rows."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sase.instructions import run_index as runs
from sase.instructions import claude as claude_parser
from sase.instructions import fingerprints as fp
from sase.instructions.models import ProviderRow, SessionObservation, VerifyReport
from typing import Any
from sase.instructions import codex as codex_parser
from sase.instructions import grok as grok_parser
from sase.instructions import muse as muse_parser


def _tri(value: bool | None) -> str:
    if value is True:
        return "✓"
    if value is False:
        return "✗"
    return "◌"


def _modal_contract(counts: list[int | None]) -> str:
    known = [value for value in counts if isinstance(value, int)]
    if not known:
        return "◌" if counts else "0"
    tally = Counter(known)
    modal, _ = tally.most_common(1)[0]
    if len(tally) == 1:
        return f"{modal}×" if modal != 0 else "0"
    spread = ",".join(str(value) for value in sorted(tally))
    return f"{modal}× [{spread}]"


def _channel_map(fields: dict[str, Any]) -> dict[str, dict[str, int | bool | None]]:
    """Return the per-column native/explicit breakdown for one session."""
    return {
        "contract": {
            "native": fields.get("contract_native", 0),
            "explicit": fields.get("contract_explicit", 0),
        },
        "home": {
            "native": fields.get("home_native"),
            "explicit": fields.get("home_explicit"),
        },
        "project": {
            "native": fields.get("project_native"),
            "explicit": fields.get("project_explicit"),
        },
        "directive": {
            "native": fields.get("directive_native"),
            "explicit": fields.get("directive_explicit"),
        },
    }


def _partial_tri(value: object, partial: bool) -> bool | None:
    """Keep positive evidence from a prefix and mark missing evidence unknown."""
    if not isinstance(value, bool):
        return None
    return None if partial and not value else value


def _observed_count(value: object, partial: bool) -> int | None:
    if not isinstance(value, int):
        return None
    return None if partial and value == 0 else value


def _tri_or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


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
    return _enrich_delivery_columns(observations, scored_runs)


def _enrich_delivery_columns(
    observations: list[SessionObservation], scored_runs: list[runs.ScoredRun]
) -> list[SessionObservation]:
    """Associate transcripts with manifests and score exact bundle markers."""
    from sase.instructions.coverage_records import (
        delivery_label,
        matching_manifests,
        manifest_layer_included,
        run_manifest_records,
    )
    from sase.instructions.coverage_sessions import root_sessions

    sessions = root_sessions(scored_runs)
    by_run_records = {
        run.artifact_dir: run_manifest_records(run.artifact_dir) for run in scored_runs
    }
    observation_index = {
        (item.run_name, item.provider, item.session_id): index
        for index, item in enumerate(observations)
        if item.helper_type is None
    }
    enriched = list(observations)
    matched_roots: list[tuple[Any, Any, int]] = []
    for session in sessions:
        index = observation_index.get(
            (session.run_name, session.provider, session.session_id)
        )
        if index is None:
            continue
        records = by_run_records.get(session.artifact_dir, [])
        matches = matching_manifests(session, records)
        if not matches:
            continue
        record = matches[0]
        item = enriched[index]
        bundle_count: int | None = None
        if record.delivery_status == "explicit" and record.invocation_id:
            found = fp.count_bundle_markers(
                session.bundle_markers, record.invocation_id
            )
            bundle_count = None if session.partial and found == 0 else found
        channels = {name: dict(values) for name, values in item.channels.items()}
        home_native = _as_tri(channels.get("home", {}).get("native"))
        project_native = _as_tri(channels.get("project", {}).get("native"))
        home_explicit = _as_tri(channels.get("home", {}).get("explicit"))
        project_explicit = _as_tri(channels.get("project", {}).get("explicit"))
        if record.delivery_status == "explicit":
            visible = bundle_count is not None and bundle_count > 0
            home_explicit = (
                manifest_layer_included(record, "home")
                if visible
                else (None if session.partial else False)
            )
            project_explicit = (
                manifest_layer_included(record, "project")
                if visible
                else (None if session.partial else False)
            )
            channels.setdefault("home", {})["explicit"] = home_explicit
            channels.setdefault("project", {})["explicit"] = project_explicit
        enriched[index] = replace(
            item,
            home=(
                _tri_or(home_native, home_explicit)
                if home_native is not None or home_explicit is not None
                else item.home
            ),
            project=(
                _tri_or(project_native, project_explicit)
                if project_native is not None or project_explicit is not None
                else item.project
            ),
            channels=channels,
            bundle_count=bundle_count,
            delivery=delivery_label(record),
            home_expected=(
                manifest_layer_included(record, "home")
                if record.delivery_status == "explicit"
                else None
            ),
            bundle_markers=session.bundle_markers,
        )
        matched_roots.append((session, record, index))

    # Claude helper prompts use the helper sha and the root invocation id.
    for session, record, _root_index in matched_roots:
        if session.provider != "claude" or not record.invocation_id:
            continue
        delivery = record.manifest.get("delivery")
        subagent = delivery.get("subagent") if isinstance(delivery, dict) else None
        if not isinstance(subagent, dict) or subagent.get("status") != "explicit":
            continue
        helper_sha = subagent.get("bundle_sha256")
        if not isinstance(helper_sha, str):
            helper_sha = None
        for index, helper in enumerate(enriched):
            if (
                helper.provider != "claude"
                or helper.run_name != session.run_name
                or helper.helper_type is None
                or not helper.session_id.startswith(f"{session.session_id}/")
            ):
                continue
            helper_bundle_count = (
                fp.count_bundle_markers(
                    helper.bundle_markers,
                    record.invocation_id,
                    bundle_sha256=helper_sha,
                )
                if helper_sha
                else 0
            )
            root_bundle_count = fp.count_bundle_markers(
                helper.bundle_markers,
                record.invocation_id,
                bundle_sha256=record.bundle_sha256,
            )
            enriched[index] = replace(
                helper,
                helper_bundle=helper_bundle_count > 0,
                root_bundle_in_helper=root_bundle_count,
            )
    return enriched


def _root_guard_denial(
    session_path: Path,
    records: list[dict[str, Any]],
    partial: bool,
) -> tuple[bool, bool]:
    """Return ``(denied, partial)`` for a root Claude transcript.

    The capped ``records`` cover the first 512 KiB; a denial can arrive much
    later, so fall back to a cheap streaming pass bounded by the helper cap.
    That pass JSON-decodes only lines holding the guard prefix or a tool-use
    pairing id. An Agent-tool hand-back quoting the guard text never counts
    because it is not a Bash or Skill result.
    """
    if claude_parser.has_guard_denial(records):
        return True, partial
    try:
        size = session_path.stat().st_size
    except OSError:
        return False, partial
    if size <= runs.ROOT_TRANSCRIPT_BYTE_CAP:
        return False, partial
    denied, hit_cap = _streaming_guard_denial(
        session_path, max_bytes=runs.HELPER_TRANSCRIPT_BYTE_CAP
    )
    return denied, (partial or hit_cap)


def _streaming_guard_denial(session_path: Path, *, max_bytes: int) -> tuple[bool, bool]:
    """Scan a root transcript for a paired guard denial within *max_bytes*."""
    import json

    kinds: dict[str, bool] = {}
    pending: list[tuple[str, bool, str]] = []
    used = 0
    hit_cap = False
    try:
        size = session_path.stat().st_size
    except OSError:
        return False, False
    if size > max_bytes:
        hit_cap = True
    try:
        with open(session_path, encoding="utf-8") as stream:
            for line in stream:
                encoded = len(line.encode("utf-8"))
                if used + encoded > max_bytes:
                    hit_cap = True
                    break
                used += encoded
                if fp.GUARD_DENY_REASON_PREFIX not in line and "tool_use" not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = record.get("type")
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                if record_type == "assistant":
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue
                        raw_id = block.get("id")
                        use_id = (
                            str(raw_id) if isinstance(raw_id, str) and raw_id else None
                        )
                        if use_id is None:
                            raw_alt = block.get("tool_use_id")
                            if isinstance(raw_alt, str) and raw_alt:
                                use_id = raw_alt
                        if use_id is None:
                            continue
                        name = block.get("name")
                        kinds[str(use_id)] = name in ("Bash", "Skill")
                elif record_type == "user":
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_result":
                            continue
                        if block.get("is_error") is not True:
                            continue
                        raw_id = block.get("tool_use_id")
                        use_id = (
                            str(raw_id) if isinstance(raw_id, str) and raw_id else None
                        )
                        if use_id is None:
                            continue
                        body = block.get("content")
                        texts: list[str] = []
                        if isinstance(body, str):
                            texts = [body]
                        elif isinstance(body, list):
                            for item in body:
                                if isinstance(item, str):
                                    texts.append(item)
                                elif isinstance(item, dict) and isinstance(
                                    item.get("text"), str
                                ):
                                    texts.append(str(item["text"]))
                        for text in texts:
                            if fp.GUARD_DENY_REASON_PREFIX in text:
                                pending.append((str(use_id), True, text))
    except OSError:
        return False, hit_cap
    for use_id, _is_error, text in pending:
        _ = text
        if kinds.get(use_id) is True:
            return True, hit_cap
    # A denial whose tool_use sits beyond the cap stays unknown; the caller
    # keeps the observation partial so the gap is visible.
    return False, hit_cap


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
        root_denial, partial = _root_guard_denial(session_path, records, partial)
        helpers = runs.find_claude_helpers(session_path)
        observations.append(
            SessionObservation(
                provider="claude",
                run_name=run.name,
                session_id=session_path.stem,
                contract_count=_observed_count(fields["contract_count"], partial),
                home=_partial_tri(fields["home"], partial),
                project=_partial_tri(fields["project"], partial),
                directive=_partial_tri(fields["directive"], partial),
                native_full_count=_observed_count(fields["native_full_count"], partial),
                foreign=_as_str(fields["foreign"]),
                helper_type=None,
                has_helper_template=bool(fields["has_helper_template"]),
                final_attempts=int(fields["final_attempts"]),
                final_denied=int(fields["final_denied"]),
                final_accepted=int(fields["final_accepted"]),
                root_guard_denial=root_denial,
                partial=partial,
                channels=_channel_map(fields),
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
    native, explicit = claude_parser.instruction_sources(records)
    contract_native = fp.count_contract_occurrences(native)
    contract_explicit = fp.count_contract_occurrences(explicit)
    markers = fp.bundle_markers(explicit)
    return [
        SessionObservation(
            provider="claude",
            run_name=run.name,
            session_id=f"{session_id}/{helper_path.stem}",
            contract_count=_observed_count(
                contract_native + contract_explicit, partial
            ),
            home=None,
            project=None,
            directive=None,
            native_full_count=_observed_count(contract_native, partial),
            foreign=None,
            helper_type=agent_type,
            has_helper_template=bool(signals["has_template"]),
            final_attempts=int(signals["attempts"]),
            final_denied=int(signals["denied"]),
            final_accepted=int(signals["accepted"]),
            partial=partial,
            channels={
                "contract": {
                    "native": contract_native,
                    "explicit": contract_explicit,
                }
            },
            bundle_markers=markers,
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
                contract_count=_observed_count(fields["contract_count"], partial),
                home=_partial_tri(fields["home"], partial),
                project=_partial_tri(fields["project"], partial),
                directive=_partial_tri(fields["directive"], partial),
                native_full_count=_observed_count(fields["native_full_count"], partial),
                foreign=_as_str(fields["foreign"]),
                partial=partial,
                channels=_channel_map(fields),
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
        system_prompt, partial = runs.read_text_capped(
            session_dir / "system_prompt.txt", max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
        fields = grok_parser.observe_grok_session(
            context, system_prompt, home_h1=runs.home_h1(), project_h1=project
        )
        observations.append(
            SessionObservation(
                provider="grok",
                run_name=run.name,
                session_id=session_dir.name,
                contract_count=_observed_count(fields["contract_count"], partial),
                home=_partial_tri(fields["home"], partial),
                project=_partial_tri(fields["project"], partial),
                directive=_partial_tri(fields["directive"], partial),
                native_full_count=_observed_count(fields["native_full_count"], partial),
                foreign=_as_str(fields["foreign"]),
                partial=partial,
                channels=_channel_map(fields),
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
            contract_count=_observed_count(fields["contract_count"], partial),
            home=_partial_tri(fields["home"], partial),
            project=_partial_tri(fields["project"], partial),
            directive=_partial_tri(fields["directive"], partial),
            native_full_count=_observed_count(fields["native_full_count"], partial),
            partial=partial,
            channels=_channel_map(fields),
        )
    ]


def _aggregate_rows(
    observations: list[SessionObservation],
    scored_runs: list[runs.ScoredRun],
    coverages: dict[str, str] | None = None,
) -> list[ProviderRow]:
    """Aggregate observations into one row per provider."""
    order = ("claude", "codex", "muse", "grok", "agy")
    by_provider: dict[str, list[SessionObservation]] = {name: [] for name in order}
    for obs in observations:
        by_provider.setdefault(obs.provider, []).append(obs)
    runs_by_provider: dict[str, int] = {}
    for run in scored_runs:
        runs_by_provider[run.provider] = runs_by_provider.get(run.provider, 0) + 1
    labels = coverages or {}
    rows: list[ProviderRow] = []
    for provider in order:
        obs_list = [
            o for o in by_provider.get(provider, []) if o.session_id != "unobserved"
        ]
        if not obs_list and provider not in runs_by_provider:
            continue
        rows.append(
            _aggregate_provider(
                provider,
                obs_list,
                runs_by_provider.get(provider, 0),
                coverage=labels.get(provider, "0/0"),
            )
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
                    coverage=labels.get(provider, "0/0"),
                )
            )
    return rows


def _aggregate_provider(
    provider: str,
    obs_list: list[SessionObservation],
    run_count: int,
    *,
    coverage: str = "0/0",
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
    native = (
        _modal_contract(native_counts)
        if any(value for value in native_counts if value is not None)
        else (
            "◌"
            if native_counts and all(value is None for value in native_counts)
            else "0"
        )
    )
    if provider == "agy":
        native = "◌"
        contract = "◌"
    foreign = _foreign_label(provider, obs_list)
    helpers = _helpers_label(provider, obs_list)
    denials = sum(1 for o in obs_list if o.root_guard_denial)
    bundle_counts = [
        item.bundle_count for item in root_obs if item.delivery == "explicit"
    ]
    if bundle_counts:
        bundle = _modal_contract(bundle_counts)
    elif root_obs and all(item.delivery not in (None, "explicit") for item in root_obs):
        bundle = "—"
    else:
        bundle = "◌"
    deliveries = [item.delivery for item in root_obs if item.delivery]
    delivery = _mode_label(deliveries) if deliveries else "◌"
    channels = _aggregate_channels(root_obs)
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
        coverage=coverage,
        bundle=bundle,
        delivery=delivery,
        channels=channels,
    )


def _mode_label(values: list[str]) -> str:
    if not values:
        return "◌"
    counts = Counter(values)
    highest = max(counts.values())
    winners = sorted(value for value, count in counts.items() if count == highest)
    return winners[0] if len(winners) == 1 else "/".join(winners)


def _aggregate_channels(
    observations: list[SessionObservation],
) -> dict[str, dict[str, int | bool | None]]:
    result: dict[str, dict[str, int | bool | None]] = {}
    for column in ("contract", "home", "project", "directive"):
        breakdown: dict[str, int | bool | None] = {}
        for channel in ("native", "explicit"):
            values = [
                item.channels.get(column, {}).get(channel)
                for item in observations
                if column in item.channels
            ]
            if column == "contract":
                known = [value for value in values if isinstance(value, int)]
                counts = Counter(known)
                breakdown[channel] = (
                    min(
                        value
                        for value, count in counts.items()
                        if count == max(counts.values())
                    )
                    if counts
                    else None
                )
            else:
                breakdown[channel] = _mode_tri(
                    [value if isinstance(value, bool) else None for value in values]
                )
        result[column] = breakdown
    return result


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
    if provider == "codex":
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
        checks = [o.helper_bundle for o in helper_obs if o.helper_bundle is not None]
        root_markers = [
            o.root_bundle_in_helper
            for o in helper_obs
            if o.root_bundle_in_helper is not None
        ]
        details = f"{','.join(types)}: {attempts} attempts, {accepted} accepted"
        if checks:
            details += f"; helper bundle {sum(checks)}/{len(checks)}"
        if root_markers:
            details += f"; root markers {sum(root_markers)}"
        return details
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
    coverages: dict[str, str] | None = None,
) -> VerifyReport:
    """Build a ``VerifyReport`` from runs and observations."""
    rows = _aggregate_rows(observations, scored_runs, coverages)
    return VerifyReport(
        provider_rows=tuple(rows),
        observations=tuple(observations),
        filters=dict(filters),
        generated_at=datetime.now(tz=UTC).isoformat(),
    )


__all__ = [
    "build_report",
    "collect_observations",
]
