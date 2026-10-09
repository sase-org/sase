"""Cheap `%auto`/`%a` scan coverage and launch-message parity."""

from __future__ import annotations

import pytest

from sase.macro._directive_scan import scan_auto_directive
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives


@pytest.mark.parametrize("prompt", ["do the work", "%dispatch:apollo do the work"])
def test_auto_scan_absent_without_auto(prompt: str) -> None:
    assert scan_auto_directive(prompt) is None


@pytest.mark.parametrize(
    "prompt",
    [
        "%auto do the work",
        "%a do the work",
        "%auto+ do the work",
        "%auto:true do the work",
        "%auto:plan do the work",
        "%auto:tale do the work",
        "%a:epic do the work",
        "%auto:manual do the work",
        "%auto:off do the work",
    ],
)
def test_auto_scan_ok_for_valid_and_manual_spellings(prompt: str) -> None:
    scan = scan_auto_directive(prompt)

    assert scan is not None
    assert scan.error is None


@pytest.mark.parametrize(
    "prompt",
    [
        "%auto(plan=ask) do the work",
        "%a(epic=ask) do the work",
        "%auto(plan, epic) do the work",
        "%auto() do the work",
        "%auto(tale) do the work",
        "%auto( do the work",
        "%auto:foo do the work",
        "%a:foo do the work",
        "%auto:`foo` do the work",
        "%auto:x(plan=ask) do the work",
        "%auto:epic_plan do the work",
        "%auto %auto:off do the work",
        "%auto %auto do the work",
        "%auto:foo %auto:bar do the work",
    ],
)
def test_auto_scan_error_matches_launch_error(prompt: str) -> None:
    with pytest.raises(DirectiveError) as exc_info:
        extract_prompt_directives(prompt)

    scan = scan_auto_directive(prompt)

    assert scan is not None
    assert scan.error == str(exc_info.value)


def test_auto_scan_ignores_fenced_spelling() -> None:
    assert scan_auto_directive("```\n%auto:foo\n```\ndo the work") is None


def test_auto_scan_ignores_disabled_spelling() -> None:
    prompt = "%macros_enabled:false\n%auto:foo\n%macros_enabled:true\ndo the work"

    assert scan_auto_directive(prompt) is None
