"""Invariants of the fast-policy stylesheet snapshot behind ``AcePage``."""

from __future__ import annotations

from textual.css.stylesheet import Stylesheet

from sase.ace.testing._stylesheet_cache import _hydrate, _snapshot


_CSS = "Screen { color: red; } #x, .y { color: blue; }"


def _parsed() -> Stylesheet:
    stylesheet = Stylesheet(variables={"accent": "red"})
    stylesheet.add_source(_CSS, read_from=("inline", "snapshot-test"))
    stylesheet.parse()
    return stylesheet


def test_snapshot_is_immutable_bytes_detached_from_the_live_stylesheet() -> None:
    live = _parsed()
    snapshot = _snapshot(live)

    assert isinstance(snapshot.state, bytes)
    live._variables["accent"] = "green"
    live.rules.clear()

    hydrated = _hydrate(snapshot)
    assert hydrated._variables == {"accent": "red"}
    assert [rule.css for rule in hydrated.rules] == [
        rule.css for rule in _parsed().rules
    ]


def test_each_hydrate_is_private_and_keeps_rule_identity_with_its_index() -> None:
    snapshot = _snapshot(_parsed())
    first = _hydrate(snapshot)
    second = _hydrate(snapshot)

    for hydrated in (first, second):
        rule_ids = {id(rule) for rule in hydrated.rules}
        assert set(hydrated.rules_map) == {"Screen", "#x", ".y"}
        for entries in hydrated.rules_map.values():
            # ``Stylesheet.apply`` filters ``rules`` by membership in the map.
            assert {id(rule) for rule in entries} <= rule_ids
        assert hydrated._require_parse is False
    assert {id(rule) for rule in first.rules}.isdisjoint(
        id(rule) for rule in second.rules
    )
    assert first.source is not second.source
    assert first._variables is not second._variables
    first._variables["accent"] = "green"
    assert second._variables == {"accent": "red"}
