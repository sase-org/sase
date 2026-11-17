"""Source-aware command-substitution policy adapter.

Thin Python glue over the ``sase_core`` prompt-command-substitution policy
(see the linked ``sase-core`` repo,
``crates/sase_core/src/prompt_command_substitution/``). The Rust core owns
the source-versus-rendered eligibility rule and balanced command-span
planning; this module owns Jinja-adjacent orchestration that must stay in
Python: launch-authorship resolution, UTF-8/``str`` offset conversion,
subprocess execution through :func:`sase.file_references._execute_cmd_cached`,
and generated-text guard tokens that keep interpolated data and command
stdout out of later execution passes.

The central rule: only complete command expressions present in authorized
source may execute (human-authored prompt text or an admitted
macro/workflow definition in a human launch). Context values, rendered
text, and command stdout are data regardless of their content and must
never reach an execution pass.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from sase.macro._disabled_regions import disabled_region_ranges
from sase.macro._exceptions import MacroError
from sase.macro._fenced_blocks import fenced_block_ranges

#: Launch-authorship stamp read from the process environment. Scoped to
#: prompt preprocessing; an in-process successor may carry a different value
#: than the launch envelope. Unset means human: direct human-facing
#: preprocessing commands may have no launch envelope, while agent
#: subprocesses always receive an explicit stamp from a launch funnel.
LAUNCH_AUTHORSHIP_ENV = "SASE_PROMPT_AUTHORSHIP"

LaunchAuthorship = Literal["human", "agent"]


class PromptTextKind(Enum):
    """Provenance of the text handed to a command-substitution boundary."""

    #: Human-authored prompt source (the raw submitted prompt).
    HUMAN_SOURCE = "human_source"
    #: An admitted macro or workflow definition rendered in a human launch.
    ADMITTED_DEFINITION = "admitted_definition"
    #: Already-rendered or otherwise produced data. Never eligible, even in
    #: a human launch.
    GENERATED = "generated"

    @property
    def is_source(self) -> bool:
        """Whether text of this kind may carry executable commands."""
        return self is not PromptTextKind.GENERATED


@dataclass(frozen=True)
class CmdsubProvenance:
    """Explicit provenance for one command-substitution boundary.

    ``kind`` names what the text is; ``launch_authorship`` names who
    launched the pipeline. Execution requires source-kind text in a human
    launch. Missing provenance on a generated route fails closed because
    :func:`resolve_provenance` can only produce source kinds for text the
    caller explicitly presents as source.
    """

    kind: PromptTextKind
    launch_authorship: LaunchAuthorship

    @property
    def may_execute(self) -> bool:
        """Whether commands in this text may execute."""
        return self.kind.is_source and self.launch_authorship == "human"


def _resolve_launch_authorship(
    explicit: LaunchAuthorship | str | None = None,
) -> LaunchAuthorship:
    """Resolve the launch authorship for this preprocessing call.

    An explicit value wins. Otherwise the existing launch-authorship stamp
    decides; an unset stamp means human (direct human-facing commands carry
    no envelope) and an unknown value fails closed to agent.
    """
    if explicit in ("human", "agent"):
        return explicit  # type: ignore[return-value]
    value = os.environ.get(LAUNCH_AUTHORSHIP_ENV)
    if value is None:
        return "human"
    if value in ("human", "agent"):
        return value  # type: ignore[return-value]
    return "agent"


def resolve_provenance(
    provenance: CmdsubProvenance | None,
    *,
    default_kind: PromptTextKind = PromptTextKind.HUMAN_SOURCE,
    launch_authorship: LaunchAuthorship | str | None = None,
) -> CmdsubProvenance:
    """Resolve the effective provenance for a boundary call.

    An explicitly passed provenance is used as-is. Otherwise the kind
    defaults to *default_kind* (callers present their input as source by
    calling) and the authorship resolves from *launch_authorship* or the
    launch stamp.
    """
    if provenance is not None:
        return provenance
    return CmdsubProvenance(
        kind=default_kind,
        launch_authorship=_resolve_launch_authorship(launch_authorship),
    )


def generated_provenance(
    launch_authorship: LaunchAuthorship | str | None = None,
) -> CmdsubProvenance:
    """Provenance for already-rendered text: never executes."""
    return CmdsubProvenance(
        kind=PromptTextKind.GENERATED,
        launch_authorship=_resolve_launch_authorship(launch_authorship),
    )


def _interpolation_markers(nonce: str) -> tuple[str, str]:
    """Return the ``(start, end)`` interpolation markers for *nonce*.

    A marking Jinja ``finalize`` wraps every ``{{ }}`` output in these so
    :meth:`GeneratedTextGuard.hide_marked_spans` can find exactly the spans
    that came from interpolated values.
    """
    return f"\x00SJSMARK_{nonce}_S\x00", f"\x00SJSMARK_{nonce}_E\x00"


class GeneratedTextLeakError(MacroError):
    """Internal generated-text protection escaped its rendering boundary."""


def assert_no_generated_text_residue(text: str, *, boundary: str) -> None:
    """Reject residue from any guard at an outermost rendering boundary."""
    if "\x00" not in text:
        return
    if re.search(r"\x00(?:SJSMARK_|SASEDATA_)", text, re.IGNORECASE):
        raise GeneratedTextLeakError(
            f"Internal invariant violation at {boundary}: generated-text protection "
            "remains in the prompt; the prompt was not launched."
        )


@dataclass
class _CommandReplacement:
    """One planned ``$(command)`` splice, in Python ``str`` offsets."""

    start: int
    end: int
    command: str


class GeneratedTextGuard:
    """Hide generated text from later command-substitution passes.

    Each guard mints unique null-byte tokens (one UUID nonce per guard) and
    remembers the content behind them. Wrapping interpolated data and command
    stdout keeps that text inert to macro expansion, fence/disabled-region
    scans, and command planning, while leaving the surrounding source text
    fully visible. Tokens never collide across guards, and unwrapping only
    ever restores tokens this guard minted.
    """

    _TOKEN_RE_TEMPLATE = r"\x00SASEDATA_{nonce}_(\d+)\x00"

    def __init__(self) -> None:
        import uuid

        self._nonce = uuid.uuid4().hex
        self._contents: dict[str, str] = {}
        self._counter = 0
        self._token_re = re.compile(
            self._TOKEN_RE_TEMPLATE.format(nonce=re.escape(self._nonce))
        )
        self._start, self._end = _interpolation_markers(self._nonce)
        self._marker_re = re.compile(
            f"{re.escape(self._start)}|{re.escape(self._end)}", re.IGNORECASE
        )
        self._marked_span_re = re.compile(
            f"{re.escape(self._start)}(.*?){re.escape(self._end)}",
            re.DOTALL | re.IGNORECASE,
        )

    @property
    def nonce(self) -> str:
        """The unique nonce embedded in every token this guard mints."""
        return self._nonce

    def wrap(self, content: str) -> str:
        """Replace *content* with a guard token, remembering the original."""
        token = f"\x00SASEDATA_{self._nonce}_{self._counter}\x00"
        self._counter += 1
        self._contents[token] = content
        return token

    def spans_in(self, text: str) -> list[tuple[int, int]]:
        """Return ``(start, end)`` spans of this guard's tokens in *text*."""
        return [(match.start(), match.end()) for match in self._token_re.finditer(text)]

    def mark(self, value: object) -> str:
        """Flatten this guard's nested markers into one balanced data span.

        Case-changing filters may rewrite markers, so stripping ignores case.
        The whole outer value remains data. Jinja comparisons and ``length``
        on block captures or macro returns still see inner markers; slicing
        such a value can split a marker. Those limits require compiler-level
        support rather than a finalize hook.
        """
        text = self._marker_re.sub("", str(value))
        return f"{self._start}{text}{self._end}"

    def hide_marked_spans(self, text: str) -> str:
        """Replace interpolation-marked spans with guard tokens.

        The markers embed this guard's nonce (see
        :func:`_interpolation_markers`), so only spans marked for this guard
        are hidden, ignoring case changes made by Jinja filters. ``mark``
        flattens nested interpolations first. Non-greedy matching keeps
        adjacent interpolations separate, so commands assembled from data
        fragments stay literal. Unbalanced markers fail loudly.
        """
        result = self._marked_span_re.sub(lambda match: self.wrap(match.group(1)), text)
        if self._marker_re.search(result):
            raise GeneratedTextLeakError(
                "Internal invariant violation: unbalanced interpolation markers; "
                "the prompt was not launched."
            )
        return result

    def unwrap(self, text: str) -> str:
        """Restore every token this guard minted that appears in *text*."""
        if "\x00SASEDATA_" not in text:
            return text
        previous = None
        while previous != text:
            previous = text
            text = self._token_re.sub(
                lambda match: self._contents.get(match.group(0), match.group(0)),
                text,
            )
        return text


