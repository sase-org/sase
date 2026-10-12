"""Record deck subject contract (epic sase-1jm.4.2, ``shell``).

``RecordSubject`` is captured on the message pump from plain attribute
reads, wrapped defensively (``getattr`` with defaults) so an attribute
rename fails soft, never loud. If ``facts`` or ``relations`` needs a
fact the contract lacks, that phase computes it off-thread into its own
extras dataclass — never by extending this subject — so the two
parallel phases never edit the same file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: Cap on container member names captured onto a light-row subject.
_MEMBER_NAME_CAP = 8


@dataclass(frozen=True)
class RecordArchiveFacts:
    """Archived-run facts copied from the Rust Archive light row."""

    outcome: str | None = None
    time_basis: str | None = None
    last_activity: str | None = None
    start_time: str | None = None
    runtime_seconds: float | None = None
    restorable: bool | None = None
    member_count: int | None = None
    container_key: str | None = None
    archive_key: str | None = None


@dataclass(frozen=True)
class RecordSubject:
    """Pump-captured inputs for one Record deck render."""

    identity: object | None = None
    kind: str = "agent"
    location: str = "inbox"
    agent_name: str | None = None
    raw_suffix: str | None = None
    status: str | None = None
    start_time: object | None = None
    stop_time: object | None = None
    dismissed_at: object | None = None
    attempt_number: int | None = None
    historically_viewable: bool = True
    durably_revivable: bool = True
    restartable: bool = True
    missing_requirements: tuple[str, ...] = ()
    project_label: str | None = None
    project_file: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    model: str | None = None
    model_alias: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    agent_tab: str | None = None
    tribe: str | None = None
    clan_tribe: str | None = None
    imported_source_owner: str | None = None
    source_username: str | None = None
    source_machine: str | None = None
    fleet_origin_alias: str | None = None
    source_run_id: str | None = None
    artifacts_dir: str | None = None
    response_path: str | None = None
    bundle_path: str | None = None
    agent_session: str | None = None
    agent_session_role: str | None = None
    presented_session_name: str | None = None
    presented_clan_name: str | None = None
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    parent_timestamp: str | None = None
    parent_workflow: str | None = None
    retry_of_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_attempt: int = 0
    related_live_names: tuple[tuple[str, str], ...] = ()
    member_names: tuple[str, ...] = field(default_factory=tuple)
    archive: RecordArchiveFacts | None = None


def _text(value: Any) -> str | None:
    """Return ``value`` as text, or None when absent."""
    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    return text or None


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Return ``value`` as a tuple of text, tolerating any shape."""
    try:
        items = tuple(value or ())
    except Exception:
        return ()
    out: list[str] = []
    for item in items:
        try:
            text = str(item)
        except Exception:
            continue
        if text:
            out.append(text)
    return tuple(out)


