"""Tests for the bundled ``model_alias_defaults.yml`` and its parser."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
import yaml  # type: ignore[import-untyped]

from sase.llm_provider.load_balancing import (
    ModelAliasSelectorError,
    parse_model_alias_selector,
)
from sase.llm_provider import registry
from sase.llm_provider.model_alias_policy import (
    LARGE_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME,
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
        XSMALL_MODEL_ALIAS_NAME,
        SMALL_MODEL_ALIAS_NAME,
        MEDIUM_MODEL_ALIAS_NAME,
        LARGE_MODEL_ALIAS_NAME,
        XLARGE_MODEL_ALIAS_NAME,
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

    assert not fallbacks
    assert set(targets) == _DECLARED_ROLE_ALIAS_NAMES


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
    aliases[SMALL_MODEL_ALIAS_NAME].pop("target")
    aliases[SMALL_MODEL_ALIAS_NAME]["fallback"] = "@nope"

    with pytest.raises(RuntimeError, match="small.*unknown alias '@nope'"):
        _parse_fixture_aliases(aliases)


def test_parser_rejects_unparseable_target() -> None:
    aliases = _fixture_aliases()
    aliases[XSMALL_MODEL_ALIAS_NAME]["target"] = "claude/opus || || codex/o3"

    with pytest.raises(RuntimeError, match="xsmall.*empty members"):
        _parse_fixture_aliases(aliases)


def test_parser_rejects_size_alias_without_target_or_fallback() -> None:
    aliases = _fixture_aliases()
    aliases[LARGE_MODEL_ALIAS_NAME].pop("target")

    with pytest.raises(RuntimeError, match="large.*must set either"):
        _parse_fixture_aliases(aliases)


def test_parser_rejects_two_alias_fallback_cycle() -> None:
    aliases = _fixture_aliases()
    aliases[SMALL_MODEL_ALIAS_NAME].pop("target")
    aliases[SMALL_MODEL_ALIAS_NAME]["fallback"] = "@medium"
    aliases[MEDIUM_MODEL_ALIAS_NAME].pop("target")
    aliases[MEDIUM_MODEL_ALIAS_NAME]["fallback"] = "@small"

    with pytest.raises(RuntimeError, match="small.*cycle|cycle.*small"):
        _parse_fixture_aliases(aliases)


def test_every_shipped_selector_member_names_a_registered_provider_model(
    real_model_alias_defaults: None,
) -> None:
    """Every `provider/model` selector member must name a real, published model.

    Guards against typos like `grok/grok4.6` or a member pointing at a
    provider the registry does not know about.
    """
    provider_names = set(registry.registered_provider_names())
    model_to_provider = registry.model_to_provider_map()

    for name, target in implicit_alias_targets().items():
        selector = parse_model_alias_selector(target)
        if selector is None:
            continue
        for member in selector.members:
            clean_member, _effort = split_model_effort(member)
            if "/" not in clean_member:
                continue
            provider, model = clean_member.split("/", 1)
            assert provider in provider_names, (
                f"'{name}' member {member!r} names unknown provider '{provider}'"
            )
            assert model_to_provider.get(model) == provider, (
                f"'{name}' member {member!r} names a model '{model}' that "
                f"provider '{provider}' does not publish"
            )
