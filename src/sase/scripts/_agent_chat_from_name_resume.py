"""Plain transcript-path resolution for named-agent resume targets."""

from __future__ import annotations

from sase.agent.names import AgentFamilyMember
from sase.agent.names._lookup_artifacts import is_success_outcome
from sase.core.dismissed_agent_completion import archived_response_path
from sase.scripts._agent_chat_from_name_common import (
    find_family_member,
    normalize_name,
    read_json_string_field,
    resolve_default_agent_name,
    resolve_done_response_path,
    resolve_meta_chat_path,
    validate_readable_transcript,
)


def resolve_agent_chat_path(name: str | None = None) -> str:
    """Return the chat path for an explicit or default resume target.

    Explicit family members use their member-owned ``agent_meta.json`` chat
    before a successful ``done.json`` fallback. Other explicit names preserve
    the legacy done-before-meta lookup order. An omitted name resolves to the
    most recently launched named agent, excluding ``SASE_ARTIFACTS_DIR`` so an
    agent cannot accidentally resume itself.
    """
    resolved_name = normalize_name(name)
    if resolved_name is None:
        resolved_name = resolve_default_agent_name()

    family_member = find_family_member(resolved_name)
    if family_member is not None:
        path = _resolve_family_member_resume_transcript(family_member)
        if path:
            return path
        raise RuntimeError(f"No agent with chat history found for: {resolved_name}")

    response_path = resolve_done_response_path(resolved_name)
    if response_path:
        return response_path

    chat_path = resolve_meta_chat_path(resolved_name)
    if chat_path:
        return chat_path

    raise RuntimeError(f"No agent with chat history found for: {resolved_name}")


def _resolve_family_member_resume_transcript(
    member: AgentFamilyMember,
) -> str | None:
    """Resolve one sequential member's owned transcript for plain resume.

    Kept independent of the ``#fork`` shell classifier: a resume target is just
    a chat path, so monitor/proc members and failed members without a saved
    transcript resolve to "nothing to resume", preserving ``%resume`` behavior.
    """
    meta_path = read_json_string_field(
        member.artifacts_dir / "agent_meta.json", "chat_path"
    )
    if meta_path is not None:
        try:
            validate_readable_transcript(member.name, meta_path)
        except OSError:
            return None
        return meta_path

    if not is_success_outcome(member.outcome):
        return None

    done_path = read_json_string_field(
        member.artifacts_dir / "done.json", "response_path"
    )
    if done_path is None and member.archived_completion is not None:
        done_path = archived_response_path(member.archived_completion)
    if done_path is None:
        return None
    try:
        validate_readable_transcript(member.name, done_path)
    except OSError:
        return None
    return done_path
