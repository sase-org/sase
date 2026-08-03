"""Tests for the bundled ``model_alias_defaults.yml`` and its parser."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
import yaml  # type: ignore[import-untyped]

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
    _parse_model_alias_defaults,
    implicit_alias_targets,
    role_alias_descriptions,
    role_alias_fallbacks,
)
from sase.xprompt.effort import split_model_effort
from tests._model_alias_defaults_fixture import (
    FROZEN_ALIAS_SHAPE,
    FROZEN_DESCRIPTIONS,
    FROZEN_FALLBACKS,
    FROZEN_TARGETS,
)

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


def _current_shape_signature() -> Mapping[str, tuple[str, str | None]]:
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()
    shape: dict[str, tuple[str, str | None]] = {}
    for name in role_alias_descriptions():
        if name in targets:
            shape[name] = ("target", None)
            continue
        fallback = fallbacks.get(name)
        if fallback is not None:
            clean_reference, _effort = split_model_effort(fallback)
            shape[name] = ("fallback", clean_reference[1:])
            continue
        shape[name] = ("empty", None)
    return shape


def _shape_diff(
    actual: Mapping[str, tuple[str, str | None]],
    expected: Mapping[str, tuple[str, str | None]],
) -> str:
    names = sorted(set(actual) | set(expected))
    drifted = [
        f"{name}: expected {expected.get(name)!r}, got {actual.get(name)!r}"
        for name in names
        if actual.get(name) != expected.get(name)
    ]
    return "; ".join(drifted)


def _fixture_aliases() -> dict[str, dict[str, str]]:
    aliases: dict[str, dict[str, str]] = {}
    for name in _DECLARED_ROLE_ALIAS_NAMES:
        entry = {"description": FROZEN_DESCRIPTIONS[name]}
        target = FROZEN_TARGETS.get(name)
        fallback = FROZEN_FALLBACKS.get(name)
        if target is not None:
            entry["target"] = target
        if fallback is not None:
            entry["fallback"] = fallback
        aliases[name] = entry
    return aliases


def _parse_fixture_aliases(aliases: Mapping[str, Mapping[str, str]]) -> None:
    _parse_model_alias_defaults(
        yaml.safe_dump(
            {"schema_version": 1, "aliases": aliases},
            sort_keys=False,
        ),
        source="test defaults",
    )


def test_every_declared_name_has_a_description_and_vice_versa(
    real_model_alias_defaults: None,
) -> None:
    """A role alias name constant without a YAML entry, or vice versa, fails."""
    assert set(role_alias_descriptions()) == _DECLARED_ROLE_ALIAS_NAMES


def test_fallback_and_target_are_mutually_exclusive_and_cover_every_role(
    real_model_alias_defaults: None,
) -> None:
    fallbacks = role_alias_fallbacks()
    targets = implicit_alias_targets()

    assert set(fallbacks).isdisjoint(targets)
    assert set(fallbacks) | set(targets) | {DEFAULT_MODEL_ALIAS_NAME} == (
        _DECLARED_ROLE_ALIAS_NAMES
    )


def test_default_alias_has_neither_fallback_nor_target(
    real_model_alias_defaults: None,
) -> None:
    assert DEFAULT_MODEL_ALIAS_NAME not in role_alias_fallbacks()
    assert DEFAULT_MODEL_ALIAS_NAME not in implicit_alias_targets()


def test_every_description_is_a_nonempty_stripped_string(
    real_model_alias_defaults: None,
) -> None:
    for name, description in role_alias_descriptions().items():
        assert isinstance(description, str) and description, name
        assert description == description.strip(), name


def test_every_target_parses_under_the_selector_grammar(
    real_model_alias_defaults: None,
) -> None:
    for name, target in implicit_alias_targets().items():
        try:
            selector = parse_model_alias_selector(target)
        except ModelAliasSelectorError as exc:
            raise AssertionError(
                f"'{name}' target {target!r} is malformed: {exc}"
            ) from exc
        if selector is not None:
            assert selector.members


def test_every_fallback_resolves_to_a_declared_alias_name(
    real_model_alias_defaults: None,
) -> None:
    for name, fallback in role_alias_fallbacks().items():
        clean, _effort = split_model_effort(fallback)
        assert clean.startswith("@"), (
            f"'{name}' fallback {fallback!r} must be an @-reference"
        )
        referenced = clean[1:]
        assert referenced in _DECLARED_ROLE_ALIAS_NAMES, (
            f"'{name}' fallback references unknown alias '@{referenced}'"
        )


def test_shipped_defaults_match_the_frozen_graph_shape(
    real_model_alias_defaults: None,
) -> None:
    actual = _current_shape_signature()
    assert actual == FROZEN_ALIAS_SHAPE, (
        "shipped model alias graph shape drifted; update "
        "tests/_model_alias_defaults_fixture.py when this graph-shape change "
        f"is intended: {_shape_diff(actual, FROZEN_ALIAS_SHAPE)}"
    )


def test_parser_rejects_unknown_fallback_reference() -> None:
    aliases = _fixture_aliases()
    aliases[EPIC_LANDER_MODEL_ALIAS_NAME]["fallback"] = "@nope"

    with pytest.raises(RuntimeError, match="epic_lander.*unknown alias '@nope'"):
        _parse_fixture_aliases(aliases)


def test_parser_rejects_unparseable_target() -> None:
    aliases = _fixture_aliases()
    aliases[CHEAP_MODEL_ALIAS_NAME]["target"] = "claude/opus || || codex/o3"

    with pytest.raises(RuntimeError, match="cheap.*empty members"):
        _parse_fixture_aliases(aliases)


def test_parser_rejects_two_alias_fallback_cycle() -> None:
    aliases = _fixture_aliases()
    aliases[SMART_MODEL_ALIAS_NAME]["fallback"] = "@smartest"
    aliases[SMARTEST_MODEL_ALIAS_NAME].pop("target")
    aliases[SMARTEST_MODEL_ALIAS_NAME]["fallback"] = "@smart"

    with pytest.raises(RuntimeError, match="smart.*cycle|cycle.*smart"):
        _parse_fixture_aliases(aliases)
