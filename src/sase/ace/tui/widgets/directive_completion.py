"""Pure-logic directive completion engine for the prompt input bar."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    filter_agent_completion_candidates,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt._directive_types import (
    AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
    _DIRECTIVE_ALIASES,
    _KNOWN_DIRECTIVES,
)
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import (
    build_model_completion_catalog,
    filter_model_completion_entries,
)

_DIRECTIVE_TOKEN_RE = re.compile(r"^%[A-Za-z0-9_]*$")
_DIRECTIVE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_]")
_DIRECTIVE_OPENING_CONTEXTS = frozenset("([{\"'")
_USER_FACING_DIRECTIVES = frozenset((*_KNOWN_DIRECTIVES, "alt"))


@dataclass(frozen=True, slots=True)
class DirectiveCompletionMetadata:
    """Display metadata for a prompt directive completion candidate."""

    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DirectiveArgCompletionMetadata:
    """Display metadata for a prompt directive argument completion candidate."""

    directive_name: str = ""
    description: str = ""


_DIRECTIVE_ARGUMENT_HINTS: dict[str, str] = {
    "alt": "(variants)",
    "auto": ":argument (e.g. plan|tale|epic)",
    "clan": ":name or (name, tribe=tribe)",
    "effort": ":level",
    "hide": "flag",
    "model": ":model or (model, alias=model)",
    "name": ":agent or (parent, suffix)",
    "repeat": ":count",
    "tribe": ":name",
    "wait": ":agent or (agent, time=5m, runners=1)",
}


_DIRECTIVE_DESCRIPTIONS: dict[str, str] = {
    "alt": "split a prompt into variants; shorthand %{A | B}",
    "auto": "request automatic gate resolution; arguments are gate-specific",
    "clan": "join a named parallel agent clan",
    "effort": "set the reasoning-effort level for this prompt",
    "hide": "hide the agent from the default Agents tab",
    "model": "choose a model and optional launch-family alias overrides",
    "name": "assign an agent name or attach a member to an existing family",
    "repeat": "run the prompt multiple serial iterations",
    "tribe": "assign a user-managed agent tribe",
    "wait": "defer launch for agents, a time floor, or a runner threshold",
}

_EFFORT_ARGUMENT_DESCRIPTIONS: dict[str, str] = {
    "none": "no reasoning-effort override",
    "minimal": "minimal reasoning effort",
    "low": "low reasoning effort",
    "medium": "medium reasoning effort",
    "high": "high reasoning effort",
    "xhigh": "extra-high reasoning effort",
    "max": "maximum reasoning effort",
}

_AUTO_ARGUMENT_DESCRIPTIONS: dict[str, str] = {
    "plan": "plan-gate compatibility alias for normal approval",
    "tale": "plan-gate compatibility alias for SDD tale approval",
    "epic": "plan-gate compatibility alias for SDD epic approval",
}

_DIRECTIVE_ARGUMENT_VALUES: dict[str, tuple[str, ...]] = {
    "effort": EFFORT_LEVELS_ORDERED,
    "auto": AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
}

_DIRECTIVE_ARGUMENT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "effort": _EFFORT_ARGUMENT_DESCRIPTIONS,
    "auto": _AUTO_ARGUMENT_DESCRIPTIONS,
}

_WAIT_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("runners=", "start when at most this many agents are already running"),
    ("time=", "start after a duration or absolute wall-clock time"),
)

_CLAN_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("tribe=", "assign one tribe to the entire clan"),
)


def is_directive_like_token(token: str) -> bool:
    """Return True when token looks like a prompt directive reference."""
    return _DIRECTIVE_TOKEN_RE.fullmatch(token) is not None


def extract_directive_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str] | None:
    """Extract a directive token around a cursor position in one line."""
    col = min(col, len(line))

    token_start = col
    while token_start > 0 and _is_directive_identifier(line[token_start - 1]):
        token_start -= 1

    percent_index = token_start - 1
    if percent_index < 0 or line[percent_index] != "%":
        return None
    if not _has_valid_directive_context(line, percent_index):
        return None

    token_end = col
    while token_end < len(line) and _is_directive_identifier(line[token_end]):
        token_end += 1

    token = line[percent_index:token_end]
    if not is_directive_like_token(token):
        return None
    return percent_index, token_end, token


def extract_directive_arg_token_around_cursor(
    line: str,
    col: int,
) -> tuple[int, int, str, str] | None:
    """Extract a fixed-value directive argument token around the cursor.

    Returns ``(arg_start, arg_end, directive_name, partial)`` where
    ``directive_name`` is canonical and ``arg_start``/``arg_end`` bound the
    replaceable argument value after ``:``.
    """
    col = min(col, len(line))

    percent_index = line.rfind("%", 0, col)
    if percent_index < 0:
        return None
    if not _has_valid_directive_context(line, percent_index):
        return None

    name_start = percent_index + 1
    name_end = name_start
    while name_end < len(line) and _is_directive_identifier(line[name_end]):
        name_end += 1
    if name_end == name_start or name_end >= len(line):
        return None

    raw_name = line[name_start:name_end]
    marker = line[name_end]
    if marker not in {":", "("}:
        return None
    if col <= name_end:
        return None

    directive_name = _canonical_directive_name(raw_name)
    if directive_name is None:
        return None

    if marker == "(":
        if directive_name == "clan":
            return _extract_clan_paren_arg_token(line, col, name_end)
        if directive_name == "wait":
            return _extract_wait_paren_arg_token(line, col, name_end)
        if directive_name == "model":
            return _extract_model_paren_arg_token(line, col, name_end)
        return None

    colon_index = name_end
    if col <= colon_index:
        return None
    if directive_name == "wait":
        return _extract_wait_colon_arg_token(line, col, colon_index)

    arg_start = colon_index + 1
    arg_predicate = _directive_argument_predicate(directive_name)
    if any(not arg_predicate(char) for char in line[arg_start:col]):
        return None

    arg_end = col
    while arg_end < len(line) and arg_predicate(line[arg_end]):
        arg_end += 1

    if directive_name == "model":
        prefix = line[arg_start:col]
        at_index = prefix.rfind("@")
        if at_index >= 0:
            suffix_start = arg_start + at_index + 1
            suffix_end = col
            while suffix_end < len(line) and _is_directive_argument_identifier(
                line[suffix_end]
            ):
                suffix_end += 1
            return suffix_start, suffix_end, "effort", line[suffix_start:suffix_end]

    return arg_start, arg_end, directive_name, line[arg_start:arg_end]


def build_directive_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a directive token."""
    if not is_directive_like_token(token):
        return [], ""

    partial = token[1:]
    partial_lower = partial.lower()
    aliases_by_directive = _aliases_by_directive()
    candidates = [
        CompletionCandidate(
            display=f"%{directive}",
            insertion=f"%{directive}",
            is_dir=False,
            name=directive,
            metadata=DirectiveCompletionMetadata(
                aliases=aliases_by_directive.get(directive, ()),
                argument_hint=_DIRECTIVE_ARGUMENT_HINTS.get(directive, ""),
                description=_DIRECTIVE_DESCRIPTIONS.get(directive, ""),
            ),
        )
        for directive in sorted(_USER_FACING_DIRECTIVES)
        if _matches_directive(directive, aliases_by_directive, partial_lower)
    ]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion[1:] for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def build_directive_arg_completion_candidates(
    directive_name: str,
    partial: str,
    *,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build fixed-value candidates for a directive argument token."""
    if directive_name == "model_alias_key":
        return _build_model_alias_key_completion_candidates(partial)
    if directive_name == "clan_keyword":
        return _build_keyword_completion_candidates(
            partial,
            directive_name="clan",
            keywords=_CLAN_KEYWORD_ARGUMENTS,
        )
    if directive_name == "model_or_alias_key":
        models, _ = _build_model_arg_completion_candidates(partial)
        aliases, _ = _build_model_alias_key_completion_candidates(partial)
        return [*models, *aliases], ""
    canonical = _canonical_directive_name(directive_name)
    if canonical is None:
        return [], ""

    if canonical == "model":
        return _build_model_arg_completion_candidates(partial)
    if canonical == "wait":
        return _build_wait_arg_completion_candidates(partial, agent_candidates)

    values = _DIRECTIVE_ARGUMENT_VALUES.get(canonical)
    if values is None:
        return [], ""

    partial_lower = partial.lower()
    descriptions = _DIRECTIVE_ARGUMENT_DESCRIPTIONS.get(canonical, {})
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value,
            metadata=DirectiveArgCompletionMetadata(
                directive_name=canonical,
                description=descriptions.get(value, ""),
            ),
        )
        for value in values
        if value.lower().startswith(partial_lower)
    ]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def build_agent_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    excluded_names: frozenset[str] = frozenset(),
) -> tuple[list[CompletionCandidate], str]:
    """Build visible-agent candidates for a wait/fork-style argument."""
    if "=" in partial:
        return [], ""

    entries = [
        entry
        for entry in filter_agent_completion_candidates(agent_candidates, partial)
        if entry.name not in excluded_names
    ]
    candidates = [
        CompletionCandidate(
            display=entry.name,
            insertion=entry.name,
            is_dir=False,
            name=entry.name,
            metadata=entry,
        )
        for entry in entries
    ]

    shared_extension = ""
    partial_lower = partial.lower()
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def _build_wait_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
) -> tuple[list[CompletionCandidate], str]:
    """Build agent-name and keyword candidates for ``%wait`` arguments."""
    agents, _ = build_agent_arg_completion_candidates(partial, agent_candidates)
    partial_lower = partial.lower()
    keywords = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value[:-1],
            metadata=DirectiveArgCompletionMetadata(
                directive_name="wait",
                description=description,
            ),
        )
        for value, description in _WAIT_KEYWORD_ARGUMENTS
        if value.lower().startswith(partial_lower)
    ]
    candidates = [*keywords, *agents]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]
    return candidates, shared_extension


def _build_keyword_completion_candidates(
    partial: str,
    *,
    directive_name: str,
    keywords: tuple[tuple[str, str], ...],
) -> tuple[list[CompletionCandidate], str]:
    partial_lower = partial.lower()
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value[:-1],
            metadata=DirectiveArgCompletionMetadata(
                directive_name=directive_name,
                description=description,
            ),
        )
        for value, description in keywords
        if value.lower().startswith(partial_lower)
    ]
    return candidates, ""


def _build_model_arg_completion_candidates(
    partial: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build dynamic candidates for a ``%model`` directive argument token."""
    entries = filter_model_completion_entries(
        build_model_completion_catalog(),
        partial,
    )
    candidates = [
        CompletionCandidate(
            display=entry.display,
            insertion=entry.value,
            is_dir=False,
            name=entry.value,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="model",
                description=entry.description,
            ),
        )
        for entry in entries
    ]

    shared_extension = ""
    partial_lower = partial.lower()
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def _build_model_alias_key_completion_candidates(
    partial: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build ``alias=`` candidates for parenthesized ``%model`` kwargs."""
    from sase.llm_provider.config import model_alias_description, model_alias_names

    partial_lower = partial.lower()
    candidates = [
        CompletionCandidate(
            display=f"{alias}=",
            insertion=f"{alias}=",
            is_dir=False,
            name=alias,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="model",
                description=model_alias_description(alias) or "model alias override",
            ),
        )
        for alias in sorted(model_alias_names())
        if alias.lower().startswith(partial_lower)
    ]
    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]
    return candidates, shared_extension


def _matches_directive(
    directive: str,
    aliases_by_directive: dict[str, tuple[str, ...]],
    partial_lower: str,
) -> bool:
    if directive.lower().startswith(partial_lower):
        return True
    return any(
        alias.startswith(partial_lower) for alias in aliases_by_directive[directive]
    )


def _extract_wait_colon_arg_token(
    line: str,
    col: int,
    colon_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = colon_index + 1
    if not _is_valid_wait_argument_prefix(line[value_start:col]):
        return None
    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1

    if any(
        not _is_wait_directive_argument_identifier(char)
        for char in line[fragment_start:col]
    ):
        return None

    fragment_end = col
    while fragment_end < len(line) and _is_wait_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1

    return fragment_start, fragment_end, "wait", line[fragment_start:fragment_end]


def _extract_wait_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    if ")" in line[value_start:col]:
        return None
    if not _is_valid_wait_argument_prefix(line[value_start:col]):
        return None

    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1

    if any(
        not _is_wait_directive_argument_identifier(char)
        for char in line[fragment_start:col]
    ):
        return None

    fragment_end = col
    while fragment_end < len(line) and _is_wait_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1

    return fragment_start, fragment_end, "wait", line[fragment_start:fragment_end]


def _extract_clan_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    prefix = line[value_start:col]
    if ")" in prefix:
        return None
    comma_index = line.rfind(",", value_start, col)
    if comma_index < value_start:
        return None
    fragment_start = comma_index + 1
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1
    fragment = line[fragment_start:col]
    if "=" in fragment or any(
        not _is_directive_argument_identifier(char) for char in fragment
    ):
        return None
    fragment_end = col
    while fragment_end < len(line) and _is_directive_argument_identifier(
        line[fragment_end]
    ):
        fragment_end += 1
    return (
        fragment_start,
        fragment_end,
        "clan_keyword",
        line[fragment_start:fragment_end],
    )


def _extract_model_paren_arg_token(
    line: str,
    col: int,
    open_index: int,
) -> tuple[int, int, str, str] | None:
    value_start = open_index + 1
    prefix = line[value_start:col]
    if ")" in prefix:
        return None

    fragment_start = line.rfind(",", value_start, col) + 1
    if fragment_start <= 0:
        fragment_start = value_start
    while fragment_start < col and line[fragment_start].isspace():
        fragment_start += 1
    fragment = line[fragment_start:col]

    equals_index = fragment.find("=")
    if equals_index >= 0:
        arg_start = fragment_start + equals_index + 1
        if any(
            not _is_model_directive_argument_identifier(char)
            for char in line[arg_start:col]
        ):
            return None
        arg_end = col
        while arg_end < len(line) and _is_model_directive_argument_identifier(
            line[arg_end]
        ):
            arg_end += 1
        return arg_start, arg_end, "model", line[arg_start:arg_end]

    if any(not _is_model_directive_argument_identifier(char) for char in fragment):
        return None
    arg_end = col
    while arg_end < len(line) and _is_model_directive_argument_identifier(
        line[arg_end]
    ):
        arg_end += 1

    if fragment_start == value_start:
        at_index = fragment.rfind("@")
        if at_index > 0:
            effort_start = fragment_start + at_index + 1
            return effort_start, arg_end, "effort", line[effort_start:arg_end]
        return (
            fragment_start,
            arg_end,
            "model_or_alias_key",
            line[fragment_start:arg_end],
        )
    return fragment_start, arg_end, "model_alias_key", line[fragment_start:arg_end]


def _aliases_by_directive() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {
        directive: [] for directive in _USER_FACING_DIRECTIVES
    }
    for alias, canonical in _DIRECTIVE_ALIASES.items():
        if canonical in grouped:
            grouped[canonical].append(alias)
    return {directive: tuple(sorted(aliases)) for directive, aliases in grouped.items()}


def _canonical_directive_name(raw_name: str) -> str | None:
    canonical = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
    if canonical not in _KNOWN_DIRECTIVES:
        return None
    return canonical


def _has_valid_directive_context(line: str, percent_index: int) -> bool:
    if percent_index == 0:
        return True
    previous = line[percent_index - 1]
    return previous.isspace() or previous in _DIRECTIVE_OPENING_CONTEXTS


def _is_directive_identifier(char: str) -> bool:
    return _DIRECTIVE_IDENTIFIER_RE.fullmatch(char) is not None


def _is_directive_argument_identifier(char: str) -> bool:
    return _is_directive_identifier(char) or char in "-="


def _is_model_directive_argument_identifier(char: str) -> bool:
    return _is_directive_argument_identifier(char) or char in "./@"


def _is_wait_directive_argument_identifier(char: str) -> bool:
    return _is_directive_identifier(char) or char in "-.="


def _is_valid_wait_argument_prefix(prefix: str) -> bool:
    """Return True when prefix is a well-formed (possibly partial) wait list.

    Each comma-separated segment may carry surrounding whitespace but must
    otherwise contain only wait-argument identifier characters. Prose with
    internal spaces before the active fragment is therefore rejected, so a
    later prose comma cannot masquerade as a new comma-separated wait argument.
    """
    for segment in prefix.split(","):
        if any(
            not _is_wait_directive_argument_identifier(char) for char in segment.strip()
        ):
            return False
    return True


def _directive_argument_predicate(directive_name: str) -> Callable[[str], bool]:
    if directive_name == "model":
        return _is_model_directive_argument_identifier
    return _is_directive_argument_identifier
