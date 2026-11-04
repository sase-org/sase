"""Formatting for a fork source whose parent agent failed before finishing."""

from collections.abc import Mapping
from pathlib import Path

from .common import (
    LoadChatForResume,
    blockquote,
    fork_source_failure,
    fork_source_optional_string,
    fork_source_string,
    format_text_fence,
    markdown_code_span,
)

_MAX_FAILURE_MESSAGE_CHARS = 4000
_MAX_TRACEBACK_LINES = 20
FAILED_PARENT_GUIDANCE = (
    "One or more parent sections are marked FAILED: those transcripts are "
    "incomplete and their work is unverified — check the marked sections before "
    "relying on anything they claim."
)
HIJACKED_PARENT_GUIDANCE = (
    "Hijacked parent transcripts are unfinished: the user stopped those agents "
    "because they were not making progress, so their work is unverified."
)


def format_hijacked_agent_frame(name: str | None = None) -> str:
    """Return the shared warning that a hijacked transcript is unfinished."""
    agent = f" {markdown_code_span(name)}" if name else ""
    return (
        f"**The user stopped this unfinished agent{agent} because it was not "
        "making progress; it did not finish.** Its transcript is incomplete, and "
        "its work is unverified. Treat it as evidence, not as a completed result."
    )


def format_hijacked_agent_section(
    source: Mapping[str, object],
    name: str,
    *,
    heading: str,
    load_resume_history: LoadChatForResume,
) -> str:
    """Render a hijacked parent section without labeling it as a failure."""
    return f"{heading} (HIJACKED)\n\n" + format_hijacked_agent_body(
        source,
        name,
        load_resume_history=load_resume_history,
    )


def format_hijacked_agent_body(
    source: Mapping[str, object],
    name: str,
    *,
    load_resume_history: LoadChatForResume,
) -> str:
    """Render a hijack notice and the available transcript or launch prompt."""
    rows = [
        format_hijacked_agent_frame(name),
        "",
        f"### Transcript — agent `{name}`",
        "",
    ]
    path = fork_source_optional_string(source, "path")
    if path:
        try:
            history = load_resume_history(path)
        except (OSError, ValueError):
            history = ""
        if history:
            return (
                "\n".join(rows)
                + history
                + "\n\n"
                + (
                    f"**End of transcript — agent `{name}` was stopped before it finished.**"
                )
            )

    rows.append("_No readable transcript was saved for this agent._")
    launch_prompt = _hijacked_launch_prompt(source, path)
    if launch_prompt:
        rows.extend(["", "**Its launch prompt was:**", "", blockquote(launch_prompt)])
    return "\n".join(rows)


def _hijacked_launch_prompt(
    source: Mapping[str, object], transcript_path: str | None
) -> str | None:
    failure = fork_source_failure(source)
    prompt = _failure_string(failure, "launch_prompt") if failure is not None else None
    if prompt:
        return prompt
    artifact_dir = fork_source_optional_string(source, "artifact_dir")
    candidates = [Path(artifact_dir) / "raw_prompt.md"] if artifact_dir else []
    if transcript_path:
        candidates.append(Path(transcript_path).expanduser().parent / "raw_prompt.md")
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if text:
            return text
    return None


def format_failed_agent_section(
    source: Mapping[str, object],
    name: str,
    failure: Mapping[str, object],
    *,
    heading: str,
    load_resume_history: LoadChatForResume,
) -> str:
    return f"{heading} (FAILED)\n\n" + format_failed_agent_body(
        source,
        name,
        failure,
        load_resume_history=load_resume_history,
        heading_level=3,
    )