def record_subject_from_agent(
    agent: Any,
    *,
    attempt_number: int | None = None,
    related_live_names: tuple[tuple[str, str], ...] = (),
    archive: RecordArchiveFacts | None = None,
    bundle_path: str | None = None,
) -> RecordSubject:
    """Capture a :class:`RecordSubject` from ``agent`` without I/O.

    Every attribute is read defensively: a missing attribute yields its
    default, never an error. ``bundle_path`` overrides the agent's own
    path when the caller already resolved one (the Archive read-only
    path does).
    """
    try:
        identity = agent.identity
    except Exception:
        identity = None
    try:
        is_container = bool(agent.is_clan_container)
    except Exception:
        is_container = False
    try:
        read_only = bool(getattr(agent, "_archive_read_only", False))
    except Exception:
        read_only = False
    try:
        owner = getattr(agent, "imported_source_owner", None)
        imported_owner = _text(getattr(owner, "owner", None) or owner)
    except Exception:
        imported_owner = None
    if bundle_path is None:
        try:
            bundle_path = _text(getattr(agent, "bundle_path", None))
        except Exception:
            bundle_path = None
    if bundle_path is None:
        try:
            bundle_path = _text(getattr(agent, "_dismissed_bundle_path", None))
        except Exception:
            bundle_path = None
    try:
        presented_session = _text(getattr(agent, "presented_agent_name", None))
    except Exception:
        presented_session = None
    try:
        presented_clan = _text(getattr(agent, "presented_clan_name", None))
    except Exception:
        presented_clan = None
    try:
        members = _string_tuple(getattr(agent, "member_names", None))
    except Exception:
        members = ()
    return RecordSubject(
        identity=identity,
        kind="container" if is_container else "agent",
        location="archive" if read_only else "inbox",
        agent_name=_text(getattr(agent, "agent_name", None)),
        raw_suffix=_text(getattr(agent, "raw_suffix", None)),
        status=_text(getattr(agent, "status", None)),
        start_time=getattr(agent, "start_time", None),
        stop_time=getattr(agent, "stop_time", None),
        dismissed_at=getattr(agent, "dismissed_at", None),
        attempt_number=attempt_number,
        historically_viewable=bool(getattr(agent, "historically_viewable", True)),
        durably_revivable=bool(getattr(agent, "durably_revivable", True)),
        restartable=bool(getattr(agent, "restartable", True)),
        missing_requirements=_string_tuple(
            getattr(agent, "missing_requirements", None)
        ),
        project_label=_text(getattr(agent, "project_label", None)),
        project_file=_text(getattr(agent, "project_file", None)),
        workspace_num=getattr(agent, "workspace_num", None),
        workspace_dir=_text(getattr(agent, "workspace_dir", None)),
        model=_text(getattr(agent, "model", None)),
        model_alias=_text(getattr(agent, "model_alias", None)),
        llm_provider=_text(getattr(agent, "llm_provider", None)),
        reasoning_effort=_text(getattr(agent, "reasoning_effort", None)),
        agent_tab=_text(getattr(agent, "agent_tab", None)),
        tribe=_text(getattr(agent, "tribe", None)),
        clan_tribe=_text(getattr(agent, "clan_tribe", None)),
        imported_source_owner=imported_owner,
        source_username=_text(getattr(agent, "source_username", None)),
        source_machine=_text(getattr(agent, "source_machine", None)),
        fleet_origin_alias=_text(getattr(agent, "fleet_origin_alias", None)),
        source_run_id=_text(getattr(agent, "source_run_id", None)),
        artifacts_dir=_text(getattr(agent, "artifacts_dir", None)),
        response_path=_text(getattr(agent, "response_path", None)),
        bundle_path=bundle_path,
        agent_session=_text(getattr(agent, "agent_session", None)),
        agent_session_role=_text(getattr(agent, "agent_session_role", None)),
        presented_session_name=presented_session,
        presented_clan_name=presented_clan,
        agent_clan=_text(getattr(agent, "agent_clan", None)),
        agent_clan_generation=_text(getattr(agent, "agent_clan_generation", None)),
        parent_timestamp=_text(getattr(agent, "parent_timestamp", None)),
        parent_workflow=_text(getattr(agent, "parent_workflow", None)),
        retry_of_timestamp=_text(getattr(agent, "retry_of_timestamp", None)),
        retried_as_timestamp=_text(getattr(agent, "retried_as_timestamp", None)),
        retry_attempt=int(getattr(agent, "retry_attempt", 0) or 0),
        related_live_names=tuple(related_live_names or ()),
        member_names=members,
        archive=archive,
    )


