"""Tests for Agents-tab retry-edit name rewriting."""

from __future__ import annotations

from unittest.mock import Mock, patch

from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.ace.tui.actions.agent_workflow._entry_points import (
    _rewrite_retry_prompt_name,
)

from ._retry_edit_agent_name_helpers import (
    _Agent,
    _App,
    _configured_machine_identity,
)


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


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_prepends_allocated_retry_name(
    _mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name="foo"))

    app._retry_edit_agent()

    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.foo.r0",
)
def test_retry_edit_qualified_local_agent_uses_prompt_facing_name(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("%id:foo\nDo work", agent_name="athena.foo"))

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("foo")
    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.sase-8a.3.r0",
)
def test_retry_edit_qualified_local_family_phase_allocates_from_presented_base(
    mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:sase-8a.3\n%auto\nDo work",
            agent_name="athena.sase-8a.3--plan",
        )
    )

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("sase-8a.3")
    assert app.launched == (
        "%id:sase-8a.3.r0\n%auto\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="athena.sase-8k.2.r0",
)
def test_retry_edit_qualified_local_clan_member_preserves_clan_name(
    mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id(2, clan=sase-8k, bead=sase-8k.2)\nDo work",
            agent_name="athena.sase-8k.2",
        )
    )

    app._retry_edit_agent()

    mock_allocate.assert_called_once_with("sase-8k.2")
    assert app.launched == (
        "%id(2.r0, clan=sase-8k, bead=sase-8k.2)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_preserves_unnamed_agent_prompt(
    mock_allocate: Mock,
) -> None:
    app = _App(_Agent("Do work", agent_name=None))

    app._retry_edit_agent()

    assert app.launched == ("Do work", "/tmp/proj/proj.sase", "branch", False)
    assert app.notifications == []
    assert not mock_allocate.called


@patch("sase.agent.names.allocate_retry_name", return_value="foo.r0")
def test_retry_edit_agent_replaces_name_without_force_reuse(
    _mock_allocate: Mock,
) -> None:
    app = _App(_Agent("%id:foo\nDo work", agent_name="foo"))

    app._retry_edit_agent()

    assert app.launched == (
        "%id:foo.r0\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
    assert app.notifications == []


@patch("sase.agent.names.allocate_retry_name", return_value="root.worker.r0")
def test_retry_edit_agent_demotes_clan_declaration(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:root.worker\n%clan(root, tribe=review)\nDo work",
            agent_name="root.worker",
        )
    )

    app._retry_edit_agent()

    assert app.launched == (
        "%id(worker.r0, clan=root)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch("sase.agent.names.allocate_retry_name", return_value="root.worker.r0")
def test_retry_edit_agent_preserves_clan_joiner_membership(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id(worker, clan=root)\nDo work",
            agent_name="root.worker",
        )
    )

    app._retry_edit_agent()

    assert app.launched == (
        "%id(worker.r0, clan=root)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )


@patch(
    "sase.agent.names.allocate_retry_name",
    return_value="research.2.worker.r0",
)
def test_retry_edit_agent_resolves_template_clan_membership(
    _mock_allocate: Mock,
) -> None:
    app = _App(
        _Agent(
            "%id:research.@.worker\n%clan(research.@, tribe=review)\nDo work",
            agent_name="research.2.worker",
        )
    )

    app._retry_edit_agent()

    assert app.launched == (
        "%id(worker.r0, clan=research.2)\nDo work",
        "/tmp/proj/proj.sase",
        "branch",
        False,
    )
