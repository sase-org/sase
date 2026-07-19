"""Tests for rootless agent-clan prompt directives."""

from __future__ import annotations

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


@pytest.mark.parametrize(
    ("source", "clan"),
    [
        ("%clan:sase-6g", "sase-6g"),
        ("%clan:research.@", "research.@"),
        ("%c:research.@", "research.@"),
    ],
)
def test_clan_directive_parses_colon_name(source: str, clan: str) -> None:
    cleaned, directives = extract_prompt_directives(f"{source}\nDo work")

    assert cleaned == "Do work"
    assert directives.clan == clan
    assert directives.clan_tribe is None


@pytest.mark.parametrize("directive", ["clan", "c"])
def test_clan_directive_parses_parenthesized_tribe(directive: str) -> None:
    cleaned, directives = extract_prompt_directives(
        f"%{directive}(research.@, tribe=research)\nDo work"
    )

    assert cleaned == "Do work"
    assert directives.clan == "research.@"
    assert directives.clan_tribe == "research"
    assert directives.tag is None


def test_clan_directive_allows_plain_name_directive() -> None:
    _, directives = extract_prompt_directives(
        "%i:research.worker\n%clan:research\nDo work"
    )

    assert directives.name == "research.worker"
    assert directives.clan == "research"


@pytest.mark.parametrize("source", ["%clan", "%clan:"])
def test_clan_directive_rejects_empty_name(source: str) -> None:
    with pytest.raises(DirectiveError, match="requires a clan name argument"):
        extract_prompt_directives(f"{source}\nDo work")


def test_clan_directive_parenthesized_name_without_tribe() -> None:
    _, directives = extract_prompt_directives("%clan(foo)\nDo work")

    assert directives.clan == "foo"
    assert directives.clan_tribe is None


def test_clan_directive_rejects_plus_form() -> None:
    with pytest.raises(DirectiveError, match="does not support '\\+'"):
        extract_prompt_directives("%clan+\nDo work")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("%clan(tribe=research)", "requires a clan name"),
        ("%clan(foo, tribe=)", "requires a non-empty tribe"),
        ("%clan(foo, tribe=a, tribe=b)", "Duplicate keyword argument 'tribe'"),
        ("%clan(foo, color=blue)", "Unsupported keyword on %clan: color="),
        ("%clan(foo, bar, tribe=research)", "exactly one positional"),
        ("%clan(foo, tribe=has+space)", "Invalid '%clan' tribe= value"),
        ("%clan(foo, tribe=research", "missing closing"),
    ],
)
def test_clan_directive_rejects_invalid_argument_shapes(
    source: str,
    message: str,
) -> None:
    with pytest.raises(DirectiveError, match=message):
        extract_prompt_directives(f"{source}\nDo work")


@pytest.mark.parametrize(
    "prompt",
    [
        f"{first}\n{second}\nDo work"
        for clan_alias in ("clan", "c")
        for tribe_alias in ("tribe", "t")
        for clan_form in (f"%{clan_alias}:foo", f"%{clan_alias}(foo)")
        for tribe_form in (
            f"%{tribe_alias}:research",
            f"%{tribe_alias}(research)",
        )
        for first, second in (
            (clan_form, tribe_form),
            (tribe_form, clan_form),
        )
    ],
)
def test_clan_directive_conflicts_with_standalone_tribe(prompt: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"Cannot combine %tribe with %clan; use %clan\(<clan>, tribe=<tribe>\)",
    ):
        extract_prompt_directives(prompt)


def test_clan_directive_rejects_duplicate_alias_occurrence() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%clan'"):
        extract_prompt_directives("%clan:root\n%c:other\nDo work")


def test_clan_directive_conflicts_with_serial_family_attach() -> None:
    prompt = "%i(parent, reviewer)\n%clan:parent\nDo work"

    with pytest.raises(DirectiveError, match="Cannot combine %clan with %i"):
        extract_prompt_directives(prompt)


def test_removed_family_directives_are_not_recognized() -> None:
    prompt = "%family:example\n%f:example\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None


def test_clan_directive_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%clan:example\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None


def test_clan_tribe_conflict_inside_fenced_block_is_ignored() -> None:
    prompt = "```text\n%clan:example\n%tribe:research\n```\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == prompt
    assert directives.clan is None
    assert directives.tag is None


def test_clan_directive_inside_disabled_region_is_ignored() -> None:
    prompt = "%xprompts_enabled:false\n%clan:example\n%xprompts_enabled:true\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example\nDo work"
    assert directives.clan is None


def test_clan_tribe_conflict_inside_disabled_region_is_ignored() -> None:
    prompt = (
        "%xprompts_enabled:false\n"
        "%clan:example\n%tribe:research\n"
        "%xprompts_enabled:true\nDo work"
    )

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example\n%tribe:research\nDo work"
    assert directives.clan is None
    assert directives.tag is None