def _optional_int(value: Any) -> int | None:
    """Return ``value`` as int, or None when absent or unparsable."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    """Return ``value`` as float, or None when absent or unparsable."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    """Return ``value`` as bool only when it is already a bool."""
    if isinstance(value, bool):
        return value
    return None


def _archive_key_text(row: Mapping[str, Any]) -> str | None:
    """Return the ``user.machine@run`` identity for one light row."""
    archive_key = row.get("archive_key")
    if isinstance(archive_key, Mapping):
        user = archive_key.get("source_username")
        machine = archive_key.get("source_machine")
        run_id = archive_key.get("source_run_id")
        if all(isinstance(part, str) and part for part in (user, machine, run_id)):
            return f"{user}.{machine}@{run_id}"
        if isinstance(run_id, str) and run_id:
            return run_id
    if isinstance(archive_key, str) and archive_key:
        return archive_key
    return None


def _light_row_identity(row: Mapping[str, Any], kind: str) -> object:
    """Return a hashable identity for a light-row or container subject."""
    if kind == "container":
        key = row.get("container_key")
        return ("archive-container", str(key) if key else "")
    archive_key = row.get("archive_key")
    if isinstance(archive_key, Mapping):
        return (
            "archive-light",
            str(archive_key.get("source_username") or ""),
            str(archive_key.get("source_machine") or ""),
            str(archive_key.get("source_run_id") or ""),
        )
    name = _text(row.get("agent_name") or row.get("name"))
    return ("archive-light", name or "")


def _member_names_from_rows(members: Any) -> tuple[str, ...]:
    """Return capped member names from light-row mappings or strings."""
    out: list[str] = []
    try:
        rows = tuple(members or ())
    except Exception:
        return ()
    for member in rows:
        if len(out) >= _MEMBER_NAME_CAP:
            break
        if isinstance(member, Mapping):
            name = _text(
                member.get("agent_name") or member.get("name") or member.get("cl_name")
            )
        else:
            name = _text(member)
        if name:
            out.append(name)
    return tuple(out)


def record_archive_facts_from_light_row(
    row: Mapping[str, Any] | None,
) -> RecordArchiveFacts:
    """Copy Archive light-row facts onto :class:`RecordArchiveFacts` (no I/O)."""
    if not row:
        return RecordArchiveFacts()
    return RecordArchiveFacts(
        outcome=_text(row.get("outcome")),
        time_basis=_text(row.get("time_basis")),
        last_activity=_text(row.get("last_activity_at") or row.get("last_activity")),
        start_time=_text(row.get("start_time")),
        runtime_seconds=_optional_float(row.get("runtime_seconds")),
        restorable=_optional_bool(row.get("restorable")),
        member_count=_optional_int(row.get("member_count")),
        container_key=_text(row.get("container_key")),
        archive_key=_archive_key_text(row),
    )


def _project_label_from_light_row(
    row: Mapping[str, Any],
    display_snapshot: Any = None,
) -> str | None:
    """Return the light-row project as ``PROJECT_NAME``, never a directory key."""
    explicit = _text(row.get("project_label"))
    if explicit:
        return explicit
    key = _text(row.get("project"))
    if not key:
        return None
    if display_snapshot is None:
        return key
    from sase.project_display_names import project_display_name_for

    return project_display_name_for(key, snapshot=display_snapshot)


def record_subject_from_light_row(
    light_row: Mapping[str, Any] | None,
    *,
    members: Any = (),
    display_snapshot: Any = None,
) -> RecordSubject:
    """Build a :class:`RecordSubject` from an Archive light row (no I/O).

    Kind is ``container`` when the row is a container summary, else
    ``light_row`` for an unreadable (or otherwise unhydrated) entry.
    Facts come from the light row only; ``members`` supplies capped
    member names for the Relations card. Project labels map through
    ``display_snapshot`` the same way Archive banners do.
    """
    row: Mapping[str, Any] = light_row or {}
    is_container = bool(row.get("container"))
    kind = "container" if is_container else "light_row"
    archive = record_archive_facts_from_light_row(row)
    archive_key = row.get("archive_key")
    username = None
    machine = None
    run_id = None
    if isinstance(archive_key, Mapping):
        username = _text(archive_key.get("source_username"))
        machine = _text(archive_key.get("source_machine"))
        run_id = _text(archive_key.get("source_run_id"))
    restorable = archive.restorable
    return RecordSubject(
        identity=_light_row_identity(row, kind),
        kind=kind,
        location="archive",
        agent_name=_text(row.get("agent_name") or row.get("name")),
        status=_text(row.get("status")),
        start_time=row.get("start_time"),
        stop_time=row.get("stop_time"),
        dismissed_at=row.get("dismissed_at"),
        historically_viewable=True,
        durably_revivable=True if restorable is None else restorable,
        restartable=False,
        project_label=_project_label_from_light_row(
            row, display_snapshot=display_snapshot
        ),
        model=_text(row.get("model")),
        llm_provider=_text(row.get("provider")),
        source_username=username,
        source_machine=machine,
        source_run_id=run_id,
        bundle_path=_text(row.get("bundle_path")),
        member_names=_member_names_from_rows(members),
        archive=archive,
    )


def live_related_names(
    agents: Any, suffixes: tuple[str, ...] | list[str]
) -> tuple[tuple[str, str], ...]:
    """Resolve ``suffixes`` against the in-memory agent list (no I/O).

    Returns ``(suffix, agent name)`` pairs for live agents whose raw
    suffix matches, so the Relations card can render resolved
    ``@agent:`` references without touching the dismissed-bundle index.
    """
    wanted = {str(suffix) for suffix in suffixes or () if suffix}
    if not wanted:
        return ()
    try:
        rows = list(agents or ())
    except Exception:
        return ()
    found: list[tuple[str, str]] = []
    for agent in rows:
        try:
            suffix = str(getattr(agent, "raw_suffix", "") or "")
        except Exception:
            continue
        if suffix not in wanted:
            continue
        try:
            name = str(
                getattr(agent, "agent_name", None)
                or getattr(agent, "presented_agent_name", None)
                or ""
            )
        except Exception:
            name = ""
        if name:
            found.append((suffix, name))
    return tuple(found)


__all__ = [
    "RecordArchiveFacts",
    "RecordSubject",
    "live_related_names",
    "record_archive_facts_from_light_row",
    "record_subject_from_agent",
    "record_subject_from_light_row",
]
