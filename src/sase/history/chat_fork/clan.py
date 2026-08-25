"""Formatting for agent-clan fork sources (prompt-only summaries)."""

import os
from collections.abc import Mapping
from pathlib import Path

from sase.history.chat_resume import (
    ResolveResumeReference,
    extract_previous_conversation_turns,
    find_resume_ref_groups,
    find_resume_refs,
    parse_chat_turns,
    sanitize_resume_prompt,
)
from sase.history.chat_storage import format_metadata_model, load_chat_history

from .common import fork_source_string, json_string, load_json_object


def format_clan_fork_source(
    source: Mapping[str, object],
    *,
    index: int,
    count: int,
    resolve_resume_to_chat_path: ResolveResumeReference,
) -> str:
    name = fork_source_string(source, "name")
    generation = fork_source_string(source, "generation")
    raw_members = source.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError(f"Clan fork source '{name}' has no members")
    members = sorted(
        (_require_fork_member(member, name) for member in raw_members),
        key=lambda member: Path(fork_source_string(member, "artifact_dir")).name,
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
    name = fork_source_string(member, "name")
    path = fork_source_string(member, "path")
    artifact_dir = Path(fork_source_string(member, "artifact_dir"))
    turns = parse_chat_turns(load_chat_history(path))
    word_count = sum(len(response.split()) for _, response in turns)
    line_count = sum(len(response.splitlines()) for _, response in turns if response)

    meta = load_json_object(artifact_dir / "agent_meta.json")
    done = load_json_object(artifact_dir / "done.json")
    outcome = json_string(done, "outcome") or "unknown"
    model = (
        format_metadata_model(
            json_string(meta, "llm_provider"),
            json_string(meta, "model"),
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
