"""Transcript parsing and recursive resume-history expansion."""

import json
import os
import re
from collections.abc import Callable

from sase.history.chat_storage import (
    get_chat_file_path,
    load_chat_history,
    resolve_chat_file_path,
)

ResolveResumeReference = Callable[[str, str], str | None]


# Matches current #fork / #fork_by_chat refs plus legacy #resume /
# #resume_by_chat refs preserved in historical chat transcripts.
_RESUME_REF_RE = re.compile(
    r"#(fork|fork_by_chat|resume|resume_by_chat)"
    r"(?:"
    r":(`[^`]+`|[^\s)]+)"
    r"|"
    r"\((`[^`]+`|[^)]*)\)"
    r")"
)

# Unrendered Jinja2 markers left literal in stored prompt text.
_JINJA_MARKER_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)


def sanitize_resume_prompt(prompt: str) -> str:
    """Strip SASE control syntax from a stored user prompt."""
    if not prompt:
        return prompt

    # Lazy imports avoid import-cycle risk with sase.xprompt.
    from sase.xprompt._disabled_regions import strip_disabled_region_markers
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing_references import iter_xprompt_references
    from sase.xprompt.directives import strip_known_directives

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    protected = strip_known_directives(protected)
    protected = strip_disabled_region_markers(protected)

    refs = sorted(
        iter_xprompt_references(protected), key=lambda ref: ref.start, reverse=True
    )
    for ref in refs:
        protected = protected[: ref.start] + protected[ref.end :]

    protected = _JINJA_MARKER_RE.sub("", protected)
    protected = re.sub(r"[ \t]+\n", "\n", protected)
    protected = re.sub(r"(?m)^[ \t]+", "", protected)
    protected = re.sub(r"\n{3,}", "\n\n", protected)

    protected = unprotect_fenced_blocks(protected, fenced_blocks)
    return protected.strip()


def find_resume_refs(text: str) -> list[tuple[str, str, str]]:
    """Find and flatten all current or legacy fork references in text."""
    results: list[tuple[str, str, str]] = []
    for full_match, xprompt_name, arguments in find_resume_ref_groups(text):
        results.extend((full_match, xprompt_name, argument) for argument in arguments)
    return results


def find_resume_ref_groups(text: str) -> list[tuple[str, str, list[str]]]:
    """Return references with every argument attached to its original span."""
    results: list[tuple[str, str, list[str]]] = []
    for match in _RESUME_REF_RE.finditer(text):
        full_match = match.group(0)
        xprompt_name = match.group(1)
        raw_arg = match.group(2) or match.group(3)
        if raw_arg.startswith("`") and raw_arg.endswith("`"):
            arguments = [raw_arg[1:-1]]
        elif xprompt_name in {"fork", "resume"}:
            from sase.xprompt._parsing import parse_args

            arguments, _ = parse_args(raw_arg, preserve_empty_args=True)
            arguments = [argument for argument in arguments if argument]
        else:
            arguments = [raw_arg]
        results.append((full_match, xprompt_name, arguments))
    return results


def resolve_resume_to_chat_path(xprompt_name: str, argument: str) -> str | None:
    """Resolve a fork/resume reference to a chat file path."""
    if xprompt_name in {"fork_by_chat", "resume_by_chat"}:
        path = os.path.expanduser(argument)
        if not path.endswith(".md"):
            return resolve_chat_file_path(path)
        return path if os.path.exists(path) else None

    if xprompt_name == "fork":
        try:
            from sase.core.agent_tribe import parse_tribe_reference

            if parse_tribe_reference(argument) is not None:
                return None
        except ValueError:
            return None

    try:
        from sase.agent.names import resolve_resume_agent_name

        agent = resolve_resume_agent_name(argument)
        if agent is None:
            return None
        done_path = os.path.join(agent.artifacts_dir, "done.json")
        with open(done_path, encoding="utf-8") as f:
            done_data = json.load(f)
        response_path = done_data.get("response_path")
        if not response_path:
            return None
        expanded = os.path.expanduser(response_path)
        return expanded if os.path.exists(expanded) else None
    except Exception:
        return None


def parse_flat_turns(text: str) -> list[tuple[str, str]]:
    """Parse **User:**/**Assistant:** text into prompt/response tuples."""
    chunks = re.split(r"\*\*User:\*\*\s*", text)
    turns = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = re.split(r"\*\*Assistant:\*\*\s*", chunk, maxsplit=1)
        if len(parts) == 2:
            prompt = parts[0].strip()
            response = re.sub(r"\n---\s*$", "", parts[1]).strip()
            turns.append((prompt, response))
    return turns


