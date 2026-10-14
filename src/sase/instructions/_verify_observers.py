"""Provider-specific session observation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.instructions import claude as claude_parser
from sase.instructions import codex as codex_parser
from sase.instructions import fingerprints as fp
from sase.instructions import grok as grok_parser
from sase.instructions import muse as muse_parser
from sase.instructions import run_index as runs
from sase.instructions.models import SessionObservation


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


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


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


def observe_claude(
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


def observe_codex(
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


def observe_grok(run: runs.ScoredRun, project: str | None) -> list[SessionObservation]:
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


def observe_muse(
    run: runs.ScoredRun, home: str | None, project: str | None
) -> list[SessionObservation]:
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    observations: list[SessionObservation] = []
    for session_id in runs.find_muse_session_ids(run):
        log_path = find_muse_session_log(session_id)
        if log_path is None:
            continue
        records, partial = runs.read_jsonl_capped(
            log_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
        fields = muse_parser.observe_muse_session(
            records, home_h1=home, project_h1=project
        )
        observations.append(
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
        )
    if observations:
        return observations
    fallback_id = runs.find_muse_session_id(run)
    if not fallback_id:
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
    return [
        SessionObservation(
            provider="muse",
            run_name=run.name,
            session_id=fallback_id,
            contract_count=0,
            home=False,
            project=None,
            directive=None,
            native_full_count=0,
        )
    ]
