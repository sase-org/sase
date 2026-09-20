"""Tests for the shortest-``%model``-spelling formatter."""

from __future__ import annotations

import pytest

from sase.llm_provider import model_directive_label as label_module
from sase.llm_provider.model_directive_label import format_model_directive_label


def _patch_probe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mapping: dict[str, str] | None = None,
    aliases: set[str] | None = None,
) -> list[tuple[str, object]]:
    """Stub the resolver and alias names; return the recorded resolver calls.

    ``mapping`` plays the role of ``model_to_provider_map()``: a mapped bare name
    resolves to its provider, an unmapped one resolves to ``(None, model)`` (the
    ambient-default-provider fallback).
    """
    calls: list[tuple[str, object]] = []
    table = dict(mapping or {})

    def fake_resolve(
        model_override: str, *args: object, **kwargs: object
    ) -> tuple[str | None, str]:
        calls.append((model_override, kwargs.get("consume")))
        return table.get(model_override), model_override

    monkeypatch.setattr(label_module, "resolve_model_provider", fake_resolve)
    monkeypatch.setattr(label_module, "model_alias_names", lambda: set(aliases or ()))
    return calls


def test_bare_model_when_map_points_at_this_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(monkeypatch, mapping={"grok-4.6": "grok", "opus": "claude"})

    assert format_model_directive_label("grok", "grok-4.6") == "grok-4.6"
    assert format_model_directive_label("claude", "opus") == "opus"


def test_explicit_form_when_map_points_at_a_different_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(monkeypatch, mapping={"shared-model": "claude"})

    assert format_model_directive_label("codex", "shared-model") == (
        "codex/shared-model"
    )


def test_explicit_form_when_bare_name_is_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_probe(monkeypatch, mapping={})

    assert format_model_directive_label("codex", "some-unmapped-model") == (
        "codex/some-unmapped-model"
    )


def test_explicit_form_when_bare_name_collides_with_an_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The resolver would round-trip ``large`` to claude, but ``%model:large``
    # means the alias, which may be a rotating pool.
    _patch_probe(monkeypatch, mapping={"large": "claude"}, aliases={"large"})

    assert format_model_directive_label("claude", "large") == "claude/large"


@pytest.mark.parametrize("failing", ["resolve", "aliases"])
def test_explicit_form_when_probe_raises(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    _patch_probe(monkeypatch, mapping={"opus": "claude"})

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(
        label_module,
        "resolve_model_provider" if failing == "resolve" else "model_alias_names",
        boom,
    )

    assert format_model_directive_label("claude", "opus") == "claude/opus"


def test_falsy_provider_returns_bare_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_probe(monkeypatch)

    assert format_model_directive_label("", "mystery-model") == "mystery-model"
    assert format_model_directive_label(None, "mystery-model") == "mystery-model"
    assert calls == []


def test_falsy_model_delegates_to_provider_model_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_probe(monkeypatch)

    assert format_model_directive_label("grok", "") == "GROK"
    assert format_model_directive_label("grok", None) == "GROK"
    assert format_model_directive_label() == "Agent"
    assert format_model_directive_label("", "") == "Agent"
    assert calls == []


def test_probe_never_consumes_the_pool_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_probe(monkeypatch, mapping={"opus": "claude"})

    format_model_directive_label("claude", "opus")

    assert calls == [("opus", False)]
