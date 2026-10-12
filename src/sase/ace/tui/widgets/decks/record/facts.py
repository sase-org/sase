"""Record Lifecycle and Provenance cards (epic sase-1jm.4.2, ``facts``).

Builders are pump-safe: they read only :class:`RecordSubject` and
:class:`FactsExtras`. Disk, identity-state, and index work live in
:func:`load_facts_extras`, which the Record worker calls off-thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text

from ..card_part import CardPart
from .model import RecordArchiveFacts, RecordSubject

_LABEL = "bold #87D7FF"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_DONE_STYLE = "dim #5faf5f"
_FAILED_STYLE = "dim #d75f5f"
_LOCATIONS = {"inbox": "Inbox", "archive": "Archive"}


@dataclass(frozen=True)
class FactsExtras:
    """Off-thread Lifecycle/Provenance inputs (filled by ``facts``)."""

    reference: str | None = None
    artifacts_dir: str | None = None
    chat_path: str | None = None
    dismissed_at: str | None = None
    revived_at: str | None = None
    times_revived: int = 0
    bundle_path: str | None = None


def load_facts_extras(subject: RecordSubject) -> FactsExtras:
    """Load Lifecycle/Provenance extras for ``subject`` (worker thread).

    Resolves the ``@agent:`` reference, the artifacts dir (the stored
    path, resolved the way :meth:`Agent.get_artifacts_dir` resolves an
    explicit dir), the chat path from ``agent_meta.json``, and
    dismissed-bundle index rows. A missing index yields empty values,
    never an error.
    """
    reference = _load_reference(subject)
    artifacts_dir = _load_artifacts_dir(subject)
    chat_path = _load_chat_path(artifacts_dir)
    dismissed_at, revived_at, times_revived, index_bundle = _load_index_facts(subject)
    bundle_path = subject.bundle_path or index_bundle
    return FactsExtras(
        reference=reference,
        artifacts_dir=artifacts_dir,
        chat_path=chat_path,
        dismissed_at=dismissed_at,
        revived_at=revived_at,
        times_revived=times_revived,
        bundle_path=bundle_path,
    )


def lifecycle_card(subject: RecordSubject, extras: FactsExtras) -> CardPart:
    """Build the Lifecycle card from pump-captured facts plus extras."""
    text = Text()
    heading = extras.reference or subject.agent_name or "Unnamed agent"
    text.append(heading, style="bold")
    text.append("\n")
    _field(text, "Location", _location_label(subject.location))
    _status_line(text, subject)
    archive = subject.archive
    if archive is not None:
        _outcome_line(text, subject, archive)
    _field(text, "Started", _started_value(subject))
    ended = _format_timestamp(subject.stop_time)
    if ended:
        _field(text, "Ended", ended)
    else:
        text.append("Ended: ", style=_LABEL)
        text.append("end not recorded", style="dim italic")
        text.append("\n")
    dismissed = _format_timestamp(extras.dismissed_at)
    if dismissed:
        _field(text, "Dismissed", dismissed)
    if archive is not None and archive.last_activity:
        last = _format_timestamp(archive.last_activity)
        if last:
            _field(text, "Last activity", last)
    if archive is not None and archive.time_basis:
        _time_basis_line(text, archive.time_basis)
    if extras.times_revived > 0:
        revived = f"×{extras.times_revived}"
        revived_at = _format_timestamp(extras.revived_at)
        if revived_at:
            revived = f"{revived} ({revived_at})"
        _field(text, "Revived", revived)
    _field(text, "Viewable", _yes_no(subject.historically_viewable))
    _field(text, "Restorable", _yes_no(_restorable(subject)))
    _field(text, "Restartable", _yes_no(subject.restartable))
    if subject.missing_requirements:
        _field(text, "Missing", ", ".join(subject.missing_requirements))
    return CardPart("lifecycle", "Lifecycle", text)


def provenance_card(subject: RecordSubject, extras: FactsExtras) -> CardPart:
    """Build the Provenance card from pump-captured facts plus extras."""
    text = Text()
    _field(text, "Project", subject.project_label)
    _workspace_lines(text, subject)
    _model_lines(text, subject)
    _field(text, "Agent tab", subject.agent_tab or "main")
    if subject.tribe:
        _field(text, "Tribe", subject.tribe)
    if subject.clan_tribe:
        _field(text, "Clan tribe", subject.clan_tribe)
    owner = _owner_label(subject)
    if owner:
        _field(text, "Owner", owner)
    if subject.source_run_id:
        _field(text, "Source run", subject.source_run_id)
    _field(text, "Chat", extras.chat_path)
    _artifacts_line(text, extras.artifacts_dir)
    bundle = extras.bundle_path or subject.bundle_path
    if subject.location == "archive" or bundle:
        _field(text, "Bundle", bundle)
    return CardPart("provenance", "Provenance", text)


def _load_reference(subject: RecordSubject) -> str | None:
    name = subject.agent_name
    if not name:
        return None
    try:
        from sase.artifact_ref_entries import reference_for_agent_name

        return reference_for_agent_name(name)
    except Exception:
        return None


def _load_artifacts_dir(subject: RecordSubject) -> str | None:
    raw = subject.artifacts_dir
    if not raw:
        return None
    from pathlib import Path

    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_path

        resolved = resolve_agent_artifact_path(raw)
    except Exception:
        resolved = Path(raw)
    try:
        if resolved.is_dir():
            return str(resolved)
    except Exception:
        return None
    return None


def _load_chat_path(artifacts_dir: str | None) -> str | None:
    if not artifacts_dir:
        return None
    try:
        import os

        from sase.agent.artifact_files_cache import get_global_cache

        meta = get_global_cache().read_json(
            os.path.join(artifacts_dir, "agent_meta.json")
        )
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    candidate = meta.get("chat_path")
    if isinstance(candidate, str) and candidate:
        return candidate
    return None


def _load_index_facts(
    subject: RecordSubject,
) -> tuple[str | None, str | None, int, str | None]:
    suffix = subject.raw_suffix
    if not suffix:
        return None, None, 0, None
    try:
        from sase.ace.dismissed_agents import dismissed_bundles_dir
        from sase.ace.dismissed_bundle_index import query_summaries

        root = dismissed_bundles_dir()
        summaries = query_summaries(root, suffixes={suffix}, visibility=None)
    except Exception:
        return None, None, 0, None
    if not summaries:
        return None, None, 0, None
    row = summaries[0]
    dismissed_at = _text(getattr(row, "dismissed_at", None))
    revived_at = _text(getattr(row, "revived_at", None))
    try:
        times_revived = int(getattr(row, "times_revived", 0) or 0)
    except (TypeError, ValueError):
        times_revived = 0
    bundle_path = _text(getattr(row, "bundle_path", None))
    return dismissed_at, revived_at, times_revived, bundle_path


def _location_label(location: str) -> str:
    return _LOCATIONS.get(location, location.title() if location else "—")


def _status_line(text: Text, subject: RecordSubject) -> None:
    text.append("Status: ", style=_LABEL)
    if subject.status:
        from sase.agents.status_style import agent_status_text

        text.append_text(agent_status_text(subject.status.upper()))
    else:
        text.append("—", style="dim")
    text.append("\n")


def _outcome_line(
    text: Text, subject: RecordSubject, archive: RecordArchiveFacts
) -> None:
    label, style = _outcome_label(
        {"outcome": archive.outcome or "", "status": subject.status or ""}
    )
    text.append("Outcome: ", style=_LABEL)
    text.append(label, style=style)
    text.append("\n")


def _outcome_label(row: dict[str, Any]) -> tuple[str, str]:
    """Match Archive-row √ / ✗ / ○ WAS vocabulary (``_rows._outcome_label``)."""
    from sase.ace.tui.models.agent_status import STOPPED_COLOR

    outcome = str(row.get("outcome") or "")
    if outcome == "done":
        return "✓ done", _DONE_STYLE
    if outcome == "failed":
        return "✗ failed", _FAILED_STYLE
    status = str(row.get("status") or "").strip() or "UNKNOWN"
    return f"○ WAS {status}", f"bold {STOPPED_COLOR}"


def _started_value(subject: RecordSubject) -> str | None:
    archive = subject.archive
    if archive is not None and archive.start_time:
        started = _format_timestamp(archive.start_time)
        if started:
            return started
    return _format_timestamp(subject.start_time)


def _time_basis_line(text: Text, basis: str) -> None:
    text.append("Time basis: ", style=_LABEL)
    if basis == "started":
        text.append(basis, style="dim italic")
    elif basis == "dismissed":
        text.append(basis, style="dim")
    else:
        text.append(basis)
    text.append("\n")


def _restorable(subject: RecordSubject) -> bool:
    archive = subject.archive
    if archive is not None and archive.restorable is not None:
        return bool(archive.restorable)
    return bool(subject.durably_revivable)


def _workspace_lines(text: Text, subject: RecordSubject) -> None:
    number = subject.workspace_num
    if number is not None and not isinstance(number, bool):
        try:
            parsed = int(number)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            _field(text, "Workspace", f"#{parsed}")
    if subject.workspace_dir:
        _field(text, "Directory", subject.workspace_dir)


def _model_lines(text: Text, subject: RecordSubject) -> None:
    from sase.llm_provider.model_label import append_model_field

    before = len(text)
    append_model_field(
        text,
        subject.model,
        subject.llm_provider,
        subject.reasoning_effort,
        subject.model_alias,
    )
    if len(text) > before:
        return
    if subject.llm_provider:
        _field(text, "Provider", subject.llm_provider)
    if subject.reasoning_effort:
        _field(text, "Effort", subject.reasoning_effort)


def _owner_label(subject: RecordSubject) -> str | None:
    if subject.imported_source_owner:
        return subject.imported_source_owner
    user = subject.source_username
    machine = subject.source_machine
    if user and machine:
        return f"{user}@{machine}"
    return user or machine


def _artifacts_line(text: Text, artifacts_dir: str | None) -> None:
    text.append("Artifacts dir: ", style=_LABEL)
    if artifacts_dir:
        text.append(artifacts_dir)
    else:
        text.append("not recorded", style="dim italic")
    text.append("\n")


def _format_timestamp(value: object) -> str | None:
    if value is None or value == "":
        return None
    from sase.ace.tui.models.agent_archive_list import parse_archive_timestamp
    from sase.core.time import format_local, get_timezone

    if isinstance(value, str):
        parsed = parse_archive_timestamp(value, get_timezone())
        if parsed is not None:
            return parsed.strftime(_TIME_FMT)
    formatted = format_local(value, _TIME_FMT, default="")  # type: ignore[arg-type]
    return formatted or None


def _field(text: Text, label: str, value: object | None) -> None:
    text.append(f"{label}: ", style=_LABEL)
    if value is None or value == "":
        text.append("—", style="dim")
    elif isinstance(value, Text):
        text.append_text(value)
    else:
        text.append(str(value))
    text.append("\n")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _text(value: object) -> str | None:
    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    return text or None


__all__ = [
    "FactsExtras",
    "lifecycle_card",
    "load_facts_extras",
    "provenance_card",
]
