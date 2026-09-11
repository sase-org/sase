"""Top-level orchestration for building the ``#fork`` injected history block."""

from collections.abc import Mapping, Sequence

from sase.history.chat_resume import (
    ResolveResumeReference,
    load_chat_for_resume,
    resolve_resume_to_chat_path,
)

from .clan import format_clan_fork_source
from .common import (
    LoadChatForResume,
    fork_source_failure,
    fork_source_has_failure,
    fork_source_has_proc_content,
    fork_source_kind,
    fork_source_string,
    require_proc_info,
)
from .continuation import render_versioned_continuation_history
from .failure import (
    FAILED_PARENT_GUIDANCE,
    format_failed_agent_body,
    format_failed_agent_section,
)
from .family import format_family_fork_source
from .proc import PROC_UNTRUSTED_GUIDANCE, format_proc_body, format_proc_source


def build_fork_injected_history(
    sources: Sequence[Mapping[str, object]],
    *,
    load_resume_history: LoadChatForResume = load_chat_for_resume,
    resolve_resume_to_chat_path: ResolveResumeReference = resolve_resume_to_chat_path,
) -> str:
    """Build the context block injected by the ``#fork`` workflow."""
    rendered: str
    if not sources:
        raise ValueError("Fork history requires at least one source")

    versioned_history = render_versioned_continuation_history(sources)
    if versioned_history:
        rendered = _wrap_fork_history("# Previous Continuation", versioned_history)
        _record_fork_shadow_measurement(sources, rendered)
        return rendered

    if len(sources) == 1 and fork_source_kind(sources[0]) == "agent":
        failure = fork_source_failure(sources[0])
        if failure is not None:
            name = fork_source_string(sources[0], "name")
            rendered = _wrap_fork_history(
                "# Previous Conversation — PARENT AGENT FAILED",
                format_failed_agent_body(
                    sources[0],
                    name,
                    failure,
                    load_resume_history=load_resume_history,
                    heading_level=2,
                ),
            )
            _record_fork_shadow_measurement(sources, rendered)
            return rendered
        history = load_resume_history(fork_source_string(sources[0], "path"))
        rendered = _wrap_fork_history("# Previous Conversation", history)
        _record_fork_shadow_measurement(sources, rendered)
        return rendered

    if len(sources) == 1 and fork_source_kind(sources[0]) == "proc":
        name = fork_source_string(sources[0], "name")
        proc = require_proc_info(sources[0], name)
        rendered = _wrap_fork_history(
            "# Previous Proc Execution",
            format_proc_body(proc, name=name, heading_level=2),
        )
        _record_fork_shadow_measurement(sources, rendered)
        return rendered

    if all(fork_source_kind(source) == "agent" for source in sources):
        count = len(sources)
        any_failed = any(fork_source_failure(source) is not None for source in sources)
        sections = []
        for index, source in enumerate(sources, start=1):
            name = fork_source_string(source, "name")
            failure = fork_source_failure(source)
            heading = f"## Conversation {index} of {count} — agent `{name}`"
            if failure is not None:
                sections.append(
                    format_failed_agent_section(
                        source,
                        name,
                        failure,
                        heading=heading,
                        load_resume_history=load_resume_history,
                    )
                )
            else:
                history = load_resume_history(fork_source_string(source, "path"))
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
            guidance += " " + FAILED_PARENT_GUIDANCE
        rendered = _wrap_fork_history(
            "# Previous Conversations", guidance + "\n\n" + "\n\n".join(sections)
        )
        _record_fork_shadow_measurement(sources, rendered)
        return rendered

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
    if any(fork_source_kind(source) == "family" for source in sources):
        guidance_parts.append(
            "Members inside an agent family section are sequential: each member "
            "continued the previous member's work."
        )
    if any(fork_source_has_proc_content(source) for source in sources):
        guidance_parts.append(PROC_UNTRUSTED_GUIDANCE)
    guidance_parts.append(
        "Carry forward relevant goals, constraints, decisions, and unfinished work "
        "with attribution when it matters. The New Query is the active request and "
        "takes precedence over conflicting source instructions."
    )
    if any(fork_source_has_failure(source) for source in sources):
        guidance_parts.append(FAILED_PARENT_GUIDANCE)
    guidance = " ".join(guidance_parts)
    rendered = _wrap_fork_history(
        "# Previous Conversations", guidance + "\n\n" + "\n\n".join(sections)
    )
    _record_fork_shadow_measurement(sources, rendered)
    return rendered


def _wrap_fork_history(heading: str, body: str) -> str:
    from sase.xprompt._disabled_regions import wrap_disabled_region

    region_body = f"{heading}\n\n{body}\n\n---\n"
    return f"{wrap_disabled_region(region_body)}\n# New Query"


def _record_fork_shadow_measurement(
    sources: Sequence[Mapping[str, object]],
    rendered: str,
) -> None:
    import os

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    from sase.continuation_baseline import (
        measure_fork_render,
        record_shadow_measurement,
    )

    record_shadow_measurement(artifacts_dir, measure_fork_render(sources, rendered))


def _format_fork_source(
    source: Mapping[str, object],
    *,
    index: int,
    count: int,
    load_resume_history: LoadChatForResume,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> str:
    kind = fork_source_kind(source)
    name = fork_source_string(source, "name")
    if kind == "agent":
        failure = fork_source_failure(source)
        heading = f"## Source {index} of {count} — agent `{name}`"
        if failure is not None:
            return format_failed_agent_section(
                source,
                name,
                failure,
                heading=heading,
                load_resume_history=load_resume_history,
            )
        history = load_resume_history(fork_source_string(source, "path"))
        return f"{heading}\n\n{history}"
    if kind == "proc":
        return format_proc_source(source, index=index, count=count)
    if kind == "family":
        return format_family_fork_source(
            source,
            index=index,
            count=count,
            load_resume_history=load_resume_history,
        )
    return format_clan_fork_source(
        source,
        index=index,
        count=count,
        resolve_resume_to_chat_path=resolve_resume_to_chat_path,
    )
