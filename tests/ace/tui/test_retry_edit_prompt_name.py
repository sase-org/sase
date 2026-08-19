"""Tests for the retry-edit prompt name-rewriting contract."""

from __future__ import annotations

from unittest.mock import patch

from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.ace.tui.actions.agent_workflow._entry_points import (
    _rewrite_retry_prompt_name,
)

from ._retry_edit_agent_name_helpers import _configured_machine_identity


def test_rewrite_retry_prompt_prepends_name_when_missing() -> None:
    assert _rewrite_retry_prompt_name("Do work", "foo.r0") == "%id:foo.r0\nDo work"


def test_rewrite_retry_prompt_replaces_percent_name() -> None:
    assert (
        _rewrite_retry_prompt_name("%id:foo\nDo work", "foo.r0")
        == "%id:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_replaces_percent_n() -> None:
    assert (
        _rewrite_retry_prompt_name("%i:foo\nDo work", "foo.r0") == "%id:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_bare_id_does_not_allocate_an_intermediate_name() -> None:
    with patch(
        "sase.agent.names.get_next_auto_name",
        side_effect=AssertionError("retry rewrite must not allocate"),
    ):
        rewritten = _rewrite_retry_prompt_name("%id\nDo work", "foo.r0")

    assert rewritten == "%id:foo.r0\nDo work"


def test_rewrite_retry_prompt_replaces_template_name() -> None:
    assert (
        _rewrite_retry_prompt_name("%id:@.cld\nDo work", "0.cld.r0")
        == "%id:0.cld.r0\nDo work"
    )


def test_rewrite_retry_prompt_preserves_tribe_keyword() -> None:
    assert (
        _rewrite_retry_prompt_name(
            "%id(foo, tribe=review)\nDo work",
            "foo.r0",
        )
        == "%id(foo.r0, tribe=review)\nDo work"
    )


def test_rewrite_retry_prompt_uses_concrete_name_for_family_member() -> None:
    assert (
        _rewrite_retry_prompt_name(
            "%id(reviewer, family=foo)\nDo work",
            "foo--reviewer.r0",
        )
        == "%id:foo--reviewer.r0\nDo work"
    )


def test_rewrite_retry_prompt_preserves_clan_joiner_membership() -> None:
    assert (
        _rewrite_retry_prompt_name(
            "%id(worker, clan=root)\nDo work",
            "root.worker.r0",
        )
        == "%id(worker.r0, clan=root)\nDo work"
    )


def test_rewrite_retry_prompt_resolves_template_clan_joiner() -> None:
    assert (
        _rewrite_retry_prompt_name(
            "%id(worker, clan=research.@)\nDo work",
            "research.2.worker.r0",
            current_agent_name="research.2.worker",
        )
        == "%id(worker.r0, clan=research.2)\nDo work"
    )


def test_rewrite_retry_prompt_ignores_fenced_and_disabled_name_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert _rewrite_retry_prompt_name(prompt, "foo.r0") == f"%id:foo.r0\n{prompt}"


def test_rewrite_retry_prompt_can_prepend_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name("Do work", "foo.r0", directive_alias="i")
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_can_replace_percent_name_with_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name(
            "%id:foo\nDo work",
            "foo.r0",
            directive_alias="i",
        )
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_can_replace_percent_n_with_n_alias() -> None:
    assert (
        rewrite_retry_prompt_name("%i:foo\nDo work", "foo.r0", directive_alias="i")
        == "%i:foo.r0\nDo work"
    )


def test_rewrite_retry_prompt_n_alias_ignores_fenced_and_disabled_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert (
        rewrite_retry_prompt_name(prompt, "foo.r0", directive_alias="i")
        == f"%i:foo.r0\n{prompt}"
    )
