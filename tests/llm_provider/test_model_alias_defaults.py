"""Tests for the bundled ``model_alias_defaults.yml`` and its loader.

These cover the shape guarantees the loader enforces so a malformed or
incomplete edit to the shipped defaults YAML fails fast, rather than silently
dropping a role alias or rerouting it to the wrong fallback.
"""

from __future__ import annotations

from sase.llm_provider.load_balancing import (
    ModelAliasSelectorError,
    parse_model_alias_selector,
)
from sase.llm_provider.model_alias_policy import (
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
    CODER_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    implicit_alias_targets,
    role_alias_descriptions,
    role_alias_fallbacks,
)
from sase.xprompt.effort import split_model_effort

# Independent ground truth: every alias-name constant the module declares,
# enumerated here rather than derived from the loader under test.
_DECLARED_ROLE_ALIAS_NAMES = frozenset(
    {
        DEFAULT_MODEL_ALIAS_NAME,
        CODER_MODEL_ALIAS_NAME,
        EPIC_LANDER_MODEL_ALIAS_NAME,
        BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
        XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
        SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
        MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
        LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
        XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
        SMART_MODEL_ALIAS_NAME,
        SMARTEST_MODEL_ALIAS_NAME,
        CHEAP_MODEL_ALIAS_NAME,
        CHEAPER_MODEL_ALIAS_NAME,
        CHEAPEST_MODEL_ALIAS_NAME,
    }
)


def test_every_declared_name_has_a_description_and_vice_versa() -> None:
    """A role alias name constant without a YAML entry (or vice versa) fails."""
    assert set(role_alias_descriptions()) == _DECLARED_ROLE_ALIAS_NAMES


def test_fallback_and_target_are_mutually_exclusive_and_cover_every_role() -> None:
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()

    assert set(fallbacks).isdisjoint(targets)
    assert set(fallbacks) | set(targets) | {DEFAULT_MODEL_ALIAS_NAME} == (
        _DECLARED_ROLE_ALIAS_NAMES
    )


def test_default_alias_has_neither_fallback_nor_target() -> None:
    assert DEFAULT_MODEL_ALIAS_NAME not in role_alias_fallbacks()
    assert DEFAULT_MODEL_ALIAS_NAME not in implicit_alias_targets()


def test_every_description_is_a_nonempty_stripped_string() -> None:
    for name, description in role_alias_descriptions().items():
        assert isinstance(description, str) and description, name
        assert description == description.strip(), name


def test_every_target_parses_under_the_selector_grammar() -> None:
    for name, target in implicit_alias_targets().items():
        try:
            selector = parse_model_alias_selector(target)
        except ModelAliasSelectorError as exc:
            raise AssertionError(
                f"'{name}' target {target!r} is malformed: {exc}"
            ) from exc
        # Every current implicit target is a multi-provider selector, not a
        # bare model; a future single-target entry would also be valid.
        if selector is not None:
            assert selector.members


def test_every_fallback_resolves_to_a_declared_alias_name() -> None:
    for name, fallback in role_alias_fallbacks().items():
        clean, _effort = split_model_effort(fallback)
        assert clean.startswith("@"), (
            f"'{name}' fallback {fallback!r} must be an @-reference"
        )
        referenced = clean[1:]
        assert referenced in _DECLARED_ROLE_ALIAS_NAMES, (
            f"'{name}' fallback references unknown alias '@{referenced}'"
        )


def test_smartest_is_fallback_and_cheap_family_are_pools() -> None:
    """Pin the *shape* of the selector-valued defaults, not their literal targets."""
    targets = implicit_alias_targets()

    smartest = parse_model_alias_selector(targets[SMARTEST_MODEL_ALIAS_NAME])
    cheap = parse_model_alias_selector(targets[CHEAP_MODEL_ALIAS_NAME])
    cheaper = parse_model_alias_selector(targets[CHEAPER_MODEL_ALIAS_NAME])
    cheapest = parse_model_alias_selector(targets[CHEAPEST_MODEL_ALIAS_NAME])
    assert smartest is not None and smartest.mode == "fallback"
    assert cheap is not None and cheap.mode == "round_robin"
    assert cheaper is not None and cheaper.mode == "round_robin"
    assert cheapest is not None and cheapest.mode == "round_robin"


def test_cheap_family_ships_the_expected_members_and_efforts() -> None:
    targets = implicit_alias_targets()
    cheap = parse_model_alias_selector(targets[CHEAP_MODEL_ALIAS_NAME])
    cheaper = parse_model_alias_selector(targets[CHEAPER_MODEL_ALIAS_NAME])
    cheapest = parse_model_alias_selector(targets[CHEAPEST_MODEL_ALIAS_NAME])

    assert cheap is not None
    assert cheap.members == (
        "claude/sonnet@xhigh",
        "codex/gpt-5.5",
    )
    assert cheaper is not None
    assert cheaper.members == (
        "claude/sonnet@medium",
        "codex/gpt-5.5@medium",
    )
    assert cheapest is not None
    assert cheapest.members == (
        "claude/haiku",
        "codex/gpt-5.3-codex-spark",
    )


def test_medium_phase_worker_carries_high_effort() -> None:
    fallback = role_alias_fallbacks()[MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME]
    _clean, effort = split_model_effort(fallback)
    assert effort == "high"
