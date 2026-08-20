"""Tests for the validated Rust snippet catalog composition facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sase.core import snippet_catalog_facade


def _payload(
    *,
    templates: dict[str, str] | object | None = None,
    alias_provenance: dict[str, str] | object | None = None,
    triggers: dict[str, object] | object | None = None,
    calls: dict[str, object] | object | None = None,
    outbound: dict[str, object] | object | None = None,
    inbound: dict[str, object] | object | None = None,
    diagnostics: list[object] | object | None = None,
    explicit: dict[str, str] | None = None,
) -> dict[str, object]:
    keys = explicit or {"foo": "foo body"}
    default_triggers = {
        trigger: {"trigger": trigger, "valid": True, "reason": None} for trigger in keys
    }
    empty_lists = {trigger: [] for trigger in keys}
    return {
        "templates": {"Foo": "Foo body", "foo": "foo body"}
        if templates is None
        else templates,
        "alias_provenance": {"Foo": "foo"}
        if alias_provenance is None
        else alias_provenance,
        "triggers": default_triggers if triggers is None else triggers,
        "calls": empty_lists if calls is None else calls,
        "outbound": empty_lists if outbound is None else outbound,
        "inbound": empty_lists if inbound is None else inbound,
        "diagnostics": [] if diagnostics is None else diagnostics,
    }


def _patch_binding(monkeypatch, payload: object) -> None:
    monkeypatch.setattr(
        snippet_catalog_facade,
        "require_rust_binding",
        lambda _name: lambda _templates: payload,
    )


def test_compose_snippet_catalog_forwards_and_normalizes(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def binding(templates: dict[str, str]) -> dict[str, object]:
        calls.append(templates)
        return _payload(
            calls={
                "foo": [
                    {
                        "authored_target": "helper",
                        "canonical_target": None,
                        "positional_args": ["x"],
                        "span": {"start": 4, "end": 13},
                        "status": "missing",
                    }
                ]
            },
            outbound={"foo": ["helper"]},
            inbound={"foo": []},
            diagnostics=[
                {
                    "code": "missing_target",
                    "message": "foo calls missing helper",
                    "trigger": "foo",
                    "target": "helper",
                    "span": {"start": 4, "end": 13},
                    "cycle": None,
                }
            ],
        )

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
    assert result.triggers["foo"].valid is True
    assert result.calls["foo"][0].authored_target == "helper"
    assert result.calls["foo"][0].positional_args == ("x",)
    assert result.calls["foo"][0].span.start == 4
    assert result.outbound["foo"] == ("helper",)
    assert result.diagnostics[0].code == "missing_target"
    with pytest.raises(FrozenInstanceError):
        result.templates = {}  # type: ignore[misc]


def test_validate_snippet_trigger_forwards_wire(monkeypatch) -> None:
    def require_binding(name: str):
        assert name == "validate_snippet_trigger"
        return lambda trigger: {
            "trigger": trigger,
            "valid": False,
            "reason": "invalid_characters",
        }

    monkeypatch.setattr(
        snippet_catalog_facade,
        "require_rust_binding",
        require_binding,
    )

    result = snippet_catalog_facade.validate_snippet_trigger("bad-name!")

    assert result.trigger == "bad-name!"
    assert result.valid is False
    assert result.reason == "invalid_characters"


@pytest.mark.parametrize(
    ("payload", "match", "error"),
    [
        ([], "non-mapping top-level payload", TypeError),
        (
            _payload(templates=[]),
            "'templates' must be a mapping",
            TypeError,
        ),
        (
            _payload(alias_provenance=[]),
            "'alias_provenance' must be a mapping",
            TypeError,
        ),
        (
            _payload(templates={1: "body"}),
            "'templates' contains non-string key",
            TypeError,
        ),
        (
            _payload(templates={"foo": 1}),
            "'templates' contains non-string value",
            TypeError,
        ),
        (
            _payload(alias_provenance={1: "foo"}),
            "'alias_provenance' contains non-string key",
            TypeError,
        ),
        (
            _payload(alias_provenance={"Foo": 1}),
            "'alias_provenance' contains non-string value",
            TypeError,
        ),
        (
            _payload(triggers=[]),
            "'triggers' must be a mapping",
            TypeError,
        ),
        (
            _payload(calls=[]),
            "'calls' must be a mapping",
            TypeError,
        ),
        (
            _payload(outbound=[]),
            "'outbound' must be a mapping",
            TypeError,
        ),
        (
            _payload(inbound={"foo": ["foo", 1]}),
            "'inbound' contains non-string entry",
            TypeError,
        ),
        (
            _payload(diagnostics={}),
            "'diagnostics' must be a list",
            TypeError,
        ),
        (
            _payload(
                calls={
                    "foo": [
                        {
                            "authored_target": "helper",
                            "canonical_target": None,
                            "positional_args": [],
                            "span": {"start": 0, "end": 1},
                            "status": "nope",
                        }
                    ]
                }
            ),
            "status must be one of",
            ValueError,
        ),
    ],
)
def test_compose_snippet_catalog_rejects_malformed_mapping_fields(
    monkeypatch,
    payload: object,
    match: str,
    error: type[Exception],
) -> None:
    _patch_binding(monkeypatch, payload)

    with pytest.raises(error, match=match):
        snippet_catalog_facade.compose_snippet_catalog({"foo": "body"})


@pytest.mark.parametrize(
    ("explicit", "payload", "match"),
    [
        (
            {"foo": "body"},
            _payload(
                templates={"foo": "body"},
                alias_provenance={"Foo": "foo"},
                explicit={"foo": "body"},
            ),
            "missing final template 'Foo'",
        ),
        (
            {"bar": "body"},
            _payload(
                templates={"Foo": "Body", "bar": "body"},
                alias_provenance={"Foo": "foo"},
                explicit={"bar": "body"},
            ),
            "missing explicit source 'foo'",
        ),
        (
            {"foo": "body"},
            _payload(triggers={}, explicit={"foo": "body"}),
            "'triggers' is missing explicit key 'foo'",
        ),
        (
            {"foo": "body"},
            _payload(
                triggers={
                    "foo": {"trigger": "foo", "valid": True, "reason": None},
                    "bar": {"trigger": "bar", "valid": True, "reason": None},
                }
            ),
            "'triggers' contains unexpected explicit key 'bar'",
        ),
        (
            {"foo": "body"},
            _payload(
                calls={
                    "foo": [
                        {
                            "authored_target": "bar",
                            "canonical_target": "bar",
                            "positional_args": [],
                            "span": {"start": 0, "end": 3},
                            "status": "resolved",
                        }
                    ]
                }
            ),
            "canonical target 'bar' on 'foo' is not explicit",
        ),
    ],
)
def test_compose_snippet_catalog_rejects_invalid_provenance(
    monkeypatch,
    explicit: dict[str, str],
    payload: object,
    match: str,
) -> None:
    _patch_binding(monkeypatch, payload)

    with pytest.raises(ValueError, match=match):
        snippet_catalog_facade.compose_snippet_catalog(explicit)


def test_compose_snippet_catalog_live_binding_exposes_graph_fields() -> None:
    result = snippet_catalog_facade.compose_snippet_catalog(
        {"foo": "foo #[helper]$0", "helper": "helper $1$0"}
    )

    assert result.alias_provenance == {"Foo": "foo", "Helper": "helper"}
    assert result.triggers["foo"].valid is True
    assert result.calls["foo"][0].authored_target == "helper"
    assert result.calls["foo"][0].canonical_target == "helper"
    assert result.calls["foo"][0].status == "resolved"
    assert result.outbound["foo"] == ("helper",)
    assert result.inbound["helper"] == ("foo",)
    assert result.diagnostics == ()


def test_validate_snippet_trigger_live_binding() -> None:
    valid = snippet_catalog_facade.validate_snippet_trigger("fix_it2")
    invalid = snippet_catalog_facade.validate_snippet_trigger("bad-name!")

    assert valid == snippet_catalog_facade.SnippetTriggerValidation(
        trigger="fix_it2", valid=True, reason=None
    )
    assert invalid.valid is False
    assert invalid.reason == "invalid_characters"
