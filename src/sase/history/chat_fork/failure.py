"""Formatting for a fork source whose parent agent failed before finishing."""

from collections.abc import Mapping

from .common import (
    LoadChatForResume,
    _blockquote,
    _fork_source_optional_string,
    _fork_source_string,
    _format_text_fence,
    _markdown_code_span,
)

_MAX_FAILURE_MESSAGE_CHARS = 4000
_MAX_TRACEBACK_LINES = 20
_FAILED_PARENT_GUIDANCE = (
    "One or more parent sections are marked FAILED: those transcripts are "
    "incomplete and their work is unverified — check the marked sections before "
    "relying on anything they claim."
)


def _format_failed_agent_section(
    source: Mapping[str, object],
    name: str,
    failure: Mapping[str, object],
    *,
    heading: str,
    load_resume_history: LoadChatForResume,
) -> str:
    return f"{heading} (FAILED)\n\n" + _format_failed_agent_body(
        source,
        name,
        failure,
        load_resume_history=load_resume_history,
        heading_level=3,
    )


def _format_failed_agent_body(
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
        rows.append(_format_text_fence(_truncate_failure_message(error)))

    traceback = _failure_string(failure, "traceback")
    if traceback is not None:
        rows.extend(
            [
                "",
                f"**Traceback (last {_MAX_TRACEBACK_LINES} lines):**",
                "",
                _format_text_fence(_traceback_tail(traceback)),
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
        path = _fork_source_string(source, "path")
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
        rows.extend(["", "**Its launch prompt was:**", "", _blockquote(launch_prompt)])
    return "\n".join(rows)


def _failure_transcript_available(
    source: Mapping[str, object],
    failure: Mapping[str, object],
) -> bool:
    value = failure.get("transcript_available")
    if isinstance(value, bool):
        return value and _fork_source_optional_string(source, "path") is not None
    return _fork_source_optional_string(source, "path") is not None


def _format_failed_transcript_end(
    name: str,
    failure: Mapping[str, object],
) -> str:
    summary = _failure_summary_line(failure)
    return (
        f"**End of transcript — agent `{name}` failed here: "
        f"{_markdown_code_span(summary)}.**"
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
