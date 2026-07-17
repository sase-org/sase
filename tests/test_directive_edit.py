"""Tests for pure prompt directive rewrite helpers."""

from __future__ import annotations

from unittest.mock import patch

from sase.xprompt.directive_edit import (
    PromptWaitDirective,
    set_prompt_auto_mode,
    set_prompt_clan,
    set_prompt_name,
    set_prompt_tribe,
    set_prompt_wait,
)
from sase.xprompt.directives import extract_prompt_directives


def test_set_prompt_name_inserts_when_absent() -> None:
    assert set_prompt_name("Do work", "reviewer") == "%name:reviewer\nDo work"


def test_set_prompt_name_replaces_long_form() -> None:
    assert set_prompt_name("%name:old\nDo work", "new") == "%name:new\nDo work"


def test_set_prompt_name_replaces_alias_without_touching_tribe() -> None:
    prompt = "%t:batch\n%n:old\nDo work"
    assert set_prompt_name(prompt, "new") == "%name:new\n%t:batch\nDo work"


def test_set_prompt_tribe_set_and_unset_alias() -> None:
    assert set_prompt_tribe("%t:old\nDo work", "triage") == ("%tribe:triage\nDo work")
    assert set_prompt_tribe("%tribe:triage\nDo work", None) == "Do work"


def test_set_prompt_tribe_migrates_removed_group_spellings() -> None:
    prompt = "%group:old\n%g:older\nDo work"
    assert set_prompt_tribe(prompt, "triage") == "%tribe:triage\nDo work"


def test_set_prompt_clan_set_and_unset_alias() -> None:
    assert set_prompt_clan("%c:old\nDo work", "research") == ("%clan:research\nDo work")
    assert set_prompt_clan("%clan:research\nDo work", None) == "Do work"


def test_set_prompt_auto_mode_canonical_forms() -> None:
    assert set_prompt_auto_mode("%a:tale\nDo work", "plan") == "%auto\nDo work"
    assert set_prompt_auto_mode("%auto\nDo work", "epic") == "%auto:epic\nDo work"
    assert set_prompt_auto_mode("%auto:epic\nDo work", None) == "Do work"


def test_set_prompt_wait_replaces_alias_and_time_forms() -> None:
    prompt = "%w:old\n#t:5m\n%time:1h\nDo work"
    rewritten = set_prompt_wait(
        prompt,
        PromptWaitDirective(agents=("dep",), time_token="10m"),
    )
    assert rewritten == "%wait(dep, time=10m)\nDo work"
    with patch("sase.agent.names.is_agent_name_template", return_value=False):
        _, directives = extract_prompt_directives(rewritten)
    assert directives.wait == ["dep"]
    assert directives.wait_duration == 600.0


def test_set_prompt_wait_replaces_inline_wait_and_time_forms() -> None:
    prompt = "%w:old #t:5m %time:1430 Do work"
    rewritten = set_prompt_wait(
        prompt,
        PromptWaitDirective(agents=("dep",), time_token="10m"),
    )

    assert rewritten == "%wait(dep, time=10m)\nDo work"


def test_set_prompt_wait_clears_wait_directives() -> None:
    assert set_prompt_wait("%wait(dep, time=5m)\nDo work", None) == "Do work"


def test_set_prompt_wait_formats_runner_threshold() -> None:
    rewritten = set_prompt_wait(
        "Do work",
        PromptWaitDirective(agents=("dep",), time_token="5m", runners=0),
    )

    assert rewritten == "%wait(dep, time=5m, runners=0)\nDo work"


def test_insert_after_frontmatter() -> None:
    prompt = "---\ntitle: demo\n---\nDo work"
    assert set_prompt_name(prompt, "agent") == (
        "---\ntitle: demo\n---\n%name:agent\nDo work"
    )


def test_fenced_directives_are_not_rewritten() -> None:
    prompt = "Before\n```text\n%name:example\n```\nDo work"
    assert set_prompt_name(prompt, "real") == (
        "%name:real\nBefore\n```text\n%name:example\n```\nDo work"
    )


def test_disabled_region_directives_are_not_rewritten() -> None:
    prompt = "%xprompts_enabled:false\n%tribe:old\n%xprompts_enabled:true\nDo work"
    assert set_prompt_tribe(prompt, "new") == (
        "%tribe:new\n"
        "%xprompts_enabled:false\n"
        "%tribe:old\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )


def test_alt_branch_directives_are_not_rewritten() -> None:
    prompt = "%alt(%name:a | %name:b)\nDo work"
    assert set_prompt_name(prompt, "real") == (
        "%name:real\n%alt(%name:a | %name:b)\nDo work"
    )