def format_failed_agent_body(
    source: Mapping[str, object],
    name: str,
    failure: Mapping[str, object],
    *,
    load_resume_history: LoadChatForResume,
    heading_level: int,
) -> str:
    outcome = _failure_string(failure, "outcome") or "unknown"
    intro = (
        f"**The parent agent `{name}` did not finish: it ended with outcome "
        f"`{outcome}`.** Everything below is the transcript of that failed run, "
        "so it is incomplete — the last reply may be missing, truncated, or "
        "describe work that was never finished. Do not assume any of it "
        "succeeded: verify the repository, artifacts, and any claimed results "
        "yourself, and treat diagnosing the failure as part of the New Query "
        "unless told otherwise."
    )
    return "\n\n".join(
        [
            intro,
            _format_failure_block(name, failure, heading_level=heading_level),
            _format_failed_transcript_section(
                source,
                name,
                failure,
                load_resume_history=load_resume_history,
                heading_level=heading_level,
            ),
        ]
    )


def _format_failure_block(
    name: str,
    failure: Mapping[str, object],
    *,
    heading_level: int,
) -> str:
    outcome = _failure_string(failure, "outcome") or "unknown"
    rows = [
        f"{'#' * heading_level} Parent Failure — agent `{name}`",
        "",
        f"- **Outcome:** `{outcome}`",
    ]
    ended_at = _failure_string(failure, "ended_at")
    if ended_at is not None:
        rows.append(f"- **Ended:** `{ended_at}`")

    rows.extend(["", "**Failure message:**", ""])
    error = _failure_string(failure, "error")
    if error is None:
        rows.append("_(none recorded)_")
    else:
        rows.append(format_text_fence(_truncate_failure_message(error)))

    traceback = _failure_string(failure, "traceback")
    if traceback is not None:
        rows.extend(
            [
                "",
                f"**Traceback (last {_MAX_TRACEBACK_LINES} lines):**",
                "",
                format_text_fence(_traceback_tail(traceback)),
            ]
        )
    return "\n".join(rows)


def _format_failed_transcript_section(
    source: Mapping[str, object],
    name: str,
    failure: Mapping[str, object],
    *,
    load_resume_history: LoadChatForResume,
    heading_level: int,
) -> str:
    heading = f"{'#' * heading_level} Transcript — agent `{name}`"
    if _failure_transcript_available(source, failure):
        path = fork_source_string(source, "path")
        history = load_resume_history(path)
        return (
            f"{heading}\n\n{history}\n\n{_format_failed_transcript_end(name, failure)}"
        )

    rows = [
        heading,
        "",
        "_No transcript was saved: the agent failed before it recorded one._",
    ]
    launch_prompt = _failure_string(failure, "launch_prompt")
    if launch_prompt is not None:
        rows.extend(["", "**Its launch prompt was:**", "", blockquote(launch_prompt)])
    return "\n".join(rows)


def _failure_transcript_available(
    source: Mapping[str, object],
    failure: Mapping[str, object],
) -> bool:
    value = failure.get("transcript_available")
    if isinstance(value, bool):
        return value and fork_source_optional_string(source, "path") is not None
    return fork_source_optional_string(source, "path") is not None


def _format_failed_transcript_end(
    name: str,
    failure: Mapping[str, object],
) -> str:
    summary = _failure_summary_line(failure)
    return (
        f"**End of transcript — agent `{name}` failed here: "
        f"{markdown_code_span(summary)}.**"
    )


def _failure_summary_line(failure: Mapping[str, object]) -> str:
    error = _failure_string(failure, "error")
    if error is not None:
        for line in error.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return f"outcome {_failure_string(failure, 'outcome') or 'unknown'}"


def _failure_string(
    failure: Mapping[str, object],
    field: str,
) -> str | None:
    value = failure.get(field)
    return value if isinstance(value, str) and value else None


def _truncate_failure_message(message: str) -> str:
    if len(message) <= _MAX_FAILURE_MESSAGE_CHARS:
        return message
    return message[:_MAX_FAILURE_MESSAGE_CHARS].rstrip() + "\n… (truncated)"


def _traceback_tail(traceback: str) -> str:
    lines = traceback.splitlines()
    if len(lines) <= _MAX_TRACEBACK_LINES:
        return traceback
    return "\n".join(lines[-_MAX_TRACEBACK_LINES:] + ["… (truncated)"])