def _char_to_byte_offsets(text: str) -> list[int]:
    """Return the UTF-8 byte offset of each ``str`` index in *text*."""
    encoded = text.encode("utf-8")
    offsets = [0] * (len(text) + 1)
    byte_index = 0
    for char_index, char in enumerate(text):
        offsets[char_index] = byte_index
        byte_index += len(char.encode("utf-8"))
    offsets[len(text)] = len(encoded)
    return offsets


def _byte_to_char_offsets(text: str) -> dict[int, int]:
    """Map UTF-8 byte offsets back to ``str`` indexes for *text*."""
    mapping: dict[int, int] = {}
    byte_index = 0
    for char_index, char in enumerate(text):
        mapping[byte_index] = char_index
        byte_index += len(char.encode("utf-8"))
    mapping[byte_index] = len(text)
    return mapping


def _plan_source_commands(
    text: str,
    *,
    provenance: CmdsubProvenance,
    protected: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
) -> list[_CommandReplacement]:
    """Plan ``$(command)`` splices for *text* through the core policy.

    Args:
        text: The boundary text to scan. Offsets are Python ``str``
            indexes; protected ranges included.
        provenance: Explicit boundary provenance. Generated text and agent
            launches plan no replacements.
        protected: ``(start, end)`` ``str`` ranges (fenced blocks, disabled
            regions, guard tokens) that are data, never command candidates.

    Returns:
        Ordered replacements in ``str`` offsets. Empty when ineligible or
        when the text holds no complete unescaped command outside the
        protected ranges.
    """
    if not provenance.may_execute or "$(" not in text:
        return []
    from sase.core.rust import require_rust_binding

    plan_fn = require_rust_binding("plan_prompt_command_substitution")
    version_fn = require_rust_binding("prompt_command_substitution_wire_schema_version")
    to_bytes = _char_to_byte_offsets(text)
    request: dict[str, Any] = {
        "schema_version": version_fn(),
        "text": text,
        "kind": provenance.kind.value,
        "launch_authorship": provenance.launch_authorship,
        "protected_ranges": [
            {"start": to_bytes[start], "end": to_bytes[end]} for start, end in protected
        ],
    }
    plan = plan_fn(request)
    to_chars = _byte_to_char_offsets(text)
    replacements = []
    for item in plan["replacements"]:
        replacements.append(
            _CommandReplacement(
                start=to_chars[item["start"]],
                end=to_chars[item["end"]],
                command=item["command"],
            )
        )
    return replacements


