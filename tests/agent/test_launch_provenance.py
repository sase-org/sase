"""Launch provenance stamping tests (fail-closed human-authorship origin)."""

from __future__ import annotations

import pytest

from sase.agent.launch_provenance import (
    PROMPT_ORIGIN_ENV,
    PROMPT_SOURCE_SURFACE_ENV,
    fill_launch_provenance_default,
    normalize_prompt_origin,
    prompt_origin_for_launch,
    read_launch_provenance,
    with_launch_provenance,
)


@pytest.fixture(autouse=True)
def _no_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve origins as a human shell would: no agent markers present."""
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_normalize_prompt_origin_accepts_known_values() -> None:
    assert normalize_prompt_origin("typed") == "typed"
    assert normalize_prompt_origin("generated") == "generated"
    assert normalize_prompt_origin("unknown") == "unknown"


def test_normalize_prompt_origin_fails_closed() -> None:
    assert normalize_prompt_origin(None) == "unknown"
    assert normalize_prompt_origin("") == "unknown"
    assert normalize_prompt_origin("human") == "unknown"
    assert normalize_prompt_origin("TYPED") == "unknown"


def test_prompt_origin_for_launch_none_is_unknown() -> None:
    assert prompt_origin_for_launch(None) == "unknown"


def test_agent_process_resolves_generated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside an agent, even an explicit typed origin resolves generated."""
    monkeypatch.setenv("SASE_AGENT", "1")
    assert prompt_origin_for_launch("typed") == "generated"
    assert prompt_origin_for_launch(None) == "generated"


def test_prompt_origin_for_launch_keeps_valid_stamp() -> None:
    assert (
        prompt_origin_for_launch(
            "generated", launch_envs=({PROMPT_ORIGIN_ENV: "typed"},)
        )
        == "typed"
    )


def test_with_launch_provenance_does_not_mutate_input() -> None:
    extra = {"A": "b"}
    stamped = with_launch_provenance(extra, origin="typed", source_surface="ace")
    assert extra == {"A": "b"}
    assert stamped[PROMPT_ORIGIN_ENV] == "typed"
    assert stamped[PROMPT_SOURCE_SURFACE_ENV] == "ace"


def test_with_launch_provenance_keeps_outer_stamp() -> None:
    extra = {PROMPT_ORIGIN_ENV: "typed", PROMPT_SOURCE_SURFACE_ENV: "ace"}
    stamped = with_launch_provenance(extra, origin="generated")
    assert stamped[PROMPT_ORIGIN_ENV] == "typed"
    assert stamped[PROMPT_SOURCE_SURFACE_ENV] == "ace"


def test_fill_default_inherits_valid_ambient() -> None:
    stamped = fill_launch_provenance_default(
        None, env={PROMPT_ORIGIN_ENV: "typed", PROMPT_SOURCE_SURFACE_ENV: "ace"}
    )
    assert stamped[PROMPT_ORIGIN_ENV] == "typed"
    assert stamped[PROMPT_SOURCE_SURFACE_ENV] == "ace"


def test_fill_default_is_generated_without_ambient() -> None:
    stamped = fill_launch_provenance_default(None, env={})
    assert stamped[PROMPT_ORIGIN_ENV] == "generated"
    assert stamped[PROMPT_SOURCE_SURFACE_ENV] == "unknown"


def test_fill_default_never_overwrites_explicit_stamp() -> None:
    stamped = fill_launch_provenance_default(
        {PROMPT_ORIGIN_ENV: "typed"},
        env={PROMPT_ORIGIN_ENV: "generated"},
    )
    assert stamped[PROMPT_ORIGIN_ENV] == "typed"


def test_read_launch_provenance_missing_is_unknown() -> None:
    assert read_launch_provenance({}) == ("unknown", "unknown")
    assert read_launch_provenance({PROMPT_ORIGIN_ENV: "bogus"}) == (
        "unknown",
        "unknown",
    )
