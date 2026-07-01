"""Source-preserving YAML writer for config edits."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from sase.config._edit_types import ConfigEditError
from sase.config._edit_yaml_io import dump_yaml, make_yaml
from sase.config._edit_yaml_surgical import (
    try_set_key_surgical,
    try_unset_key_surgical,
)


def _set_key_round_trip(text: str, key_path: tuple[str, ...], value: Any) -> str:
    from ruamel.yaml.comments import CommentedMap

    handler = make_yaml()
    data = handler.load(text) if text.strip() else None
    if not isinstance(data, MutableMapping):
        data = CommentedMap()
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            child = CommentedMap()
            node[segment] = child
        node = child
    node[key_path[-1]] = value
    return dump_yaml(handler, data)


def _unset_key_round_trip(text: str, key_path: tuple[str, ...]) -> str:
    handler = make_yaml()
    data = handler.load(text)
    if not isinstance(data, MutableMapping):
        return text
    node: MutableMapping[Any, Any] = data
    for segment in key_path[:-1]:
        child = node.get(segment)
        if not isinstance(child, MutableMapping):
            return text
        node = child
    last = key_path[-1]
    if last not in node:
        return text
    del node[last]
    return dump_yaml(handler, data)


def set_key(text: str, key_path: tuple[str, ...], value: Any) -> str:
    """Return *text* with *value* set at *key_path*, preserving formatting.

    Intermediate mappings are created as needed. Common block-style scalar
    edits are applied as surgical text splices so unrelated bytes stay
    unchanged; ambiguous shapes fall back to the round-trip loader.
    """
    if not key_path:
        raise ConfigEditError("cannot set an empty key path")
    result = try_set_key_surgical(text, key_path, value)
    return result if result is not None else _set_key_round_trip(text, key_path, value)


def unset_key(text: str, key_path: tuple[str, ...]) -> str:
    """Return *text* with the key at *key_path* removed, preserving formatting."""
    if not key_path or not text.strip():
        return text
    result = try_unset_key_surgical(text, key_path)
    return result if result is not None else _unset_key_round_trip(text, key_path)
