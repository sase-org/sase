"""Coverage for the narrow legacy v1 transport adapter."""

from __future__ import annotations

from typing import Any

from sase.core import machine_hood_facade as facade


def test_v1_transport_adapter_qualifies_once_and_preserves_archive_prefix(
    monkeypatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def binding(name: str):
        def invoke(*args: Any) -> str:
            calls.append((name, args))
            return f"{args[1]}.{args[0]}"

        return invoke

    facade._core.cache_clear()
    monkeypatch.setattr(facade, "require_rust_binding", binding)

    assert facade.machine_qualify_v1_transport_agent_name("foo", "athena") == (
        "athena.foo"
    )
    assert (
        facade.machine_qualify_v1_transport_agent_name("athena.foo", "athena")
        == "athena.foo"
    )
    assert (
        facade.machine_qualify_v1_transport_agent_name("260722.foo", "athena")
        == "260722.athena.foo"
    )
    assert calls == [
        ("qualify_machine_agent_name", ("foo", "athena")),
        ("qualify_machine_agent_name", ("foo", "athena")),
    ]
    facade._core.cache_clear()
