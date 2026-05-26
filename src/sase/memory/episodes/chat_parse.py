"""Bounded, source-grounded parsing for SASE chat transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from sase.history.chat import find_resume_refs, parse_chat_turns, resolve_chat_file_path

CHAT_EXCERPT_MAX_CHARS = 240

_LINKED_CHATS_HEADING_RE = re.compile(
    r"^#{1,6}\s+Linked Chats\s*$",
    re.MULTILINE,
)
_NEXT_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_BACKTICK_PATH_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass(frozen=True)
class _ChatForkRef:
    """A current or legacy fork/resume directive found in prompt text."""

    full_match: str
    xprompt_name: str
    argument: str
    turn_index: int
    resolved_chat_path: str | None = None


@dataclass(frozen=True)
class _ChatTurnRef:
    """A bounded prompt/response turn reference, not the full transcript body."""

    id: str
    turn_index: int
    prompt_excerpt: str | None = None
    response_excerpt: str | None = None


@dataclass(frozen=True)
class ParsedChatTranscript:
    """Structured references extracted from one chat transcript."""

    path: str
    turns: list[_ChatTurnRef] = field(default_factory=list)
    linked_chat_paths: list[str] = field(default_factory=list)
    fork_refs: list[_ChatForkRef] = field(default_factory=list)


def parse_chat_transcript(path: Path | str) -> ParsedChatTranscript:
    """Parse a chat transcript into turn refs and deterministic graph links."""

    normalized = _normalize_path(path)
    try:
        content = Path(normalized).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ParsedChatTranscript(path=normalized)

    turns = [
        _ChatTurnRef(
            id=f"turn-{index:04d}",
            turn_index=index,
            prompt_excerpt=_bounded_excerpt(prompt),
            response_excerpt=_bounded_excerpt(response),
        )
        for index, (prompt, response) in enumerate(parse_chat_turns(content), 1)
    ]

    fork_refs: list[_ChatForkRef] = []
    for index, (prompt, _response) in enumerate(parse_chat_turns(content), 1):
        for full_match, xprompt_name, argument in find_resume_refs(prompt):
            fork_refs.append(
                _ChatForkRef(
                    full_match=full_match,
                    xprompt_name=xprompt_name,
                    argument=argument,
                    turn_index=index,
                    resolved_chat_path=_resolve_chat_argument(
                        argument,
                        base_dir=Path(normalized).parent,
                    )
                    if xprompt_name in {"fork_by_chat", "resume_by_chat"}
                    else None,
                )
            )

    return ParsedChatTranscript(
        path=normalized,
        turns=turns,
        linked_chat_paths=_extract_linked_chat_paths(
            content,
            base_dir=Path(normalized).parent,
        ),
        fork_refs=fork_refs,
    )


def _extract_linked_chat_paths(content: str, *, base_dir: Path) -> list[str]:
    match = _LINKED_CHATS_HEADING_RE.search(content)
    if match is None:
        return []
    rest = content[match.end() :]
    next_heading = _NEXT_HEADING_RE.search(rest)
    section = rest[: next_heading.start()] if next_heading else rest

    paths: list[str] = []
    seen: set[str] = set()
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        candidates = _BACKTICK_PATH_RE.findall(line)
        candidates.extend(_MARKDOWN_LINK_RE.findall(line))
        if not candidates:
            parts = re.split(r"\s+[—-]\s+", line, maxsplit=1)
            if len(parts) == 2:
                candidates.append(parts[1].strip())
        for candidate in candidates:
            resolved = _resolve_chat_argument(candidate, base_dir=base_dir)
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _resolve_chat_argument(argument: str, *, base_dir: Path) -> str:
    cleaned = argument.strip().strip("<>")
    if cleaned.startswith("file://"):
        cleaned = cleaned.removeprefix("file://")
    if cleaned.startswith("~") or cleaned.startswith("/"):
        return _normalize_path(cleaned)

    local = (base_dir / cleaned).resolve(strict=False)
    if local.exists():
        return str(local)

    resolved = resolve_chat_file_path(cleaned)
    if resolved is not None:
        return _normalize_path(resolved)
    if not cleaned.endswith(".md"):
        resolved_md = resolve_chat_file_path(f"{cleaned}.md")
        if resolved_md is not None:
            return _normalize_path(resolved_md)
    return str(local)


def _bounded_excerpt(text: str) -> str | None:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return None
    if len(collapsed) <= CHAT_EXCERPT_MAX_CHARS:
        return collapsed
    return collapsed[: CHAT_EXCERPT_MAX_CHARS - 3].rstrip() + "..."


def _normalize_path(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


__all__ = [
    "CHAT_EXCERPT_MAX_CHARS",
    "ParsedChatTranscript",
    "parse_chat_transcript",
]
