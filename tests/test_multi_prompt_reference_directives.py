"""Tests for static directive extraction used by multi-prompt preflight."""

from __future__ import annotations

import pytest

from sase.agent.multi_prompt_reference_directives import (
    StaticClanDirective,
    extract_static_clan_directive,
    extract_static_name_directive,
    has_bare_wait_directive,
    rewrite_bare_wait_directives,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("%id(worker, clan=research)", "research.worker"),
        ("%i(a.b, clan=review)", "review.a.b"),
        ("%id(!worker, clan=research)", "research.worker"),
        ("%id(cld, clan=research.@)", "research.@.cld"),
    ],
)
def test_static_name_extraction_derives_clan_member_name(
    source: str,
    expected: str,
) -> None:
    assert extract_static_name_directive(f"{source}\nDo work") == expected


def test_static_name_extraction_ignores_family_keyword_form() -> None:
    assert extract_static_name_directive("%id(reviewer, family=foo)\nDo work") is None


def test_static_clan_extraction_marks_id_keyword_as_joiner() -> None:
    directive = extract_static_clan_directive("%id(worker, clan=research)\nDo work")

    assert directive == StaticClanDirective(
        name="research",
        tribe=None,
        declared=False,
    )


def test_static_clan_extraction_marks_clan_directive_as_declaration() -> None:
    directive = extract_static_clan_directive(
        "%clan(research, tribe=review)\n%id:research.worker\nDo work"
    )

    assert directive == StaticClanDirective(
        name="research",
        tribe="review",
        declared=True,
    )


@pytest.mark.parametrize("directive", ["wait", "w"])
def test_bead_only_wait_is_not_bare_or_rewritten(directive: str) -> None:
    prompt = f"%{directive}(bead=sase-87.1)\nDo work"

    assert has_bare_wait_directive(prompt) is False
    assert rewrite_bare_wait_directives(prompt, "previous") == prompt


def test_bead_only_wait_does_not_hide_separate_bare_wait() -> None:
    prompt = "%w(bead=sase-87.1)\n%wait\nDo work"

    assert has_bare_wait_directive(prompt) is True
    assert rewrite_bare_wait_directives(prompt, "previous") == (
        "%w(bead=sase-87.1)\n%wait:previous\nDo work"
    )
