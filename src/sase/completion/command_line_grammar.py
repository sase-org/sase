"""Thin adapter over ``sase_core_rs.CommandLineGrammar``.

All parsing, ranking, diagnostics, and run-policy logic lives in sase-core
(``crates/sase_core/src/command_line/``). This module only loads the frozen
Rust handle and exposes typed zero-copy views over the dicts it returns.

Offsets on the wire are Unicode scalar (char) offsets, exactly Python ``str``
indexes. The resolver treats every value-taking option as taking one value:
the spec does not carry option ``nargs``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, NotRequired, TypedDict, cast

COMMAND_LINE_GRAMMAR_SCHEMA_VERSION: Final = 1


class LineToken(TypedDict):
    """One lexed token with its resolver role."""

    text: str
    start: int
    end: int
    role: str
    quoted: bool
    unterminated: bool


class LineSlot(TypedDict):
    """The cursor slot classification."""

    kind: str
    dest: str | None
    value_kind: str | None
    choices: list[str] | None
    value_hint: str | None
    prefix: str
    replace_start: int
    replace_end: int


class LineDiagnostic(TypedDict):
    """One advisory diagnostic (never blocking)."""

    start: int
    end: int
    severity: str
    code: str
    message: str


class SignatureSegment(TypedDict):
    """One usage segment with its active/required flags."""

    text: str
    role: str
    active: bool
    required: bool


class LineSignature(TypedDict):
    """The live signature line."""

    segments: list[SignatureSegment]
    summary: str


class RunPolicyOutcome(TypedDict):
    """The evaluated run policy for the resolved node."""

    policy: str
    note: str | None


class LineContext(TypedDict):
    """The full per-keystroke resolver response."""

    tokens: list[LineToken]
    argv: list[str]
    path: list[str]
    node_kind: str
    slot: LineSlot
    used_dests: list[str]
    diagnostics: list[LineDiagnostic]
    signature: LineSignature
    run_policy: RunPolicyOutcome
    writes: bool
    confirms: bool
    confirm_flag_present: bool
    stdin: bool
    schema_version: int


class DynamicCandidate(TypedDict):
    """One caller-supplied completion candidate."""

    value: str
    display: NotRequired[str | None]
    description: NotRequired[str | None]
    badge: NotRequired[str | None]
    source: NotRequired[str | None]
    partial: NotRequired[bool | None]


class CompletionItem(TypedDict):
    """One ranked completion row."""

    insert_text: str
    display: str
    description: str
    badge: str
    source: str
    match_runs: list[list[int]]
    selected: bool


class CommandLineCompletion(TypedDict):
    """The ranked completion response for the cursor slot."""

    replace_start: int
    replace_end: int
    items: list[CompletionItem]
    total: int
    kind: str
    schema_version: int


class HelpPositional(TypedDict):
    """One positional row in command help."""

    metavar: str
    dest: str
    summary: str
    nargs: Any
    required: bool
    choices: list[str] | None
    value_kind: str | None
    value_hint: str | None


class HelpOption(TypedDict):
    """One option row in command help."""

    strings: list[str]
    dest: str
    summary: str
    metavar: str | None
    takes_value: bool
    required: bool
    repeatable: bool
    default: str | None
    choices: list[str] | None
    value_kind: str | None
    value_hint: str | None


class HelpChild(TypedDict):
    """One subcommand row in command help."""

    name: str
    aliases: list[str]
    summary: str


class CommandHelp(TypedDict):
    """The static help view for one command path."""

    usage: str
    summary: str
    positionals: list[HelpPositional]
    options: list[HelpOption]
    children: list[HelpChild]
    default_child: str | None
    run_policy: list[dict[str, Any]]
    writes: bool
    stdin: bool
    confirms: bool


@dataclass(frozen=True, slots=True)
class CommandLineGrammar:
    """A frozen ``sase_core_rs.CommandLineGrammar`` handle."""

    _handle: Any

    @classmethod
    def from_spec_json(cls, text: str) -> CommandLineGrammar:
        """Build a grammar from full-descriptions spec JSON."""
        from sase.core.rust import require_rust_binding

        handle = require_rust_binding("CommandLineGrammar")(text)
        if handle.SCHEMA_VERSION != COMMAND_LINE_GRAMMAR_SCHEMA_VERSION:
            raise RuntimeError(
                "CommandLineGrammar schema mismatch: rust "
                f"{handle.SCHEMA_VERSION} != "
                f"python {COMMAND_LINE_GRAMMAR_SCHEMA_VERSION}"
            )
        return cls(_handle=handle)

    def resolve(self, line: str, cursor: int) -> LineContext:
        """Return the resolver context for *line* at *cursor*."""
        return cast(LineContext, self._handle.resolve(line, cursor))

    def complete(
        self,
        line: str,
        cursor: int,
        *,
        dynamic: Sequence[DynamicCandidate] = (),
        selected: Sequence[str] = (),
        limit: int = 100,
    ) -> CommandLineCompletion:
        """Return ranked candidates for the cursor slot."""
        return cast(
            CommandLineCompletion,
            self._handle.complete(
                line,
                cursor,
                [dict(candidate) for candidate in dynamic],
                list(selected),
                limit,
            ),
        )

    def command_help(self, path: Sequence[str]) -> CommandHelp | None:
        """Return the help view for *path*, or ``None`` when unknown."""
        result = self._handle.command_help(list(path))
        return None if result is None else cast(CommandHelp, result)

    def __len__(self) -> int:
        return len(self._handle)


def load_command_line_grammar(path: Path) -> CommandLineGrammar:
    """Load a grammar from a spec JSON file.

    Call only from a worker thread: it does file I/O and parses the ~0.5 MB
    cached ``sase completion spec -d -j`` document.
    """
    return CommandLineGrammar.from_spec_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "COMMAND_LINE_GRAMMAR_SCHEMA_VERSION",
    "CommandHelp",
    "CommandLineCompletion",
    "CommandLineGrammar",
    "CompletionItem",
    "DynamicCandidate",
    "HelpChild",
    "HelpOption",
    "HelpPositional",
    "LineContext",
    "LineDiagnostic",
    "LineSignature",
    "LineSlot",
    "LineToken",
    "RunPolicyOutcome",
    "SignatureSegment",
    "load_command_line_grammar",
]
