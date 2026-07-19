"""Formatting for conversation history injected by the ``#fork`` workflow."""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from sase.history.chat_resume import (
    ResolveResumeReference,
    extract_previous_conversation_turns,
    find_resume_ref_groups,
    find_resume_refs,
    load_chat_for_resume,
    parse_chat_turns,
    resolve_resume_to_chat_path,
    sanitize_resume_prompt,
)
from sase.history.chat_storage import (
    format_metadata_model,
    load_chat_history,
)

LoadChatForResume = Callable[[str], str]


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
        history = load_resume_history(_fork_source_string(sources[0], "path"))
        return _wrap_fork_history("# Previous Conversation", history)

    if all(_fork_source_kind(source) == "agent" for source in sources):
        count = len(sources)
        sections = []
        for index, source in enumerate(sources, start=1):
            name = _fork_source_string(source, "name")
            history = load_resume_history(_fork_source_string(source, "path"))
            sections.append(
                f"## Conversation {index} of {count} — agent `{name}`\n\n{history}"
            )
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
    guidance = (
        f"You are forking from {count} prior source{'s' if count != 1 else ''}. "
        "Each Source section is independent, and section order carries no "
        "priority. Carry forward relevant goals, constraints, decisions, and "
        "unfinished work with attribution when it matters. The New Query is the "
        "active request and takes precedence over conflicting source instructions."
    )
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


def _fork_source_kind(source: Mapping[str, object]) -> str:
    value = source.get("kind", "agent")
    if value not in {"agent", "clan"}:
        raise ValueError(f"Unsupported fork source kind: {value!r}")
    return str(value)


def _fork_source_string(source: Mapping[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Fork source field '{field}' must be a non-empty string")
    return value


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
        history = load_resume_history(_fork_source_string(source, "path"))
        return f"## Source {index} of {count} — agent `{name}`\n\n{history}"
    return _format_clan_fork_source(
        source,
        index=index,
        count=count,
        resolve_resume_to_chat_path=resolve_resume_to_chat_path,
    )


def _format_clan_fork_source(
    source: Mapping[str, object],
    *,
    index: int,
    count: int,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> str:
    name = _fork_source_string(source, "name")
    generation = _fork_source_string(source, "generation")
    raw_members = source.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError(f"Clan fork source '{name}' has no members")
    members = sorted(
        (_require_fork_member(member, name) for member in raw_members),
        key=lambda member: Path(_fork_source_string(member, "artifact_dir")).name,
    )

    header_rows = [
        f"## Source {index} of {count} — agent clan `{name}`",
        "",
        f"- **Generation:** `{generation}`",
    ]
    tribe = source.get("tribe")
    if isinstance(tribe, str) and tribe:
        header_rows.append(f"- **Tribe:** `@{tribe}`")
    header_rows.extend(
        [
            f"- **Members:** {len(members)}",
            "",
            "Full clan-member replies were intentionally omitted. Read a listed "
            "transcript only when that member's full reply is needed.",
        ]
    )
    member_blocks = [
        _format_clan_member(
            member,
            index=member_index,
            count=len(members),
            resolve_resume_to_chat_path=resolve_resume_to_chat_path,
        )
        for member_index, member in enumerate(members, start=1)
    ]
    return "\n".join(header_rows) + "\n\n" + "\n\n".join(member_blocks)


def _require_fork_member(value: object, clan_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Clan fork source '{clan_name}' has an invalid member")
    return value


def _format_clan_member(
    member: Mapping[str, object],
    *,
    index: int,
    count: int,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> str:
    name = _fork_source_string(member, "name")
    path = _fork_source_string(member, "path")
    artifact_dir = Path(_fork_source_string(member, "artifact_dir"))
    turns = parse_chat_turns(load_chat_history(path))
    word_count = sum(len(response.split()) for _, response in turns)
    line_count = sum(len(response.splitlines()) for _, response in turns if response)

    meta = _load_json_object(artifact_dir / "agent_meta.json")
    done = _load_json_object(artifact_dir / "done.json")
    outcome = _json_string(done, "outcome") or "unknown"
    model = (
        format_metadata_model(
            _json_string(meta, "llm_provider"),
            _json_string(meta, "model"),
        )
        or "unknown"
    )
    prompts = _load_fork_member_prompts(
        path,
        resolve_resume_to_chat_path=resolve_resume_to_chat_path,
    )
    prompt_blocks = [
        f"#### Prompt {prompt_index} of {len(prompts)}\n\n{prompt}"
        for prompt_index, prompt in enumerate(prompts, start=1)
    ]
    if not prompt_blocks:
        prompt_blocks = ["#### Prompts\n\n(No parsed prompts found.)"]

    summary = (
        f"**Reply summary:** outcome `{outcome}` · model `{model}` · launch "
        f"`{artifact_dir.name}` · approximately {word_count} words / "
        f"{line_count} lines · transcript `{path}`"
    )
    return (
        f"### Member {index} of {count} — agent `{name}`\n\n{summary}\n\n"
        + "\n\n".join(prompt_blocks)
    )


def _load_fork_member_prompts(
    file_ref: str,
    _visited: set[str] | None = None,
    *,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> list[str]:
    """Load sanitized prompts recursively while omitting every reply body."""
    visited = set() if _visited is None else _visited
    content = load_chat_history(file_ref)
    if file_ref.startswith("/") or file_ref.startswith("~"):
        absolute_path = os.path.abspath(os.path.expanduser(file_ref))
    else:
        from sase.history.chat_storage import (
            get_chat_file_path,
            resolve_chat_file_path,
        )

        absolute_path = os.path.abspath(
            resolve_chat_file_path(file_ref) or get_chat_file_path(file_ref)
        )
    if absolute_path in visited:
        return []
    visited.add(absolute_path)

    prompts: list[str] = []
    for prompt, _response in parse_chat_turns(content):
        refs = find_resume_ref_groups(prompt) if find_resume_refs(prompt) else []
        for full_match, xprompt_name, arguments in refs:
            needs_fallback = False
            for argument in arguments:
                resolved_path = resolve_resume_to_chat_path(xprompt_name, argument)
                normalized_path = (
                    os.path.abspath(os.path.expanduser(resolved_path))
                    if resolved_path
                    else None
                )
                if resolved_path is not None and normalized_path not in visited:
                    try:
                        prompts.extend(
                            _load_fork_member_prompts(
                                resolved_path,
                                set(visited),
                                resolve_resume_to_chat_path=resolve_resume_to_chat_path,
                            )
                        )
                    except OSError:
                        needs_fallback = True
                elif resolved_path is None:
                    needs_fallback = True
            if needs_fallback:
                prompts.extend(
                    clean
                    for fallback_prompt, _ in extract_previous_conversation_turns(
                        content
                    )
                    if (clean := sanitize_resume_prompt(fallback_prompt))
                )
            prompt = prompt.replace(full_match, "", 1).strip()

        clean_prompt = sanitize_resume_prompt(prompt)
        if clean_prompt:
            prompts.append(clean_prompt)
    return prompts


def _load_json_object(path: Path) -> Mapping[str, object]:
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    return value if isinstance(value, str) and value else None
