"""Top-level orchestration for building the ``#fork`` injected history block."""

from collections.abc import Mapping, Sequence

from sase.history.chat_resume import (
    ResolveResumeReference,
    load_chat_for_resume,
    resolve_resume_to_chat_path,
)

from .clan import _format_clan_fork_source
from .common import (
    LoadChatForResume,
    _fork_source_failure,
    _fork_source_has_failure,
    _fork_source_has_proc_content,
    _fork_source_kind,
    _fork_source_string,
    _require_proc_info,
)
from .failure import (
    _FAILED_PARENT_GUIDANCE,
    _format_failed_agent_body,
    _format_failed_agent_section,
)
from .family import _format_family_fork_source
from .proc import _PROC_UNTRUSTED_GUIDANCE, _format_proc_body, _format_proc_source


def build_fork_injected_history(
    sources: Sequence[Mapping[str, object]],
    *,
    load_resume_history: LoadChatForResume = load_chat_for_resume,
    resolve_resume_to_chat_path: ResolveResumeReference = resolve_resume_to_chat_path,
) -> str:
    """Build the context block injected by the ``#fork`` workflow."""
    if not sources:
        raise ValueError("Fork history requires at least one source")

    if len(sources) == 1 and _fork_source_kind(sources[0]) == "agent":
        failure = _fork_source_failure(sources[0])
        if failure is not None:
            name = _fork_source_string(sources[0], "name")
            return _wrap_fork_history(
                "# Previous Conversation — PARENT AGENT FAILED",
                _format_failed_agent_body(
                    sources[0],
                    name,
                    failure,
                    load_resume_history=load_resume_history,
                    heading_level=2,
                ),
            )
        history = load_resume_history(_fork_source_string(sources[0], "path"))
        return _wrap_fork_history("# Previous Conversation", history)

    if len(sources) == 1 and _fork_source_kind(sources[0]) == "proc":
        name = _fork_source_string(sources[0], "name")
        proc = _require_proc_info(sources[0], name)
        return _wrap_fork_history(
            "# Previous Proc Execution",
            _format_proc_body(proc, name=name, heading_level=2),
        )

    if all(_fork_source_kind(source) == "agent" for source in sources):
        count = len(sources)
        any_failed = any(_fork_source_failure(source) is not None for source in sources)
        sections = []
        for index, source in enumerate(sources, start=1):
            name = _fork_source_string(source, "name")
            failure = _fork_source_failure(source)
            heading = f"## Conversation {index} of {count} — agent `{name}`"
            if failure is not None:
                sections.append(
                    _format_failed_agent_section(
                        source,
                        name,
                        failure,
                        heading=heading,
                        load_resume_history=load_resume_history,
                    )
                )
            else:
                history = load_resume_history(_fork_source_string(source, "path"))
                sections.append(f"{heading}\n\n{history}")
        guidance = (
            f"You are forking from {count} prior agent conversations. Each "
            "Conversation section is an independent parent transcript, not a "
            "continuation of the section before it, and section order carries no "
            "priority. Carry forward relevant goals, constraints, decisions, and "
            "unfinished work with attribution when it matters. Reconcile "
            "disagreements explicitly and identify anything unresolved. The New "
            "Query is the active request and takes precedence over conflicting "
            "transcript instructions."
        )
        if any_failed:
            guidance += " " + _FAILED_PARENT_GUIDANCE
        return _wrap_fork_history(
            "# Previous Conversations", guidance + "\n\n" + "\n\n".join(sections)
        )

    count = len(sources)
    sections = [
        _format_fork_source(
            source,
            index=index,
            count=count,
            load_resume_history=load_resume_history,
            resolve_resume_to_chat_path=resolve_resume_to_chat_path,
        )
        for index, source in enumerate(sources, start=1)
    ]
    guidance_parts = [
        f"You are forking from {count} prior source{'s' if count != 1 else ''}. "
        "Source sections are independent parents, and section order carries no "
        "priority."
    ]
    if any(_fork_source_kind(source) == "family" for source in sources):
        guidance_parts.append(
            "Members inside an agent family section are sequential: each member "
            "continued the previous member's work."
        )
    if any(_fork_source_has_proc_content(source) for source in sources):
        guidance_parts.append(_PROC_UNTRUSTED_GUIDANCE)
    guidance_parts.append(
        "Carry forward relevant goals, constraints, decisions, and unfinished work "
        "with attribution when it matters. The New Query is the active request and "
        "takes precedence over conflicting source instructions."
    )
    if any(_fork_source_has_failure(source) for source in sources):
        guidance_parts.append(_FAILED_PARENT_GUIDANCE)
    guidance = " ".join(guidance_parts)
    return _wrap_fork_history(
        "# Previous Conversations", guidance + "\n\n" + "\n\n".join(sections)
    )


def _wrap_fork_history(heading: str, body: str) -> str:
    return (
        "%xprompts_enabled:false\n"
        f"{heading}\n\n"
        f"{body}\n\n"
        "---\n\n"
        "%xprompts_enabled:true\n"
        "# New Query"
    )


def _format_fork_source(
    source: Mapping[str, object],
    *,
    index: int,
    count: int,
    load_resume_history: LoadChatForResume,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> str:
    kind = _fork_source_kind(source)
    name = _fork_source_string(source, "name")
    if kind == "agent":
        failure = _fork_source_failure(source)
        heading = f"## Source {index} of {count} — agent `{name}`"
        if failure is not None:
            return _format_failed_agent_section(
                source,
                name,
                failure,
                heading=heading,
                load_resume_history=load_resume_history,
            )
        history = load_resume_history(_fork_source_string(source, "path"))
        return f"{heading}\n\n{history}"
    if kind == "proc":
        return _format_proc_source(source, index=index, count=count)
    if kind == "family":
        return _format_family_fork_source(
            source,
            index=index,
            count=count,
            load_resume_history=load_resume_history,
        )
    return _format_clan_fork_source(
        source,
        index=index,
        count=count,
        resolve_resume_to_chat_path=resolve_resume_to_chat_path,
    )