def _execute_planned_commands(
    text: str,
    replacements: list[_CommandReplacement],
    *,
    guard: GeneratedTextGuard | None = None,
) -> str:
    """Splice planned command stdout into *text*, end-to-start.

    Successful output is stripped; failed or empty output splices as an
    empty string (matching the legacy substitution contract). Stdout is
    generated text: when *guard* is given it is wrapped in a guard token so
    no later pass can scan it for commands.
    """
    from sase.file_references import execute_cmd_cached

    for replacement in sorted(replacements, key=lambda item: item.start, reverse=True):
        output, success = execute_cmd_cached(replacement.command)
        stdout = output.strip() if success and output else ""
        if guard is not None:
            stdout = guard.wrap(stdout)
        text = text[: replacement.start] + stdout + text[replacement.end :]
    return text


def _unescape_cmdsub(text: str) -> str:
    """Restore escaped ``\\$(`` sequences to literal ``$(``."""
    return text.replace("\\$(", "$(")


def _literal_zone_ranges(text: str) -> list[tuple[int, int]]:
    """Return data ranges (fenced blocks plus disabled regions) in *text*."""
    return [*fenced_block_ranges(text), *disabled_region_ranges(text)]


def execute_eligible_commands(
    text: str,
    *,
    provenance: CmdsubProvenance,
    guard: GeneratedTextGuard | None = None,
    extra_protected: list[tuple[int, int]] | tuple[tuple[int, int], ...] = (),
) -> str:
    """Execute source commands in *text* at this provenance boundary.

    Ineligible text (generated kind or agent launch) returns unchanged. For
    eligible text, fenced blocks, disabled regions, guard tokens, and
    *extra_protected* ranges are data: complete commands overlapping them
    stay literal. Escaped ``\\$(`` sequences become literal ``$(`` only
    when this boundary executed (preserving the legacy substitution
    contract); ineligible text is returned byte-identical.
    """
    if not provenance.may_execute or "$(" not in text:
        return text
    protected: list[tuple[int, int]] = [
        *_literal_zone_ranges(text),
        *extra_protected,
    ]
    if guard is not None:
        protected.extend(guard.spans_in(text))
    replacements = _plan_source_commands(
        text, provenance=provenance, protected=protected
    )
    text = _execute_planned_commands(text, replacements, guard=guard)
    return _unescape_cmdsub(text)
