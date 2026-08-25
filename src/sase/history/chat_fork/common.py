"""Shared helpers for inspecting fork source dicts and formatting Markdown."""

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path

LoadChatForResume = Callable[..., str]


def _fork_source_kind(source: Mapping[str, object]) -> str:
    value = source.get("kind", "agent")
    if value not in {"agent", "proc", "clan", "family"}:
        raise ValueError(f"Unsupported fork source kind: {value!r}")
    return str(value)


def _fork_source_failure(source: Mapping[str, object]) -> Mapping[str, object] | None:
    value = source.get("failure")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Fork source failure metadata must be an object")
    outcome = value.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        raise ValueError("Fork source failure metadata requires an outcome")
    return value


def _fork_member_is_failed(member: Mapping[str, object]) -> bool:
    """Return whether one family member (agent or proc kind) is terminal-failed."""
    if _fork_source_failure(member) is not None:
        return True
    if member.get("kind") != "proc":
        return False
    proc = member.get("proc")
    return isinstance(proc, Mapping) and bool(proc.get("failed"))


def _fork_source_has_failure(source: Mapping[str, object]) -> bool:
    """Return whether one top-level source has a failed agent, proc, or member."""
    if _fork_source_failure(source) is not None:
        return True
    if source.get("kind") == "proc":
        proc = source.get("proc")
        return isinstance(proc, Mapping) and bool(proc.get("failed"))
    if source.get("kind") != "family":
        return False
    raw_members = source.get("members")
    if not isinstance(raw_members, list):
        return False
    return any(
        isinstance(member, Mapping) and _fork_member_is_failed(member)
        for member in raw_members
    )


def _fork_source_has_proc_content(source: Mapping[str, object]) -> bool:
    """Return whether one top-level source itself is, or contains, a proc shell."""
    if source.get("kind") == "proc":
        return True
    if source.get("kind") != "family":
        return False
    raw_members = source.get("members")
    if not isinstance(raw_members, list):
        return False
    return any(
        isinstance(member, Mapping) and member.get("kind") == "proc"
        for member in raw_members
    )


def _require_proc_info(source: Mapping[str, object], name: str) -> Mapping[str, object]:
    proc = source.get("proc")
    if not isinstance(proc, Mapping):
        raise ValueError(f"Proc fork source '{name}' is missing proc metadata")
    return proc


def _fork_source_string(source: Mapping[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Fork source field '{field}' must be a non-empty string")
    return value


def _fork_source_optional_string(
    source: Mapping[str, object],
    field: str,
) -> str | None:
    value = source.get(field)
    return value if isinstance(value, str) and value else None


def _format_text_fence(text: str) -> str:
    max_backticks = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)), default=0
    )
    fence = "`" * max(3, max_backticks + 1)
    return f"{fence}text\n{text}\n{fence}"


def _markdown_code_span(text: str) -> str:
    max_backticks = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)), default=0
    )
    fence = "`" * max(1, max_backticks + 1)
    spacer = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{spacer}{text}{spacer}{fence}"


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


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
