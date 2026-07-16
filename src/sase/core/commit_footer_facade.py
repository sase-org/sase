"""Typed Python facade for the Rust commit-footer contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.rust import require_rust_binding

COMMIT_FOOTER_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LinkedCommitTagValue:
    """A readable tag label with its Markdown reference destination."""

    label: str
    destination: str
    reference_id: str | None = None


type CommitTagValue = str | LinkedCommitTagValue


@dataclass(frozen=True)
class _CommitFooterReference:
    id: str
    destination: str


@dataclass(frozen=True)
class _CommitFooterTag:
    raw_key: str
    key: str
    raw_value: str
    value: CommitTagValue

    @property
    def label(self) -> str:
        if isinstance(self.value, LinkedCommitTagValue):
            return self.value.label
        return self.value


@dataclass(frozen=True)
class _CommitFooter:
    body: str
    footer: str
    tags: tuple[_CommitFooterTag, ...]
    references: tuple[_CommitFooterReference, ...]


def parse_commit_footer(message: str) -> _CommitFooter:
    """Parse *message* through the shared Rust footer grammar."""
    binding = require_rust_binding("parse_commit_footer")
    raw = binding(message)
    if not isinstance(raw, dict):
        raise TypeError("parse_commit_footer returned a non-dict payload")
    schema_version = int(raw.get("schema_version", -1))
    if schema_version != COMMIT_FOOTER_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "unsupported commit-footer wire schema version "
            f"{schema_version}; expected {COMMIT_FOOTER_WIRE_SCHEMA_VERSION}"
        )

    tags = tuple(_tag_from_wire(tag) for tag in _dict_rows(raw.get("tags")))
    references = tuple(
        _CommitFooterReference(
            id=str(reference["id"]),
            destination=str(reference["destination"]),
        )
        for reference in _dict_rows(raw.get("references"))
    )
    return _CommitFooter(
        body=str(raw.get("body") or ""),
        footer=str(raw.get("footer") or ""),
        tags=tags,
        references=references,
    )


def update_commit_footer(
    message: str,
    updates: Mapping[str, object],
    *,
    remove_keys: frozenset[str] | set[str] = frozenset(),
) -> str:
    """Apply plain or linked tag updates through the Rust footer updater."""
    wire_updates: list[dict[str, str | None]] = []
    for key, raw_value in updates.items():
        update = _update_to_wire(str(key), raw_value)
        if update is not None:
            wire_updates.append(update)
    binding = require_rust_binding("update_commit_footer")
    return str(binding(message, wire_updates, list(remove_keys)))


def append_body_suffix_before_footer(message: str, suffix: str) -> str:
    """Append body prose while keeping a structured footer terminal."""
    parsed = parse_commit_footer(message)
    body = parsed.body if parsed.tags else message.rstrip()
    combined = f"{body}\n\n{suffix}" if body else suffix
    if not parsed.tags:
        return combined
    return f"{combined}\n\n{parsed.footer}"


def _tag_from_wire(raw: dict[str, Any]) -> _CommitFooterTag:
    destination = raw.get("destination")
    label = str(raw.get("label") or "")
    if destination is None:
        value: CommitTagValue = label
    else:
        reference_id = raw.get("reference_id")
        value = LinkedCommitTagValue(
            label=label,
            destination=str(destination),
            reference_id=str(reference_id) if reference_id is not None else None,
        )
    return _CommitFooterTag(
        raw_key=str(raw.get("raw_key") or ""),
        key=str(raw.get("key") or ""),
        raw_value=str(raw.get("raw_value") or ""),
        value=value,
    )


def _update_to_wire(
    key: str,
    raw_value: object,
) -> dict[str, str | None] | None:
    if isinstance(raw_value, LinkedCommitTagValue):
        label = _sanitize(raw_value.label)
        destination = _sanitize(raw_value.destination)
        reference_id = _sanitize(raw_value.reference_id)
    else:
        label = _sanitize(raw_value)
        destination = None
        reference_id = None
    if label is None:
        return None
    return {
        "key": key,
        "label": label,
        "destination": destination,
        "reference_id": reference_id,
    }


def _sanitize(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def _dict_rows(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError("commit-footer wire rows must be a list")
    if not all(isinstance(row, dict) for row in value):
        raise TypeError("commit-footer wire rows must contain only dicts")
    return tuple(value)


__all__ = [
    "COMMIT_FOOTER_WIRE_SCHEMA_VERSION",
    "CommitTagValue",
    "LinkedCommitTagValue",
    "append_body_suffix_before_footer",
    "parse_commit_footer",
    "update_commit_footer",
]
