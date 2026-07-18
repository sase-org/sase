"""Chat history management for SASE agents.

This module provides functions to save and load conversation histories
from sase agent runs. Histories are stored in ~/.sase/chats/ with filenames
that encode the branch/workspace, workflow, optional agent name, and timestamp.
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from sase.core.changespec import strip_reverted_suffix
from sase.core.paths import (
    find_sharded_file,
    iter_sharded_files,
    make_safe_filename,
    sharded_path,
)
from sase.core.time import generate_timestamp, get_timezone
from sase.core.shell import run_shell_command
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_METADATA_LABEL


# Matches current #fork / #fork_by_chat refs plus legacy #resume /
# #resume_by_chat refs preserved in historical chat transcripts.
_RESUME_REF_RE = re.compile(
    r"#(fork|fork_by_chat|resume|resume_by_chat)"  # xprompt name
    r"(?:"
    r":(`[^`]+`|[^\s)]+)"  # colon syntax (backtick-quoted or bare)
    r"|"
    r"\((`[^`]+`|[^)]*)\)"  # paren syntax
    r")"
)


# Unrendered Jinja2 markers left literal in stored prompt text (e.g. a source
# xprompt wrapped them in ``{% raw %}``): expression, statement, and comment.
_JINJA_MARKER_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)


def _sanitize_resume_prompt(prompt: str) -> str:
    """Strip sase-specific lingo from a stored user prompt for resume display.

    A forked agent has no way to interpret sase control syntax, so the
    ``# Previous Conversation`` block should read as a clean natural-language
    transcript. This removes, in order (fenced code blocks protected
    throughout so ``%``/``#``/``{{ }}`` inside examples survive):

    1. ``%name`` directives (``%name``, ``%wait``, ``%tribe``/``%t``, ...) and
       ``%xprompts_enabled:false/true`` region markers.
    2. ``#``/``#!`` xprompt & workspace references (``#git:home``, ``#research``,
       ``#fork:...``, ...). Real markdown headings (``# Heading``) are not
       reference matches and are preserved.
    3. Unrendered Jinja2 markers (``{{ }}``, ``{% %}``, ``{# #}``).
    4. Whitespace left behind by the removals.

    Idempotent: sanitizing already-clean text is a no-op. Assistant responses
    are intentionally left untouched by callers (they are model output).
    """
    if not prompt:
        return prompt

    # Lazy imports mirror the existing lazy import of resolve_resume_agent_name
    # and avoid any import-cycle risk with sase.xprompt.
    from sase.xprompt._disabled_regions import strip_disabled_region_markers
    from sase.xprompt._fenced_blocks import (
        protect_fenced_blocks,
        unprotect_fenced_blocks,
    )
    from sase.xprompt._parsing_references import iter_xprompt_references
    from sase.xprompt.directives import strip_known_directives

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    # 1. Strip %-directives and disabled-region markers.
    protected = strip_known_directives(protected)
    protected = strip_disabled_region_markers(protected)

    # 2. Strip #/#! references (remove by offset, last-to-first).
    refs = sorted(
        iter_xprompt_references(protected), key=lambda r: r.start, reverse=True
    )
    for ref in refs:
        protected = protected[: ref.start] + protected[ref.end :]

    # 3. Strip unrendered Jinja2 markers.
    protected = _JINJA_MARKER_RE.sub("", protected)

    # 4. Tidy whitespace left by the removals. Done before restoring fenced
    #    blocks so code-block indentation (carried inside the placeholders) is
    #    never touched.
    protected = re.sub(r"[ \t]+\n", "\n", protected)  # trailing spaces
    protected = re.sub(r"(?m)^[ \t]+", "", protected)  # orphaned leading spaces
    protected = re.sub(r"\n{3,}", "\n\n", protected)  # collapse blank runs

    protected = unprotect_fenced_blocks(protected, fenced_blocks)
    return protected.strip()


def _find_resume_refs(text: str) -> list[tuple[str, str, str]]:
    """Find all current or legacy fork references in text.

    Returns:
        List of (full_match, xprompt_name, argument) tuples.
    """
    results: list[tuple[str, str, str]] = []
    for full_match, xprompt_name, arguments in _find_resume_ref_groups(text):
        results.extend((full_match, xprompt_name, argument) for argument in arguments)
    return results


def _find_resume_ref_groups(text: str) -> list[tuple[str, str, list[str]]]:
    """Return references with every argument attached to its original span."""
    results: list[tuple[str, str, list[str]]] = []
    for m in _RESUME_REF_RE.finditer(text):
        full_match = m.group(0)
        xprompt_name = m.group(1)
        # Argument is in group 2 (colon syntax) or group 3 (paren syntax)
        raw_arg = m.group(2) or m.group(3)
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


def _resolve_resume_to_chat_path(xprompt_name: str, argument: str) -> str | None:
    """Resolve a fork/resume ref to a chat file path.

    For ``fork``/``resume``: looks up the named agent and reads its done.json.
    For ``fork_by_chat``/``resume_by_chat``: returns the argument directly.

    Returns:
        Absolute chat file path, or None on any failure.
    """
    if xprompt_name in {"fork_by_chat", "resume_by_chat"}:
        path = os.path.expanduser(argument)
        if not path.endswith(".md"):
            resolved = resolve_chat_file_path(path)
            return resolved
        return path if os.path.exists(path) else None

    # fork/resume — resolve via agent name
    try:
        from sase.agent.names import resolve_resume_agent_name

        agent = resolve_resume_agent_name(argument)
        if agent is None:
            return None
        import json

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


def _parse_flat_turns(text: str) -> list[tuple[str, str]]:
    """Parse **User:**/**Assistant:** formatted text into (prompt, response) tuples."""
    # Split on **User:** markers
    chunks = re.split(r"\*\*User:\*\*\s*", text)
    turns = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Split on **Assistant:** marker
        parts = re.split(r"\*\*Assistant:\*\*\s*", chunk, maxsplit=1)
        if len(parts) == 2:
            prompt = parts[0].strip()
            response = re.sub(r"\n---\s*$", "", parts[1]).strip()
            turns.append((prompt, response))
    return turns


def _extract_previous_conversation_turns(
    content: str,
) -> list[tuple[str, str]]:
    """Extract turns from singular or merged previous-conversation regions."""
    pattern = re.compile(r"^#{1,6}\s+Previous Conversations?\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    all_turns: list[tuple[str, str]] = []
    for m in matches:
        # Extract body until next same-or-higher-level heading or end
        start = m.end()
        heading_level = m.group(0).lstrip().split()[0]  # e.g. "##"
        next_heading = re.search(
            rf"^#{{{1},{len(heading_level)}}}\s",
            content[start:],
            re.MULTILINE,
        )
        end = start + next_heading.start() if next_heading else len(content)
        body = content[start:end].strip()
        # Strip trailing --- separator
        body = re.sub(r"\n---\s*$", "", body).strip()
        all_turns.extend(_parse_flat_turns(body))
    return all_turns


def _get_branch_or_workspace_name() -> str:
    """Get the current branch name or workspace name."""
    result = run_shell_command("branch_or_workspace_name", capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get branch_or_workspace_name: {result.stderr}")
    return strip_reverted_suffix(result.stdout.strip())


def generate_chat_filename(
    workflow: str,
    agent: str | None = None,
    branch_or_workspace: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Generate a chat history filename.

    Args:
        workflow: The workflow name (e.g., 'run', 'rerun', 'crs')
        agent: Optional agent name within a multi-agent workflow
        branch_or_workspace: Optional branch/workspace name (defaults to current)
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        The full path to the chat history file (without extension for basename usage)
    """
    if branch_or_workspace is None:
        branch_or_workspace = _get_branch_or_workspace_name()
    if timestamp is None:
        timestamp = generate_timestamp()

    # Sanitize user/project/workflow-derived parts before joining so path-like
    # labels such as "~/org" remain a single filename component.
    parts = [
        make_safe_filename(branch_or_workspace),
        make_safe_filename(workflow),
    ]
    if agent is not None:
        parts.append(make_safe_filename(agent))
    parts.append(timestamp)

    # Join with dashes
    basename = "-".join(parts)

    return basename


def get_chat_file_path(basename: str) -> str:
    """Return the sharded write path for a chat history file.

    For reads, prefer :func:`resolve_chat_file_path` which also handles
    legacy (unsharded) paths and cross-shard lookup.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    return sharded_path("chats", basename, ensure=False)


def resolve_chat_file_path(basename: str) -> str | None:
    """Find an existing chat history file by basename.

    Checks the expected shard (from the filename timestamp), legacy
    top-level, and finally scans all shards.  Returns ``None`` if no
    matching file exists.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    return find_sharded_file("chats", basename)


def _clean_metadata_field(value: str | None) -> str | None:
    """Normalize a transcript metadata field for compact markdown output."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _format_metadata_model(
    metadata_llm_provider: str | None,
    metadata_model: str | None,
) -> str | None:
    """Format transcript provider/model metadata without inventing unknowns."""
    provider = _clean_metadata_field(metadata_llm_provider)
    model = _clean_metadata_field(metadata_model)
    if provider and model:
        if model.startswith(f"{provider}/"):
            return model
        return f"{provider}/{model}"
    return model or provider


def _format_transcript_metadata_blocks(
    *,
    display_timestamp: str,
    metadata_model: str | None,
    metadata_llm_provider: str | None,
    metadata_agent: str | None,
    metadata_multi_agent_prompt: str | None,
) -> str:
    rows = [f"- **TIMESTAMP:** {display_timestamp}"]
    model = _format_metadata_model(metadata_llm_provider, metadata_model)
    agent = _clean_metadata_field(metadata_agent)
    multi_agent_prompt = _clean_metadata_field(metadata_multi_agent_prompt)
    if model:
        rows.append(f"- **MODEL:** {model}")
    if agent:
        rows.append(f"- **AGENT:** {agent}")
    if multi_agent_prompt:
        rows.append(
            f"- **{MULTI_AGENT_PROMPT_METADATA_LABEL}:** `{multi_agent_prompt}`"
        )
    return "\n".join(rows)


def save_chat_history(
    prompt: str,
    response: str,
    workflow: str,
    agent: str | None = None,
    previous_history: str | None = None,
    timestamp: str | None = None,
    extra_sections: str | None = None,
    branch_or_workspace: str | None = None,
    *,
    metadata_model: str | None = None,
    metadata_llm_provider: str | None = None,
    metadata_agent: str | None = None,
    metadata_multi_agent_prompt: str | None = None,
) -> str:
    """Save a chat history to a file.

    Args:
        prompt: The prompt sent to the agent
        response: The response from the agent
        workflow: The workflow name
        agent: Optional agent name for multi-agent workflows
        previous_history: Optional previous conversation history to prepend
        timestamp: Optional timestamp for filename (YYmmdd_HHMMSS format)
        extra_sections: Optional markdown content (plan feedback, Q&A) to
            insert after transcript metadata and before the prompt.
        branch_or_workspace: Optional branch/workspace name for filename.
        metadata_model: Optional model name to render in the transcript header.
        metadata_llm_provider: Optional LLM provider to render with the model.
        metadata_agent: Optional SASE agent name to render in the transcript header.
        metadata_multi_agent_prompt: Optional path to the full multi-agent
            prompt file to render in the transcript header.

    Returns:
        The full path to the saved chat history file
    """
    basename = generate_chat_filename(
        workflow, agent, branch_or_workspace=branch_or_workspace, timestamp=timestamp
    )
    # get_chat_file_path returns the sharded write location (not ensured).
    file_path = sharded_path(
        "chats",
        basename if basename.endswith(".md") else f"{basename}.md",
    )

    display_timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")

    # Build content
    content_parts = []

    # Add header
    content_parts.append(f"# Chat History - {workflow}")
    if agent:
        content_parts.append(f" ({agent})")
    metadata_blocks = _format_transcript_metadata_blocks(
        display_timestamp=display_timestamp,
        metadata_model=metadata_model,
        metadata_llm_provider=metadata_llm_provider,
        metadata_agent=metadata_agent,
        metadata_multi_agent_prompt=metadata_multi_agent_prompt,
    )
    content_parts.append(f"\n\n{metadata_blocks}\n")

    # Add extra sections (plan feedback, Q&A) before prompt
    if extra_sections:
        content_parts.append(f"\n{extra_sections}\n")

    # Add previous history if present
    if previous_history:
        content_parts.append("\n## Previous Conversation\n\n")
        content_parts.append(previous_history)
        content_parts.append("\n\n---\n")

    # Add current prompt and response
    content_parts.append("\n## Prompt\n\n")
    content_parts.append(prompt)
    content_parts.append("\n\n## Response\n\n")
    content_parts.append(response)
    content_parts.append("\n")

    content = "".join(content_parts)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Return path with ~ for home directory
    return file_path.replace(str(Path.home()), "~")


def _increment_markdown_headings(content: str) -> str:
    """Increment all markdown heading levels by one.

    Args:
        content: The markdown content to process

    Returns:
        Content with all heading levels incremented (# -> ##, ## -> ###, etc.)
    """
    lines = content.split("\n")
    result_lines = []

    for line in lines:
        # Check if line starts with markdown heading
        if line.startswith("#"):
            # Add one more # to increment the heading level
            result_lines.append("#" + line)
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


def _parse_chat_turns(content: str) -> list[tuple[str, str]]:
    """Parse chat history content into chronological (prompt, response) turns.

    Finds all Prompt/Response heading pairs at any markdown heading level,
    extracts their content, and sorts by heading depth (deepest = oldest)
    to produce chronological order.

    Args:
        content: Raw markdown content from a chat history file.

    Returns:
        List of (prompt_text, response_text) tuples in chronological order.
    """
    heading_pattern = re.compile(r"^(#{1,6})\s+(Prompt|Response)\s*$", re.MULTILINE)
    matches = list(heading_pattern.finditer(content))

    turns: list[tuple[int, str, str]] = []  # (level, prompt_text, response_text)

    i = 0
    while i < len(matches) - 1:
        m_prompt = matches[i]
        m_response = matches[i + 1]

        # Expect Prompt followed by Response at the same heading level
        if m_prompt.group(2) != "Prompt" or m_response.group(2) != "Response":
            i += 1
            continue

        prompt_level = len(m_prompt.group(1))
        response_level = len(m_response.group(1))
        if prompt_level != response_level:
            i += 1
            continue

        # Extract prompt text
        prompt_text = content[m_prompt.end() : m_response.start()].strip()

        # Extract response text (until next match or end of content)
        response_start = m_response.end()
        response_end = matches[i + 2].start() if i + 2 < len(matches) else len(content)
        response_text = content[response_start:response_end].strip()

        # Strip trailing --- separator
        response_text = re.sub(r"\n---\s*$", "", response_text).strip()

        turns.append((prompt_level, prompt_text, response_text))
        i += 2

    # Sort by depth (deepest = oldest → first in chronological order)
    turns.sort(key=lambda t: t[0], reverse=True)

    return [(prompt, response) for _, prompt, response in turns]


def extract_response_from_chat_file(file_ref: str) -> str | None:
    """Extract the most recent response text from a chat file.

    Args:
        file_ref: Either a basename or full path to the chat history file.

    Returns:
        The most recent response text, or None if the file can't be read or parsed.
    """
    try:
        content = _load_chat_history(file_ref)
    except (FileNotFoundError, OSError):
        return None
    turns = _parse_chat_turns(content)
    if not turns:
        return None
    return turns[-1][1]  # last turn = most recent response


def load_chat_for_resume(
    file_ref: str,
    _visited: set[str] | None = None,
) -> str:
    """Load a chat history file and format it as flat turns for resume.

    Loads the file without heading increment, parses all (prompt, response)
    turns in chronological order, and formats them with bold markers instead
    of heading levels to prevent heading inflation on repeated resumes.

    Recursively expands current ``#fork`` / ``#fork_by_chat`` references and
    legacy ``#resume`` / ``#resume_by_chat`` references found in prompt text,
    inlining the referenced conversation history.

    Args:
        file_ref: Either a basename or full path to the chat history file.
        _visited: Internal cycle-detection set of resolved file paths.

    Returns:
        Formatted string with flat **User:**/**Assistant:** turns.
    """
    if _visited is None:
        _visited = set()

    content = _load_chat_history(file_ref)

    # Resolve file_ref to an absolute path for cycle detection
    if file_ref.startswith("/") or file_ref.startswith("~"):
        abs_path = os.path.abspath(os.path.expanduser(file_ref))
    else:
        abs_path = os.path.abspath(
            resolve_chat_file_path(file_ref) or get_chat_file_path(file_ref)
        )
    _visited.add(abs_path)

    turns = _parse_chat_turns(content)

    if not turns:
        return content  # Fallback to raw content if parsing fails

    expanded_turns: list[tuple[str, str]] = []
    for prompt, response in turns:
        # Keep the historical flattened detector as a compatibility view;
        # grouped records retain each multi-parent invocation's original span.
        refs = _find_resume_ref_groups(prompt) if _find_resume_refs(prompt) else []
        for full_match, xprompt_name, arguments in refs:
            needs_fallback = False
            for argument in arguments:
                resolved_path = _resolve_resume_to_chat_path(xprompt_name, argument)
                normalized_path = (
                    os.path.abspath(os.path.expanduser(resolved_path))
                    if resolved_path
                    else None
                )
                if normalized_path and normalized_path not in _visited:
                    # Each fork parent gets an independent ancestry guard so
                    # shared history remains present in every conversation.
                    nested_text = load_chat_for_resume(normalized_path, set(_visited))
                    nested_turns = _parse_flat_turns(nested_text)
                    expanded_turns.extend(nested_turns)
                elif resolved_path is None:
                    needs_fallback = True
            if needs_fallback:
                # A stored expanded prompt is the recovery source when one or
                # more historical agent references no longer resolve.
                fallback_turns = _extract_previous_conversation_turns(content)
                expanded_turns.extend(fallback_turns)
            # Strip the complete multi-parent reference exactly once.
            prompt = prompt.replace(full_match, "", 1).strip()

        if prompt or response:
            expanded_turns.append((prompt, response))

    parts = []
    for prompt, response in expanded_turns:
        clean_prompt = _sanitize_resume_prompt(prompt)
        parts.append(f"**User:**\n\n{clean_prompt}\n\n**Assistant:**\n\n{response}")

    return "\n\n---\n\n".join(parts)


def build_fork_injected_history(sources: Sequence[Mapping[str, object]]) -> str:
    """Build the context block injected by the ``#fork`` workflow.

    Plain agent sources retain the established single- and multi-parent
    envelopes. Clan sources include every member's sanitized prompts plus
    reply statistics and artifact metadata; full clan-member reply text is
    deliberately omitted so a child can choose which transcript merits the
    added context cost.
    """
    if not sources:
        raise ValueError("Fork history requires at least one source")

    if len(sources) == 1 and _fork_source_kind(sources[0]) == "agent":
        history = load_chat_for_resume(_fork_source_string(sources[0], "path"))
        return _wrap_fork_history("# Previous Conversation", history)

    if all(_fork_source_kind(source) == "agent" for source in sources):
        count = len(sources)
        sections = []
        for index, source in enumerate(sources, start=1):
            name = _fork_source_string(source, "name")
            history = load_chat_for_resume(_fork_source_string(source, "path"))
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
            "# Previous Conversations", f"{guidance}\n\n{'\n\n'.join(sections)}"
        )

    count = len(sources)
    sections = [
        _format_fork_source(source, index=index, count=count)
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
        "# Previous Conversations", f"{guidance}\n\n{'\n\n'.join(sections)}"
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


def _format_fork_source(source: Mapping[str, object], *, index: int, count: int) -> str:
    kind = _fork_source_kind(source)
    name = _fork_source_string(source, "name")
    if kind == "agent":
        history = load_chat_for_resume(_fork_source_string(source, "path"))
        return f"## Source {index} of {count} — agent `{name}`\n\n{history}"
    return _format_clan_fork_source(source, index=index, count=count)


def _format_clan_fork_source(
    source: Mapping[str, object], *, index: int, count: int
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
        _format_clan_member(member, index=member_index, count=len(members))
        for member_index, member in enumerate(members, start=1)
    ]
    return "\n".join(header_rows) + "\n\n" + "\n\n".join(member_blocks)


def _require_fork_member(value: object, clan_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Clan fork source '{clan_name}' has an invalid member")
    return value


def _format_clan_member(member: Mapping[str, object], *, index: int, count: int) -> str:
    name = _fork_source_string(member, "name")
    path = _fork_source_string(member, "path")
    artifact_dir = Path(_fork_source_string(member, "artifact_dir"))
    content = _load_chat_history(path)
    turns = _parse_chat_turns(content)
    word_count = sum(len(response.split()) for _, response in turns)
    line_count = sum(len(response.splitlines()) for _, response in turns if response)

    meta = _load_json_object(artifact_dir / "agent_meta.json")
    done = _load_json_object(artifact_dir / "done.json")
    outcome = _json_string(done, "outcome") or "unknown"
    model = (
        _format_metadata_model(
            _json_string(meta, "llm_provider"),
            _json_string(meta, "model"),
        )
        or "unknown"
    )
    prompts = _load_fork_member_prompts(path)
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
        f"### Member {index} of {count} — agent `{name}`\n\n"
        f"{summary}\n\n{'\n\n'.join(prompt_blocks)}"
    )


def _load_fork_member_prompts(
    file_ref: str, _visited: set[str] | None = None
) -> list[str]:
    """Load sanitized prompts recursively while omitting every reply body."""
    visited = set() if _visited is None else _visited
    content = _load_chat_history(file_ref)
    if file_ref.startswith("/") or file_ref.startswith("~"):
        absolute_path = os.path.abspath(os.path.expanduser(file_ref))
    else:
        absolute_path = os.path.abspath(
            resolve_chat_file_path(file_ref) or get_chat_file_path(file_ref)
        )
    if absolute_path in visited:
        return []
    visited.add(absolute_path)

    prompts: list[str] = []
    for prompt, _response in _parse_chat_turns(content):
        refs = _find_resume_ref_groups(prompt) if _find_resume_refs(prompt) else []
        for full_match, xprompt_name, arguments in refs:
            needs_fallback = False
            for argument in arguments:
                resolved_path = _resolve_resume_to_chat_path(xprompt_name, argument)
                normalized_path = (
                    os.path.abspath(os.path.expanduser(resolved_path))
                    if resolved_path
                    else None
                )
                if resolved_path is not None and normalized_path not in visited:
                    try:
                        prompts.extend(
                            _load_fork_member_prompts(resolved_path, set(visited))
                        )
                    except OSError:
                        needs_fallback = True
                elif resolved_path is None:
                    needs_fallback = True
            if needs_fallback:
                prompts.extend(
                    clean
                    for fallback_prompt, _ in _extract_previous_conversation_turns(
                        content
                    )
                    if (clean := _sanitize_resume_prompt(fallback_prompt))
                )
            prompt = prompt.replace(full_match, "", 1).strip()

        clean_prompt = _sanitize_resume_prompt(prompt)
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


def _load_chat_history(file_ref: str, increment_headings: bool = False) -> str:
    """Load a chat history from a file.

    Args:
        file_ref: Either a basename (e.g., 'foobar_run_251128104155')
                  or a full path (e.g., '~/.sase/chats/foobar_run_251128104155.md')
        increment_headings: If True, increment all markdown heading levels by one

    Returns:
        The content of the chat history file
    """
    # Handle full paths
    if file_ref.startswith("/") or file_ref.startswith("~"):
        file_path = os.path.expanduser(file_ref)
    else:
        # Treat as basename — search shards + legacy top-level.
        resolved = resolve_chat_file_path(file_ref)
        if resolved is None:
            raise FileNotFoundError(f"Chat history file not found: {file_ref}")
        file_path = resolved

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Chat history file not found: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    if increment_headings:
        content = _increment_markdown_headings(content)

    return content


def list_chat_histories() -> list[str]:
    """List all available chat history basenames.

    Returns:
        A list of chat history basenames (without .md extension),
        sorted by modification time (most recent first).
    """
    entries: list[tuple[str, float]] = []
    for p in iter_sharded_files("chats", pattern="*.md"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        entries.append((p.name[:-3], mtime))
    entries.sort(key=lambda e: e[1], reverse=True)
    return [name for name, _ in entries]


def find_chat_by_timestamp(timestamp: str) -> str | None:
    """Find a chat history file by its timestamp suffix.

    Returns the path (with ~ for home) or None if not found.
    """
    suffix = f"-{timestamp}.md"
    for p in iter_sharded_files("chats", pattern="*.md"):
        if p.name.endswith(suffix):
            return str(p).replace(str(Path.home()), "~")
    return None
