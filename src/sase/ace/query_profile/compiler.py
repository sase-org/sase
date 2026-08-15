"""Compile an :class:`ArtifactQuerySchema` into a deterministic, digested profile.

The compiled :class:`CompiledQueryProfile` is what later phases pass as an
argument into Rust parse/compile/evaluate calls and into the Python
reference evaluator, instead of each of those consumers special-casing a
pane. Compilation validates the schema against the closed host vocabularies
in :mod:`sase.ace.query_profile.registry`, canonicalizes field/sigil/
predicate/macro order so authoring order never affects the result, and
computes a stable digest so callers can detect a changed dialect (for
example to invalidate a cached saved query).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .registry import (
    HOST_FIELD_VALUE_KINDS,
    HOST_MACRO_TRIGGERS,
    HOST_PREDICATES,
    HOST_SIGIL_CHARS,
)
from .types import ArtifactQuerySchema, QueryFieldSpec, QueryMacroSpec, QuerySigilSpec


class QueryProfileError(ValueError):
    """Raised when an :class:`ArtifactQuerySchema` fails host validation."""


@dataclass(frozen=True, slots=True)
class CompiledQueryProfile:
    """Deterministic, digest-stable profile compiled from a pane's schema."""

    pane_id: str
    boolean: bool
    fields: tuple[QueryFieldSpec, ...]
    sigils: tuple[QuerySigilSpec, ...]
    predicates: tuple[str, ...]
    any_special: bool
    macros: tuple[QueryMacroSpec, ...]
    free_text_hint: str
    digest: str

    def field(self, key: str) -> QueryFieldSpec | None:
        """Return the declared field named *key*, if any."""
        return next((item for item in self.fields if item.key == key), None)

    def filterable_fields(self) -> tuple[str, ...]:
        """Return field keys addressable via ``key:value`` syntax, in order."""
        return tuple(item.key for item in self.fields if item.filterable)

    def searchable_fields(self) -> tuple[str, ...]:
        """Return field keys that contribute to free-text search, in order."""
        return tuple(item.key for item in self.fields if item.searchable)

    def repeatable_fields(self) -> tuple[str, ...]:
        """Return field keys the flat (non-boolean) grammar may comma-repeat."""
        return tuple(item.key for item in self.fields if item.repeatable)

    def negatable_fields(self) -> tuple[str, ...]:
        """Return field keys the flat (non-boolean) grammar may negate."""
        return tuple(item.key for item in self.fields if item.negatable)

    def to_wire(self) -> dict[str, Any]:
        """Return the deterministic, JSON-safe payload passed into Rust."""
        payload = _canonical_payload(
            pane_id=self.pane_id,
            boolean=self.boolean,
            fields=self.fields,
            sigils=self.sigils,
            predicates=self.predicates,
            any_special=self.any_special,
            macros=self.macros,
            free_text_hint=self.free_text_hint,
        )
        payload["digest"] = self.digest
        return payload


