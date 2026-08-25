"""Family-member source classification for named-agent fork sources."""

from __future__ import annotations

from sase.agent.names import AgentFamilyMember
from sase.agent.names._lookup_artifacts import SUCCESS_OUTCOME, is_success_outcome
from sase.core.dismissed_agent_completion import (
    FAILURE_OUTCOMES,
    archived_response_path,
)
from sase.monitor_state import is_real_monitor_member, monitor_state_is_terminal
from sase.scripts._agent_chat_from_name_common import (
    json_string,
    read_json_dict,
    read_json_string_field,
    validate_readable_transcript,
)
from sase.scripts._agent_chat_from_name_failure import (
    failed_agent_family_member_shell,
)
from sase.scripts._agent_chat_from_name_models import (
    ForkExcludedFamilyMember,
    ForkFamilyMemberSource,
)
from sase.scripts._agent_chat_from_name_monitor import read_family_monitor_marker
from sase.scripts._fork_proc_sources import proc_info_from_monitor


def resolve_family_member_shell(
    member: AgentFamilyMember,
) -> ForkFamilyMemberSource | ForkExcludedFamilyMember:
    """Classify and resolve one sequential family member's concrete shell.

    A monitor member is a proc shell, never a chat transcript: its
    ``agent_family_role``/``monitor_id`` markers route it to the durable
    monitor+proc join instead of the agent chat-path lookup below.
    """
    meta = read_json_dict(member.artifacts_dir / "agent_meta.json") or {}
    if is_real_monitor_member(
        json_string(meta, "agent_family_role"),
        json_string(meta, "monitor_id"),
    ):
        return _resolve_monitor_family_member_shell(member)
    return _resolve_agent_family_member_shell(member)


def _resolve_monitor_family_member_shell(
    member: AgentFamilyMember,
) -> ForkFamilyMemberSource | ForkExcludedFamilyMember:
    record = read_family_monitor_marker(member.artifacts_dir)
    if record is None:
        return ForkExcludedFamilyMember(
            name=member.name, status="unreadable monitor record"
        )
    if not monitor_state_is_terminal(record.monitor_state):
        return ForkExcludedFamilyMember(name=member.name, status="running")
    return ForkFamilyMemberSource(
        name=member.name,
        artifact_dir=str(member.artifacts_dir),
        outcome=record.monitor_state,
        kind="proc",
        proc=proc_info_from_monitor(record),
    )


def _resolve_agent_family_member_shell(
    member: AgentFamilyMember,
) -> ForkFamilyMemberSource | ForkExcludedFamilyMember:
    """Resolve one sequential agent member's owned transcript or failure record.

    A metadata chat path is written only after a phase saves its handoff, so it
    identifies that member's conversation even when the root later receives an
    aggregate done marker for the terminal child. Legacy and terminal members
    without that metadata continue to use a successful done response. A
    terminal failed member is included with failure context rather than
    dropped; only a still-running, missing, or unreadable member is excluded.
    """
    meta_path = read_json_string_field(
        member.artifacts_dir / "agent_meta.json", "chat_path"
    )
    if meta_path is not None:
        try:
            validate_readable_transcript(member.name, meta_path)
        except OSError:
            return ForkExcludedFamilyMember(
                name=member.name, status="unreadable transcript"
            )
        return ForkFamilyMemberSource(
            name=member.name,
            artifact_dir=str(member.artifacts_dir),
            outcome=SUCCESS_OUTCOME,
            kind="agent",
            path=meta_path,
        )

    if member.outcome is None:
        return ForkExcludedFamilyMember(name=member.name, status="running")

    if member.outcome in FAILURE_OUTCOMES:
        done = read_json_dict(member.artifacts_dir / "done.json") or {}
        return failed_agent_family_member_shell(member, done, member.outcome)

    if not is_success_outcome(member.outcome):
        return ForkExcludedFamilyMember(
            name=member.name, status=member.outcome or "running"
        )

    done_path = read_json_string_field(
        member.artifacts_dir / "done.json", "response_path"
    )
    if done_path is None and member.archived_completion is not None:
        done_path = archived_response_path(member.archived_completion)
    if done_path is None:
        return ForkExcludedFamilyMember(name=member.name, status="missing transcript")
    try:
        validate_readable_transcript(member.name, done_path)
    except OSError:
        return ForkExcludedFamilyMember(
            name=member.name, status="unreadable transcript"
        )
    return ForkFamilyMemberSource(
        name=member.name,
        artifact_dir=str(member.artifacts_dir),
        outcome=SUCCESS_OUTCOME,
        kind="agent",
        path=done_path,
    )
