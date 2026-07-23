"""Tests for the validated Rust snippet catalog composition facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sase.core import snippet_catalog_facade


def test_compose_snippet_catalog_forwards_and_normalizes(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def binding(templates: dict[str, str]) -> dict[str, object]:
        calls.append(templates)
        return {
            "templates": {"Foo": "Foo body", "foo": "foo body"},
            "alias_provenance": {"Foo": "foo"},
        }

    def require_binding(name: str):
        assert name == "compose_snippet_catalog"
        return binding

    monkeypatch.setattr(
        snippet_catalog_facade,
        "require_rust_binding",
        require_binding,
    )

    result = snippet_catalog_facade.compose_snippet_catalog({"foo": "foo body"})

    assert calls == [{"foo": "foo body"}]
    assert type(result.templates) is dict
    assert type(result.alias_provenance) is dict
    assert result.templates == {"Foo": "Foo body", "foo": "foo body"}
    assert result.alias_provenance == {"Foo": "foo"}
    with pytest.raises(FrozenInstanceError):
        result.templates = {}  # type: ignore[misc]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ([], "non-mapping top-level payload"),
        (
            {"templates": [], "alias_provenance": {}},
            "'templates' must be a mapping",
        ),
        (
            {"templates": {}, "alias_provenance": []},
            "'alias_provenance' must be a mapping",
        ),
        (
            {"templates": {1: "body"}, "alias_provenance": {}},
            "'templates' contains non-string key",
        ),
        (
            {"templates": {"foo": 1}, "alias_provenance": {}},
            "'templates' contains non-string value",
        ),
        (
            {"templates": {"foo": "body"}, "alias_provenance": {1: "foo"}},
            "'alias_provenance' contains non-string key",
        ),
        (
            {"templates": {"foo": "body"}, "alias_provenance": {"Foo": 1}},
            "'alias_provenance' contains non-string value",
        ),
    ],
)
def test_compose_snippet_catalog_rejects_malformed_mapping_fields(
    monkeypatch,
    payload: object,
    match: str,
) -> None:
    monkeypatch.setattr(
        snippet_catalog_facade,
        "require_rust_binding",
        lambda _name: lambda _templates: payload,
    )

    with pytest.raises(TypeError, match=match):
        snippet_catalog_facade.compose_snippet_catalog({"foo": "body"})


@pytest.mark.parametrize(
    ("explicit", "payload", "match"),
    [
        (
            {"foo": "body"},
            {
                "templates": {"foo": "body"},
                "alias_provenance": {"Foo": "foo"},
            },
            "missing final template 'Foo'",
        ),
        (
            {"bar": "body"},
            {
                "templates": {"Foo": "Body", "bar": "body"},
                "alias_provenance": {"Foo": "foo"},
            },
            "missing explicit source 'foo'",
        ),
    ],
)
def test_compose_snippet_catalog_rejects_invalid_provenance(
    monkeypatch,
    explicit: dict[str, str],
    payload: object,
    match: str,
) -> None:
    monkeypatch.setattr(
        snippet_catalog_facade,
        "require_rust_binding",
        lambda _name: lambda _templates: payload,
    )

    with pytest.raises(ValueError, match=match):
        snippet_catalog_facade.compose_snippet_catalog(explicit)