def extract_previous_conversation_turns(content: str) -> list[tuple[str, str]]:
    """Extract turns from singular or merged previous-conversation regions."""
    pattern = re.compile(r"^#{1,6}\s+Previous Conversations?\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    all_turns: list[tuple[str, str]] = []
    for match in matches:
        start = match.end()
        heading_level = match.group(0).lstrip().split()[0]
        next_heading = re.search(
            rf"^#{{{1},{len(heading_level)}}}\s",
            content[start:],
            re.MULTILINE,
        )
        end = start + next_heading.start() if next_heading else len(content)
        body = re.sub(r"\n---\s*$", "", content[start:end].strip()).strip()
        all_turns.extend(parse_flat_turns(body))
    return all_turns


def parse_chat_turns(content: str) -> list[tuple[str, str]]:
    """Parse chat markdown into chronological prompt/response turns."""
    heading_pattern = re.compile(r"^(#{1,6})\s+(Prompt|Response)\s*$", re.MULTILINE)
    matches = list(heading_pattern.finditer(content))
    turns: list[tuple[int, str, str]] = []

    index = 0
    while index < len(matches) - 1:
        prompt_match = matches[index]
        response_match = matches[index + 1]
        if prompt_match.group(2) != "Prompt" or response_match.group(2) != "Response":
            index += 1
            continue

        prompt_level = len(prompt_match.group(1))
        if prompt_level != len(response_match.group(1)):
            index += 1
            continue

        prompt_text = content[prompt_match.end() : response_match.start()].strip()
        response_start = response_match.end()
        response_end = (
            matches[index + 2].start() if index + 2 < len(matches) else len(content)
        )
        response_text = content[response_start:response_end].strip()
        response_text = re.sub(r"\n---\s*$", "", response_text).strip()
        turns.append((prompt_level, prompt_text, response_text))
        index += 2

    turns.sort(key=lambda turn: turn[0], reverse=True)
    return [(prompt, response) for _, prompt, response in turns]


def extract_response_from_chat_file(file_ref: str) -> str | None:
    """Extract the most recent response text from a chat file."""
    try:
        content = load_chat_history(file_ref)
    except (FileNotFoundError, OSError):
        return None
    turns = parse_chat_turns(content)
    return turns[-1][1] if turns else None


def load_chat_for_resume(
    file_ref: str,
    _visited: set[str] | None = None,
    *,
    resolve_resume_to_chat_path: ResolveResumeReference = resolve_resume_to_chat_path,
    _share_visited: bool | None = None,
) -> str:
    """Load a chat and flatten recursively referenced conversation turns."""
    share_visited = _visited is not None if _share_visited is None else _share_visited
    visited = set() if _visited is None else _visited
    content = load_chat_history(file_ref)

    if file_ref.startswith("/") or file_ref.startswith("~"):
        absolute_path = os.path.abspath(os.path.expanduser(file_ref))
    else:
        absolute_path = os.path.abspath(
            resolve_chat_file_path(file_ref) or get_chat_file_path(file_ref)
        )
    visited.add(absolute_path)

    turns = parse_chat_turns(content)
    if not turns:
        return content

    expanded_turns: list[tuple[str, str]] = []
    for prompt, response in turns:
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
                if normalized_path and normalized_path not in visited:
                    nested_visited = visited if share_visited else set(visited)
                    nested_text = load_chat_for_resume(
                        normalized_path,
                        nested_visited,
                        resolve_resume_to_chat_path=resolve_resume_to_chat_path,
                        _share_visited=share_visited,
                    )
                    expanded_turns.extend(parse_flat_turns(nested_text))
                elif resolved_path is None:
                    needs_fallback = True
            if needs_fallback:
                expanded_turns.extend(extract_previous_conversation_turns(content))
            prompt = prompt.replace(full_match, "", 1).strip()

        if prompt or response:
            expanded_turns.append((prompt, response))

    parts = []
    for prompt, response in expanded_turns:
        clean_prompt = sanitize_resume_prompt(prompt)
        parts.append(f"**User:**\n\n{clean_prompt}\n\n**Assistant:**\n\n{response}")
    return "\n\n---\n\n".join(parts)
