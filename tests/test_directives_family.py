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


def test_clan_directive_allows_plain_name_directive() -> None:
    _, directives = extract_prompt_directives(
        "%n:research.worker\n%clan:research\nDo work"
    )

    assert directives.name == "research.worker"
    assert directives.clan == "research"


@pytest.mark.parametrize("source", ["%clan", "%clan:"])
def test_clan_directive_rejects_empty_name(source: str) -> None:
    with pytest.raises(DirectiveError, match="requires a clan name argument"):
        extract_prompt_directives(f"{source}\nDo work")


@pytest.mark.parametrize("source", ["%clan(foo)", "%c(foo)", "%clan+"])
def test_clan_directive_is_colon_only(source: str) -> None:
    with pytest.raises(DirectiveError, match="uses the colon form only"):
        extract_prompt_directives(f"{source}\nDo work")


def test_clan_directive_rejects_duplicate_alias_occurrence() -> None:
    with pytest.raises(DirectiveError, match="Duplicate directive '%clan'"):
        extract_prompt_directives("%clan:root\n%c:other\nDo work")


def test_clan_directive_conflicts_with_serial_family_attach() -> None:
    prompt = "%n(parent, reviewer)\n%clan:parent\nDo work"

    with pytest.raises(DirectiveError, match="Cannot combine %clan with %n"):
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


def test_clan_directive_inside_disabled_region_is_ignored() -> None:
    prompt = "%xprompts_enabled:false\n%clan:example\n%xprompts_enabled:true\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "%clan:example\nDo work"
    assert directives.clan is None
