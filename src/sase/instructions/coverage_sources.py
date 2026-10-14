"""Load the native and explicit instruction sources from provider sessions."""

from __future__ import annotations

from pathlib import Path

from sase.instructions import run_index as runs


def session_sources(
    provider: str, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str], bool]:
    """Return ``(native, explicit, partial)`` for one provider session."""
    if provider == "claude":
        from sase.instructions import claude

        for path in runs.find_claude_sessions(run):
            if path.stem == session_id:
                records, partial = runs.read_jsonl_capped(
                    path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
                )
                native, explicit = claude.instruction_sources(records)
                return native, explicit, partial
    elif provider == "codex":
        from sase.instructions import codex

        for path in runs.find_codex_sessions(run):
            if path.stem == session_id:
                records, partial = runs.read_jsonl_capped(
                    path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
                )
                native, explicit = codex.instruction_sources(records)
                return native, explicit, partial
    elif provider == "grok":
        from sase.instructions import grok

        for directory in runs.find_grok_sessions(run):
            if directory.name == session_id:
                context = runs.read_json_object(directory / "prompt_context.json")
                prompt, partial = runs.read_text_capped(
                    directory / "system_prompt.txt",
                    max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP,
                )
                native, explicit = grok.instruction_sources(context, prompt)
                return native, explicit, partial
    elif provider == "muse":
        from sase.instructions import muse
        from sase.llm_provider._muse_session_usage import find_muse_session_log

        log_path = find_muse_session_log(session_id)
        if log_path is not None:
            records, partial = runs.read_jsonl_capped(
                log_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
            )
            native, explicit = muse.instruction_sources(records)
            return native, explicit, partial
    return [], [], False


def claude_helper_sources(path: Path) -> tuple[list[str], list[str], bool]:
    """Return a Claude helper's native and explicit sources plus partial flag."""
    from sase.instructions import claude

    records, partial = runs.read_jsonl_capped(
        path, max_bytes=runs.HELPER_TRANSCRIPT_BYTE_CAP
    )
    native, explicit = claude.instruction_sources(records)
    return native, explicit, partial


__all__ = ["claude_helper_sources", "session_sources"]
