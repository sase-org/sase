"""Public compatibility façade for SASE chat history management.

The implementation is split by responsibility across ``chat_storage``,
``chat_resume``, and ``chat_fork``. Existing imports remain available here.
"""

from collections.abc import Mapping, Sequence

from sase.core.patch import strip_reverted_suffix
from sase.core.shell import run_shell_command
from sase.core.time import generate_timestamp
from sase.history.chat_fork import (
    build_fork_injected_history as _build_fork_injected_history,
)
from sase.history.chat_resume import (
    extract_previous_conversation_turns as _extract_previous_conversation_turns,
    extract_response_from_chat_file,
    find_resume_ref_groups as _find_resume_ref_groups,
    find_resume_refs as _find_resume_refs,
    load_chat_for_resume as _load_chat_for_resume,
    parse_chat_turns as _parse_chat_turns,
    parse_flat_turns as _parse_flat_turns,
    resolve_resume_to_chat_path as _resolve_resume_to_chat_path,
    sanitize_resume_prompt as _sanitize_resume_prompt,
)
from sase.history.chat_storage import (
    find_chat_by_timestamp,
    format_chat_filename as _format_chat_filename,
    format_metadata_model as _format_metadata_model,
    format_transcript_metadata_blocks as _format_transcript_metadata_blocks,
    get_chat_file_path,
    increment_markdown_headings as _increment_markdown_headings,
    list_chat_histories,
    load_chat_history as _load_chat_history,
    resolve_chat_file_path,
    write_chat_history,
)

__all__ = [
    "_extract_previous_conversation_turns",
    "_find_resume_ref_groups",
    "_find_resume_refs",
    "_format_metadata_model",
    "_format_transcript_metadata_blocks",
    "_get_branch_or_workspace_name",
    "_increment_markdown_headings",
    "_load_chat_history",
    "_parse_chat_turns",
    "_parse_flat_turns",
    "_resolve_resume_to_chat_path",
    "_sanitize_resume_prompt",
    "build_fork_injected_history",
    "extract_response_from_chat_file",
    "find_chat_by_timestamp",
    "generate_chat_filename",
    "get_chat_file_path",
    "list_chat_histories",
    "load_chat_for_resume",
    "resolve_chat_file_path",
    "save_chat_history",
]


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
    """Generate a sanitized chat history filename."""
    if branch_or_workspace is None:
        branch_or_workspace = _get_branch_or_workspace_name()
    if timestamp is None:
        timestamp = generate_timestamp()
    return _format_chat_filename(workflow, agent, branch_or_workspace, timestamp)


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
    """Save a chat history and return its home-relative path."""
    basename = generate_chat_filename(
        workflow,
        agent,
        branch_or_workspace=branch_or_workspace,
        timestamp=timestamp,
    )
    return write_chat_history(
        prompt,
        response,
        workflow,
        basename,
        agent,
        previous_history,
        extra_sections,
        metadata_model=metadata_model,
        metadata_llm_provider=metadata_llm_provider,
        metadata_agent=metadata_agent,
        metadata_multi_agent_prompt=metadata_multi_agent_prompt,
    )


def load_chat_for_resume(
    file_ref: str,
    _visited: set[str] | None = None,
) -> str:
    """Load and flatten a chat, recursively expanding fork references."""
    return _load_chat_for_resume(
        file_ref,
        _visited,
        resolve_resume_to_chat_path=_resolve_resume_to_chat_path,
    )


def build_fork_injected_history(sources: Sequence[Mapping[str, object]]) -> str:
    """Build the context block injected by the ``#fork`` workflow."""
    return _build_fork_injected_history(
        sources,
        load_resume_history=load_chat_for_resume,
        resolve_resume_to_chat_path=_resolve_resume_to_chat_path,
    )
