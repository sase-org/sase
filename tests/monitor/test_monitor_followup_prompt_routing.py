"""Model/effort routing-directive tests for :func:`sase.monitor.followup_prompt.compose_followup_prompt`."""

from __future__ import annotations

from sase.monitor.followup_prompt import compose_followup_prompt
from sase.xprompt.directives import extract_prompt_directives

from ._followup_prompt_fixtures import _COMMON


def test_compose_followup_prompt_prefixes_model_and_effort_directives() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        model="claude-sonnet-5",
        reasoning_effort="high",
        **_COMMON,
    )

    assert prompt.startswith("#fork:acme--0\n%model:claude-sonnet-5\n%effort:high\n\n")
    assert prompt.splitlines()[4] == "%xprompts_enabled:false"

    _, directives = extract_prompt_directives(prompt)
    assert directives.model == "claude-sonnet-5"
    assert directives.reasoning_effort == "high"


def test_compose_followup_prompt_omits_routing_directives_when_unset() -> None:
    prompt = compose_followup_prompt(
        starter_name=None,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        **_COMMON,
    )

    assert "%model:" not in prompt
    assert "%effort:" not in prompt


def test_compose_followup_prompt_explicit_next_model_replaces_inherited_routing() -> (
    None
):
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        model="claude-sonnet-5",
        reasoning_effort="high",
        next_model="@small",
        **_COMMON,
    )

    assert prompt.startswith("#fork:acme--0\n%model:@small\n\n")
    assert "%effort:high" not in prompt
    assert "%model:claude-sonnet-5" not in prompt

    _, directives = extract_prompt_directives(prompt)
    assert directives.model == "small"
    assert directives.reasoning_effort is None


def test_compose_followup_prompt_explicit_model_keeps_alias_effort_and_provider() -> (
    None
):
    alias = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        model="inherited-model",
        reasoning_effort="high",
        next_model="small",
        **_COMMON,
    )
    qualified = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        model="inherited-model",
        reasoning_effort="high",
        next_model="codex/gpt-5.6-sol@xhigh",
        **_COMMON,
    )

    assert alias.splitlines()[1] == "%model:@small"
    assert qualified.splitlines()[1] == "%model:codex/gpt-5.6-sol@xhigh"

    _, alias_directives = extract_prompt_directives(alias)
    assert alias_directives.model == "small"
    assert alias_directives.reasoning_effort is None

    _, qualified_directives = extract_prompt_directives(qualified)
    assert qualified_directives.model == "codex/gpt-5.6-sol"
    assert qualified_directives.reasoning_effort == "xhigh"


def test_compose_followup_prompt_omitted_next_model_still_inherits_routing() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=1.0,
        timeout_seconds=0.0,
        model="claude-sonnet-5",
        reasoning_effort="high",
        **_COMMON,
    )

    assert prompt.startswith("#fork:acme--0\n%model:claude-sonnet-5\n%effort:high\n\n")
