"""Adapter coverage for agent-tab keys, tokens, and the batched catalog."""

from __future__ import annotations

import pytest

import sase.core.agent_tab as adapter
from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabCatalog,
    AgentTabKey,
    agent_tab_key_token,
    build_agent_tab_catalog,
    parse_agent_tab_key_token,
)


def _local(tab: str | None = None) -> dict:
    return {"agent_tab": tab, "owner": {"kind": "local"}}


def _remote(alias: str, installation_id: str | None, tab: str | None = None) -> dict:
    return {
        "agent_tab": tab,
        "owner": {
            "kind": "remote",
            "installation_id": installation_id,
            "alias": alias,
        },
    }


def test_key_constructors() -> None:
    assert AgentTabKey.default() == DEFAULT_AGENT_TAB_KEY
    assert AgentTabKey.default().value == ""
    assert AgentTabKey.machine("id-1") == AgentTabKey("machine", "id-1")
    assert AgentTabKey.unresolved_machine("ghost") == AgentTabKey(
        "unresolved_machine", "ghost"
    )
    assert AgentTabKey.named("sase") == AgentTabKey("named", "sase")


def test_keys_are_hashable() -> None:
    assert hash(AgentTabKey.named("sase")) == hash(AgentTabKey("named", "sase"))
    assert len({AgentTabKey.default(), AgentTabKey.default()}) == 1


def test_token_round_trip() -> None:
    for key in (
        AgentTabKey.default(),
        AgentTabKey.machine("install-1"),
        AgentTabKey.named("sase"),
    ):
        token = agent_tab_key_token(key)
        assert isinstance(token, str)
        assert parse_agent_tab_key_token(token) == key


def test_token_shapes() -> None:
    assert agent_tab_key_token(AgentTabKey.default()) == "default"
    assert agent_tab_key_token(AgentTabKey.machine("abc")) == "machine:abc"
    assert agent_tab_key_token(AgentTabKey.named("sase")) == "named:sase"


def test_unresolved_machine_key_has_no_token() -> None:
    assert agent_tab_key_token(AgentTabKey.unresolved_machine("ghost")) is None


@pytest.mark.parametrize(
    "token",
    [None, "", "bogus", "machine:", "named:", "unresolved_machine:ghost", "default:x"],
)
def test_malformed_tokens_parse_to_none(token: object) -> None:
    assert parse_agent_tab_key_token(token) is None


def test_zero_roots_gives_empty_catalog() -> None:
    catalog = build_agent_tab_catalog(
        [], machine_mode=False, machine_order=[], named_order={}
    )
    assert isinstance(catalog, AgentTabCatalog)
    assert catalog.keys == ()
    assert catalog.entries == ()


def test_one_local_root_is_the_default_tab() -> None:
    catalog = build_agent_tab_catalog(
        [_local()], machine_mode=False, machine_order=[], named_order={}
    )
    assert catalog.keys == (AgentTabKey.default(),)
    assert [(e.key, e.label, e.root_count) for e in catalog.entries] == [
        (AgentTabKey.default(), "main", 1)
    ]


def test_two_tabs_split_roots() -> None:
    catalog = build_agent_tab_catalog(
        [_local(), _local("sase"), _local("sase")],
        machine_mode=False,
        machine_order=[],
        named_order={},
    )
    assert catalog.keys == (
        AgentTabKey.default(),
        AgentTabKey.named("sase"),
        AgentTabKey.named("sase"),
    )
    counts = {entry.key: entry.root_count for entry in catalog.entries}
    assert counts == {AgentTabKey.default(): 1, AgentTabKey.named("sase"): 2}


def test_many_tabs_count_once_each() -> None:
    roots = [_local()] + [_local(name) for name in ("b", "a", "c", "b")]
    catalog = build_agent_tab_catalog(
        roots, machine_mode=False, machine_order=[], named_order={}
    )
    counts = {entry.key: entry.root_count for entry in catalog.entries}
    assert counts == {
        AgentTabKey.default(): 1,
        AgentTabKey.named("a"): 1,
        AgentTabKey.named("b"): 2,
        AgentTabKey.named("c"): 1,
    }


def test_machine_mode_splits_local_and_remote() -> None:
    roots = [_local(), _remote("apollo", "install-apollo")]
    catalog = build_agent_tab_catalog(
        roots,
        machine_mode=True,
        machine_order=[("install-apollo", "apollo")],
        named_order={},
    )
    assert catalog.keys == (
        AgentTabKey.default(),
        AgentTabKey.machine("install-apollo"),
    )
    labels = {entry.key: entry.label for entry in catalog.entries}
    assert labels[AgentTabKey.default()] == "⌨ local"
    assert labels[AgentTabKey.machine("install-apollo")] == "⌨ apollo"


def test_machine_mode_off_collapses_remote_to_default() -> None:
    catalog = build_agent_tab_catalog(
        [_local(), _remote("apollo", "install-apollo")],
        machine_mode=False,
        machine_order=[],
        named_order={},
    )
    assert catalog.keys == (AgentTabKey.default(), AgentTabKey.default())
    assert len(catalog.entries) == 1


def test_alias_only_remote_is_unresolved() -> None:
    catalog = build_agent_tab_catalog(
        [_remote("ghost", None)],
        machine_mode=True,
        machine_order=[("install-apollo", "apollo")],
        named_order={},
    )
    key = AgentTabKey.unresolved_machine("ghost")
    assert catalog.keys == (key,)
    assert agent_tab_key_token(catalog.keys[0]) is None


def test_named_order_sorts_named_tabs() -> None:
    roots = [_local("b"), _local("a"), _local()]
    catalog = build_agent_tab_catalog(
        roots,
        machine_mode=False,
        machine_order=[],
        named_order={"a": 0, "b": 5},
    )
    assert [entry.key for entry in catalog.entries] == [
        AgentTabKey.default(),
        AgentTabKey.named("a"),
        AgentTabKey.named("b"),
    ]


def test_one_binding_call_per_roster(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list, dict]] = []
    real = adapter.require_rust_binding("build_agent_tab_catalog")

    def _counting(roots: list, options: dict) -> dict:
        calls.append((roots, options))
        return real(roots, options)

    monkeypatch.setattr(adapter, "require_rust_binding", lambda name: _counting)
    build_agent_tab_catalog(
        [_local(), _local("sase")], machine_mode=False, machine_order=[], named_order={}
    )
    assert len(calls) == 1
    assert calls[0][0] == [
        {"agent_tab": None, "owner": {"kind": "local"}},
        {"agent_tab": "sase", "owner": {"kind": "local"}},
    ]
    assert set(calls[0][1]) == {"machine_mode", "machine_order", "named_order"}
