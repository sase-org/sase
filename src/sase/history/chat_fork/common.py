"""Shared helpers for inspecting fork source dicts and formatting Markdown."""

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path

LoadChatForResume = Callable[..., str]


# legacy agent-family spelling: pre-rename fork sources carry ``kind:
# "family"``; new writers emit only ``"session"``.
LEGACY_FORK_SOURCE_KIND = "family"


def fork_source_kind(source: Mapping[str, object]) -> str:
    value = source.get("kind", "agent")
    if value == LEGACY_FORK_SOURCE_KIND:
        return "session"
    if value not in {"agent", "proc", "clan", "session"}:
        raise ValueError(f"Unsupported fork source kind: {value!r}")
    return str(value)


def fork_source_failure(source: Mapping[str, object]) -> Mapping[str, object] | None:
    value = source.get("failure")
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Fork source failure metadata must be an object")
    outcome = value.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        raise ValueError("Fork source failure metadata requires an outcome")
    return value


def fork_source_hijack_status(source: Mapping[str, object]) -> str | None:
    """Classify a hijacked agent from its durable done marker through Rust."""
    if source.get("kind", "agent") != "agent":
        return None
    done: Mapping[str, object] = {}
    artifact_dir = fork_source_optional_string(source, "artifact_dir")
    if artifact_dir:
        done = load_json_object(Path(artifact_dir).expanduser() / "done.json")
    if not done:
        transcript = fork_source_optional_string(source, "path")
        if transcript:
            done = load_json_object(Path(transcript).expanduser().parent / "done.json")

    failure = fork_source_failure(source)
    outcome = source.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        outcome = failure.get("outcome") if failure is not None else None
    if not isinstance(outcome, str) or not outcome:
        outcome = done.get("outcome")
    recovery = source.get("recovery")
    if not isinstance(recovery, Mapping):
        recovery = done.get("recovery")
    if not isinstance(recovery, Mapping):
        recovery = None
    if not isinstance(outcome, str) or not outcome:
        return None

    from sase.agent.hijack.core import agent_hijack_status_for_done_marker

    return agent_hijack_status_for_done_marker(outcome, recovery)


def fork_source_has_hijack(source: Mapping[str, object]) -> bool:
    """Return whether an agent source or one of its session members was hijacked."""
    if fork_source_hijack_status(source) is not None:
        return True
    if source.get("kind") not in ("session", LEGACY_FORK_SOURCE_KIND):
        return False
    members = source.get("members")
    return isinstance(members, list) and any(
        isinstance(member, Mapping) and fork_source_hijack_status(member) is not None
        for member in members
    )


#: Terminal gate states that read as a failure, mirroring
#: ``sase.gate_turn.state.TERMINAL_GATE_STATES``'s failing members. Kept as a
#: local literal so this generic history module never imports the domain
#: gate-turn package.
GATE_FAILURE_OUTCOMES = frozenset({"failed", "timeout", "lost"})


def _fork_member_is_failed(member: Mapping[str, object]) -> bool:
    """Return whether one agent-session member (agent, proc, or gate kind) failed."""
    if fork_source_failure(member) is not None:
        return True
    kind = member.get("kind")
    if kind == "proc":
        proc = member.get("proc")
        return isinstance(proc, Mapping) and bool(proc.get("failed"))
    if kind == "gate":
        return member.get("outcome") in GATE_FAILURE_OUTCOMES
    return False


def fork_source_has_failure(source: Mapping[str, object]) -> bool:
    """Return whether one top-level source has a failed agent, proc, or member."""
    if fork_source_failure(source) is not None:
        return True
    if source.get("kind") == "proc":
        proc = source.get("proc")
        return isinstance(proc, Mapping) and bool(proc.get("failed"))
    # legacy agent-family spelling: pre-rename sources carry "family".
    if source.get("kind") not in ("session", LEGACY_FORK_SOURCE_KIND):
        return False
    raw_members = source.get("members")
    if not isinstance(raw_members, list):
        return False
    return any(
        isinstance(member, Mapping) and _fork_member_is_failed(member)
        for member in raw_members
    )


def fork_source_has_proc_content(source: Mapping[str, object]) -> bool:
    """Return whether one top-level source itself is, or contains, a named proc."""
    if source.get("kind") == "proc":
        return True
    # legacy agent-family spelling: pre-rename sources carry "family".
    if source.get("kind") not in ("session", LEGACY_FORK_SOURCE_KIND):
        return False
    raw_members = source.get("members")
    if not isinstance(raw_members, list):
        return False
    return any(
        isinstance(member, Mapping) and member.get("kind") == "proc"
        for member in raw_members
    )


def require_proc_info(source: Mapping[str, object], name: str) -> Mapping[str, object]:
    proc = source.get("proc")
    if not isinstance(proc, Mapping):
        raise ValueError(f"Proc fork source '{name}' is missing proc metadata")
    return proc


def fork_source_string(source: Mapping[str, object], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Fork source field '{field}' must be a non-empty string")
    return value


def fork_source_optional_string(
    source: Mapping[str, object],
    field: str,
) -> str | None:
    value = source.get(field)
    return value if isinstance(value, str) and value else None


def format_text_fence(text: str) -> str:
    from sase.llm_provider.continuation_budget_spans import sanitize_span_text

    text = sanitize_span_text(text)
    max_backticks = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)), default=0
    )
    fence = "`" * max(3, max_backticks + 1)
    return f"{fence}text\n{text}\n{fence}"


def markdown_code_span(text: str) -> str:
    max_backticks = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)), default=0
    )
    fence = "`" * max(1, max_backticks + 1)
    spacer = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{spacer}{text}{spacer}{fence}"


def blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def load_json_object(path: Path) -> Mapping[str, object]:
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def json_string(data: Mapping[str, object], field: str) -> str | None:
    value = data.get(field)
    return value if isinstance(value, str) and value else None
