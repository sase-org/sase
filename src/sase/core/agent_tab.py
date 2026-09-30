"""Thin Python wrapper around the Rust agent-tab bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from collections.abc import Iterable, Mapping

from sase.core.rust import require_rust_binding

AgentTabKind = Literal["default", "machine", "unresolved_machine", "named"]


@dataclass(frozen=True, slots=True)
class AgentTabKey:
    """Hashable identity for one agent tab.

    ``value`` holds the installation id for ``machine`` keys, the alias for
    ``unresolved_machine`` keys, the canonical tab name for ``named`` keys,
    and ``""`` for the ``default`` key.
    """

    kind: AgentTabKind
    value: str = ""

    @classmethod
    def default(cls) -> AgentTabKey:
        """Return the key for the default (main/local) tab."""
        return cls("default")

    @classmethod
    def machine(cls, installation_id: str) -> AgentTabKey:
        """Return the key for one resolved machine tab."""
        return cls("machine", installation_id)

    @classmethod
    def unresolved_machine(cls, alias: str) -> AgentTabKey:
        """Return the key for a machine tab with no pinned installation id."""
        return cls("unresolved_machine", alias)

    @classmethod
    def named(cls, name: str) -> AgentTabKey:
        """Return the key for one named tab (canonical, lowercased)."""
        return cls("named", name)


DEFAULT_AGENT_TAB_KEY = AgentTabKey.default()


def agent_tab_key_token(key: AgentTabKey) -> str | None:
    """Return the persistence token for *key*, if it has one.

    Tokens are ``default``, ``machine:<id>``, and ``named:<name>``.
    Unresolved-machine keys have no token, so they are never persisted.
    """
    if key.kind == "default":
        return "default"
    if key.kind == "machine":
        return f"machine:{key.value}" if key.value else None
    if key.kind == "named":
        return f"named:{key.value}" if key.value else None
    return None


def parse_agent_tab_key_token(token: object) -> AgentTabKey | None:
    """Parse a persistence token back into an :class:`AgentTabKey`.

    Returns None for anything that is not a well-formed ``default``,
    ``machine:<id>``, or ``named:<name>`` token.
    """
    if not isinstance(token, str) or not token:
        return None
    if token == "default":
        return AgentTabKey.default()
    kind, sep, value = token.partition(":")
    if not sep or not value:
        return None
    if kind == "machine":
        return AgentTabKey.machine(value)
    if kind == "named":
        try:
            canonical = canonicalize_agent_tab(value)
        except Exception:  # noqa: BLE001 - malformed tokens are dropped.
            return None
        if canonical is None:
            return None
        return AgentTabKey.named(canonical)
    return None


@dataclass(frozen=True, slots=True)
class AgentTabCatalogEntry:
    """One ordered tab with its label and root count."""

    key: AgentTabKey
    kind: str
    label: str
    root_count: int


@dataclass(frozen=True, slots=True)
class _AgentTabCatalog:
    """Batched tab catalog for one roster.

    ``keys`` is index-aligned with the input roots; ``entries`` holds the
    ordered, deduplicated tabs.
    """

    keys: tuple[AgentTabKey, ...]
    entries: tuple[AgentTabCatalogEntry, ...]


def _key_from_wire(raw: object) -> AgentTabKey:
    """Convert one binding key dict into an :class:`AgentTabKey`."""
    if not isinstance(raw, dict):
        raise TypeError(f"sase_core_rs returned non-dict tab key: {raw!r}")
    kind = raw.get("kind")
    if kind == "default":
        return AgentTabKey.default()
    if kind == "machine":
        installation_id = raw.get("installation_id")
        if isinstance(installation_id, str) and installation_id:
            return AgentTabKey.machine(installation_id)
        alias = raw.get("alias")
        if isinstance(alias, str) and alias:
            return AgentTabKey.unresolved_machine(alias)
        raise TypeError(f"sase_core_rs returned machine tab key without id: {raw!r}")
    if kind == "unresolved_machine":
        alias = raw.get("alias")
        if isinstance(alias, str) and alias:
            return AgentTabKey.unresolved_machine(alias)
        raise TypeError(
            f"sase_core_rs returned unresolved machine tab key without alias: {raw!r}"
        )
    if kind == "named":
        name = raw.get("name")
        if isinstance(name, str) and name:
            return AgentTabKey.named(name)
        raise TypeError(f"sase_core_rs returned named tab key without a name: {raw!r}")
    raise TypeError(f"sase_core_rs returned unknown tab key kind: {kind!r}")


def build_agent_tab_catalog(
    roots: Iterable[Mapping[str, Any]],
    *,
    machine_mode: bool,
    machine_order: Iterable[tuple[str, str]],
    named_order: Mapping[str, int],
    local_alias: str | None = None,
) -> _AgentTabCatalog:
    """Build the ordered tab catalog for one roster with a single binding call.

    *roots* are wire dicts shaped ``{"agent_tab": str|None, "owner": {...}}``;
    *machine_order* holds ``(pinned_installation_id, alias)`` pairs;
    *named_order* maps canonical tab names to sort positions; *local_alias*
    names this machine's tab in machine mode (blank values are omitted).
    """
    binding = require_rust_binding("build_agent_tab_catalog")
    root_list = list(roots)
    options: dict[str, Any] = {
        "machine_mode": bool(machine_mode),
        "machine_order": [
            {"installation_id": installation_id, "alias": alias}
            for installation_id, alias in machine_order
        ],
        "named_order": dict(named_order),
    }
    if isinstance(local_alias, str) and local_alias.strip():
        options["local_alias"] = local_alias.strip()
    result: Any = binding(root_list, options)
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned non-dict tab catalog")
    raw_keys = result.get("keys")
    raw_entries = result.get("entries")
    if not isinstance(raw_keys, list) or not isinstance(raw_entries, list):
        raise TypeError("sase_core_rs returned tab catalog without keys/entries")
    keys = tuple(_key_from_wire(raw) for raw in raw_keys)
    entries: list[AgentTabCatalogEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise TypeError(f"sase_core_rs returned non-dict tab entry: {raw!r}")
        entry_kind = raw.get("kind")
        label = raw.get("label")
        root_count = raw.get("root_count")
        entries.append(
            AgentTabCatalogEntry(
                key=_key_from_wire(raw.get("key")),
                kind=entry_kind if isinstance(entry_kind, str) else "",
                label=label if isinstance(label, str) else "",
                root_count=root_count if isinstance(root_count, int) else 0,
            )
        )
    return _AgentTabCatalog(keys=keys, entries=tuple(entries))


def canonicalize_agent_tab(raw: str) -> str | None:
    """Return the stored tab name for *raw*, or None for the default tab.

    Kind ``named`` returns the canonical (trimmed, lowercased) name. Kind
    ``default`` (explicit ``%tab:main``) is stored as absent, so it returns
    None. The Rust binding's ``ValueError`` (whose text is the user-facing
    message) propagates unchanged.
    """
    binding = require_rust_binding("canonicalize_agent_tab_name")
    result: Any = binding(raw)
    if not isinstance(result, dict):
        raise TypeError("sase_core_rs returned non-dict tab canonicalization")
    kind = result.get("kind")
    if kind == "default":
        return None
    if kind == "named":
        name = result.get("name")
        if isinstance(name, str) and name:
            return name
        raise TypeError("sase_core_rs returned named tab without a name")
    raise TypeError(f"sase_core_rs returned unknown tab kind: {kind!r}")


__all__ = [
    "DEFAULT_AGENT_TAB_KEY",
    "AgentTabCatalogEntry",
    "AgentTabKey",
    "AgentTabKind",
    "agent_tab_key_token",
    "build_agent_tab_catalog",
    "canonicalize_agent_tab",
    "parse_agent_tab_key_token",
]
