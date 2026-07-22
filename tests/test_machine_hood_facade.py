"""Tests for the Python machine-hood application boundary."""

from __future__ import annotations

from typing import Any

import pytest

from sase.core import machine_hood_facade as facade


def test_rust_machine_name_bindings_are_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def binding(name: str):
        def invoke(*args: Any) -> Any:
            calls.append((name, args))
            return {
                "qualify_machine_agent_name": "athena.foo",
                "strip_machine_agent_name": "foo",
                "machine_hood_of": "athena",
            }.get(name)

        return invoke

    facade._core.cache_clear()
    monkeypatch.setattr(facade, "require_rust_binding", binding)

    facade._validate_machine_name("athena")
    assert facade._qualify_machine_agent_name("foo", "athena") == "athena.foo"
    assert facade._strip_machine_agent_name("athena.foo", "athena") == "foo"
    assert facade._machine_hood_of("athena.foo", ("athena", "zeus")) == "athena"
    assert calls == [
        ("validate_machine_name", ("athena",)),
        ("qualify_machine_agent_name", ("foo", "athena")),
        ("strip_machine_agent_name", ("athena.foo", "athena")),
        ("machine_hood_of", ("athena.foo", ["athena", "zeus"])),
    ]
    facade._core.cache_clear()


def test_local_helpers_qualify_once_and_preserve_foreign_hoods() -> None:
    identity = facade.MachineHoodIdentity("athena", ("athena", "zeus"))

    assert facade.qualify_local_agent_name("foo", identity) == "athena.foo"
    assert facade.qualify_local_agent_name("athena.foo", identity) == "athena.foo"
    assert (
        facade.qualify_local_agent_name("foo.bar--code", identity)
        == "athena.foo.bar--code"
    )
    assert facade.strip_local_agent_name("athena.foo", identity) == "foo"
    assert facade.qualify_local_agent_name("zeus.foo", identity) == "zeus.foo"
    assert facade.strip_local_agent_name("zeus.foo", identity) == "zeus.foo"
    assert facade.known_foreign_machine("zeus.foo", identity) == "zeus"


def test_local_lookup_equates_bare_and_qualified_exact_first() -> None:
    identity = facade.MachineHoodIdentity("athena", ("athena", "zeus"))

    assert facade.local_agent_name_lookup_candidates("foo", identity) == (
        "foo",
        "athena.foo",
    )
    assert facade.local_agent_name_lookup_candidates("athena.foo", identity) == (
        "athena.foo",
        "foo",
    )
    assert facade.local_agent_name_lookup_candidates("zeus.foo", identity) == (
        "zeus.foo",
    )
    assert facade.canonical_local_agent_name_key("foo", identity) == "foo"
    assert facade.canonical_local_agent_name_key("athena.foo", identity) == "foo"


def test_unconfigured_helpers_are_strict_no_ops() -> None:
    identity = facade.MachineHoodIdentity.unconfigured()

    assert facade.qualify_local_agent_name("foo", identity) == "foo"
    assert facade.strip_local_agent_name("athena.foo", identity) == "athena.foo"
    assert facade.known_foreign_machine("zeus.foo", identity) is None
    assert facade.local_agent_name_lookup_candidates("foo", identity) == ("foo",)


def test_dismissed_prefix_stays_outside_local_machine_hood() -> None:
    identity = facade.MachineHoodIdentity("athena", ("athena",))

    assert (
        facade.qualify_local_agent_name("260722.foo", identity) == "260722.athena.foo"
    )
    assert facade.strip_local_agent_name("260722.athena.foo", identity) == "260722.foo"
