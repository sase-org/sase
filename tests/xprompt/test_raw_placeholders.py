"""Tests for the typed raw-placeholder Rust facade."""

from __future__ import annotations

from typing import Any

import sase.xprompt.raw_placeholders as facade


def test_fields_rehydrate_binding_payload(monkeypatch: Any) -> None:
    calls: list[tuple[str, int]] = []

    def fake_require(name: str) -> Any:
        assert name == "raw_placeholder_fields"

        def binding(text: str, context_width: int) -> list[dict[str, object]]:
            calls.append((text, context_width))
            return [
                {
                    "text": "the plan",
                    "occurrences": 2,
                    "context": "fix <the plan> today",
                }
            ]

        return binding

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    fields = facade.raw_placeholder_fields("fix <the plan> today")

    assert calls == [("fix <the plan> today", facade.DEFAULT_CONTEXT_WIDTH)]
    assert fields == (
        facade.RawPlaceholderField(
            text="the plan",
            occurrences=2,
            context="fix <the plan> today",
        ),
    )


def test_substitute_passes_values_to_binding(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_require(name: str) -> Any:
        assert name == "substitute_raw_placeholders"

        def binding(text: str, values: dict[str, str]) -> str:
            calls.append((text, values))
            return "fix oauth"

        return binding

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    assert (
        facade.substitute_raw_placeholders("fix <service>", {"service": "oauth"})
        == "fix oauth"
    )
    assert calls == [("fix <service>", {"service": "oauth"})]


def test_input_names_rehydrate_binding_payload(monkeypatch: Any) -> None:
    calls: list[list[str]] = []

    def fake_require(name: str) -> Any:
        assert name == "placeholder_input_names"

        def binding(texts: list[str]) -> list[str]:
            calls.append(texts)
            return ["the_plan", "arg_2fa_code"]

        return binding

    monkeypatch.setattr(facade, "require_rust_binding", fake_require)

    assert facade.placeholder_input_names(("The Plan", "2fa code")) == (
        "the_plan",
        "arg_2fa_code",
    )
    assert calls == [["The Plan", "2fa code"]]


def test_real_binding_fields_are_raw_only() -> None:
    fields = facade.raw_placeholder_fields(
        "`<literal>` <live> and <live>\n```\n<code>\n```",
    )

    assert fields == (
        facade.RawPlaceholderField(
            text="live",
            occurrences=2,
            context="`<literal>` <live> and <live>",
        ),
    )


def test_real_binding_substitutes_raw_only_without_rescanning_values() -> None:
    text = "`<x>` <x>\n```\n<x>\n```\n<y>"

    assert (
        facade.substitute_raw_placeholders(text, {"x": "<y>", "y": "done"})
        == "`<x>` <y>\n```\n<x>\n```\ndone"
    )


def test_real_binding_input_names() -> None:
    assert facade.placeholder_input_names(
        ["the plan", "PR #", "2fa code", "???", "código"],
    ) == ("the_plan", "pr", "arg_2fa_code", "arg", "código")