def compile_query_profile(schema: ArtifactQuerySchema) -> CompiledQueryProfile:
    """Validate *schema* against the closed host vocabularies and compile it.

    Compilation is pure and order-independent: fields, sigils, predicates,
    and macros are sorted into a canonical order so that two schemas
    describing the same dialect always compile to byte-identical wire
    payloads and digests, regardless of the order they were authored in.
    """
    _validate(schema)
    fields = tuple(sorted(schema.fields, key=lambda item: item.key))
    sigils = tuple(sorted(schema.sigils, key=lambda item: item.sigil))
    predicates = tuple(sorted(schema.predicates))
    macros = tuple(sorted(schema.macros, key=lambda item: (item.trigger, item.letter)))
    payload = _canonical_payload(
        pane_id=schema.pane_id,
        boolean=schema.boolean,
        fields=fields,
        sigils=sigils,
        predicates=predicates,
        any_special=schema.any_special,
        macros=macros,
        free_text_hint=schema.free_text_hint,
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return CompiledQueryProfile(
        pane_id=schema.pane_id,
        boolean=schema.boolean,
        fields=fields,
        sigils=sigils,
        predicates=predicates,
        any_special=schema.any_special,
        macros=macros,
        free_text_hint=schema.free_text_hint,
        digest=digest,
    )


def _canonical_payload(
    *,
    pane_id: str,
    boolean: bool,
    fields: tuple[QueryFieldSpec, ...],
    sigils: tuple[QuerySigilSpec, ...],
    predicates: tuple[str, ...],
    any_special: bool,
    macros: tuple[QueryMacroSpec, ...],
    free_text_hint: str,
) -> dict[str, Any]:
    return {
        "pane_id": pane_id,
        "boolean": boolean,
        "fields": [_field_payload(item) for item in fields],
        "sigils": [{"sigil": item.sigil, "field": item.field} for item in sigils],
        "predicates": list(predicates),
        "any_special": any_special,
        "macros": [
            {
                "trigger": item.trigger,
                "letter": item.letter,
                "field": item.field,
                "value": item.value,
            }
            for item in macros
        ],
        "free_text_hint": free_text_hint,
    }


def _field_payload(item: QueryFieldSpec) -> dict[str, Any]:
    return {
        "key": item.key,
        "value_kind": item.value_kind,
        "filterable": item.filterable,
        "searchable": item.searchable,
        "repeatable": item.repeatable,
        "negatable": item.negatable,
        "exact_match": item.exact_match,
        "static_values": list(item.static_values),
        "hint": item.hint,
    }


def _validate(schema: ArtifactQuerySchema) -> None:
    if not schema.pane_id:
        raise QueryProfileError("pane_id must not be empty")

    field_keys: set[str] = set()
    for item in schema.fields:
        if not item.key:
            raise QueryProfileError("field key must not be empty")
        if item.key in field_keys:
            raise QueryProfileError(f"duplicate field key: {item.key!r}")
        field_keys.add(item.key)
        if item.value_kind not in HOST_FIELD_VALUE_KINDS:
            raise QueryProfileError(
                f"{item.key}: unknown value_kind {item.value_kind!r} "
                f"(valid kinds: {', '.join(sorted(HOST_FIELD_VALUE_KINDS))})"
            )
        if item.value_kind == "enum" and not item.static_values:
            raise QueryProfileError(
                f"{item.key}: enum fields must declare static_values"
            )
        if not item.filterable and (item.repeatable or item.negatable):
            raise QueryProfileError(
                f"{item.key}: repeatable/negatable only apply to filterable fields"
            )

    sigil_chars: set[str] = set()
    for sigil in schema.sigils:
        if sigil.sigil not in HOST_SIGIL_CHARS:
            raise QueryProfileError(
                f"sigil {sigil.sigil!r} is not a host-recognized sigil "
                f"(valid sigils: {', '.join(sorted(HOST_SIGIL_CHARS))})"
            )
        if sigil.sigil in sigil_chars:
            raise QueryProfileError(f"duplicate sigil: {sigil.sigil!r}")
        sigil_chars.add(sigil.sigil)
        if sigil.field not in field_keys:
            raise QueryProfileError(
                f"sigil {sigil.sigil!r} targets undeclared field {sigil.field!r}"
            )

    predicate_names: set[str] = set()
    for name in schema.predicates:
        if name not in HOST_PREDICATES:
            raise QueryProfileError(
                f"unknown predicate {name!r} "
                f"(valid predicates: {', '.join(sorted(HOST_PREDICATES))})"
            )
        if name in predicate_names:
            raise QueryProfileError(f"duplicate predicate: {name!r}")
        predicate_names.add(name)

    if schema.any_special and predicate_names != set(HOST_PREDICATES):
        raise QueryProfileError(
            "any_special requires every host predicate to be declared: "
            f"{', '.join(sorted(HOST_PREDICATES))}"
        )

    macro_keys: set[tuple[str, str]] = set()
    for macro in schema.macros:
        if macro.trigger not in HOST_MACRO_TRIGGERS:
            raise QueryProfileError(
                f"macro trigger {macro.trigger!r} is not host-recognized "
                f"(valid triggers: {', '.join(sorted(HOST_MACRO_TRIGGERS))})"
            )
        macro_key = (macro.trigger, macro.letter)
        if macro_key in macro_keys:
            raise QueryProfileError(f"duplicate macro: {macro.trigger}{macro.letter}")
        macro_keys.add(macro_key)
        if macro.field not in field_keys:
            raise QueryProfileError(
                f"macro {macro.trigger}{macro.letter} targets undeclared "
                f"field {macro.field!r}"
            )


__all__ = ["CompiledQueryProfile", "QueryProfileError", "compile_query_profile"]
