"""Keyed ``{@<id>}`` markers survive every prompt-grammar lexer.

Resolution happens in the launcher, so each lexer between a raw prompt and the
launch funnel has to carry a braced marker through intact. A class that stops at
``{`` silently truncates the name and reintroduces the latest-wins hood bug the
keyed marker exists to remove.
"""

from __future__ import annotations

import re

import pytest

from sase.agent.launch_validation import (
    preflight_launch_name_requests,
    validate_user_agent_name,
)
from sase.agent.multi_prompt_reference_resume import _RESUME_REF_RE
from sase.xprompt._directive_types import _DIRECTIVE_PATTERN
from sase.xprompt._parsing import parse_args
from sase.xprompt._parsing_vcs_tags import _DIRECTIVE_PREFIX_RE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("%id:research.{@1}.cdx", "research.{@1}.cdx"),
        ("%clan:research.{@1}", "research.{@1}"),
        ("%wait:research.{@1}.final", "research.{@1}.final"),
        ("%wait:research.{@swarm.1!}.final", "research.{@swarm.1!}.final"),
        ("%id:research.{@1!}", "research.{@1!}"),
    ],
)
def test_directive_pattern_keeps_keyed_marker(text: str, expected: str) -> None:
    match = re.search(_DIRECTIVE_PATTERN, text)

    assert match is not None
    assert match.group(3) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A `}` that does not close a marker still ends the argument, so the
        # enclosing `%{a | b}` fan-out group keeps its closing brace.
        ("%{%m:opus | %m:#codex}", "#codex"),
        ("%m:opus}", "opus"),
        # A marker-shaped argument must not end at a bare `.` or `!` either.
        ("%id:research.{@1}.", "research.{@1}"),
    ],
)
def test_directive_pattern_does_not_swallow_unmatched_braces(
    text: str, expected: str
) -> None:
    matches = list(re.finditer(_DIRECTIVE_PATTERN, text, re.MULTILINE))

    assert matches
    assert matches[-1].group(3) == expected


def test_directive_prefix_pattern_spans_keyed_markers() -> None:
    """The VCS-tag prefix matcher keeps braced markers in the launch prefix."""
    prompt = "%id:research.{@1}.cdx %clan(research.{@1}, tribe=research) body"

    match = _DIRECTIVE_PREFIX_RE.match(prompt)

    assert match is not None
    assert match.group(0) == (
        "%id:research.{@1}.cdx %clan(research.{@1}, tribe=research) "
    )


def test_parse_args_passes_braced_markers_through() -> None:
    positional, named = parse_args("research.{@1}.cdx, clan=research.{@1}")

    assert positional == ["research.{@1}.cdx"]
    assert named == {"clan": "research.{@1}"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#fork:research.{@1}.final", "research.{@1}.final"),
        ("#resume:research.{@swarm.1!}.cdx", "research.{@swarm.1!}.cdx"),
    ],
)
def test_resume_reference_pattern_keeps_keyed_marker(text: str, expected: str) -> None:
    match = _RESUME_REF_RE.search(text)

    assert match is not None
    assert match.group("colon") == expected


def test_preflight_accepts_a_keyed_marker_as_a_template() -> None:
    """A keyed ``%id`` is a template, so preflight never treats it as a name."""
    preflight_launch_name_requests(["%id:research.{@1}.cdx\nDo work"])


def test_claiming_an_unresolved_marker_names_the_marker() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        validate_user_agent_name("research.{@1}.cdx")

    message = str(excinfo.value)
    assert "unresolved agent-name marker '{@1}'" in message
    assert "resolution was skipped" in message


def test_claiming_a_concrete_name_is_unaffected() -> None:
    validate_user_agent_name("research.o.cdx")
