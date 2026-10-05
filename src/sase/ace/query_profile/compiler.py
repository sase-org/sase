"""Compile an :class:`ArtifactQuerySchema` into a deterministic, digested profile.

The compiled :class:`CompiledQueryProfile` is what later phases pass as an
argument into Rust parse/compile/evaluate calls and into the Python
reference evaluator, instead of each of those consumers special-casing a
pane. Compilation validates the schema against the closed host vocabularies
in :mod:`sase.ace.query_profile.registry`, canonicalizes field/sigil/
predicate/shorthand order so authoring order never affects the result, and
computes a stable digest so callers can detect a changed dialect (for
example to invalidate a cached saved query).

The digest hashes the same canonical payload, with the shorthand list under
the ``shorthands`` key, that pinned core rebuilds and hashes when it loads a
wire profile. Core rejects a profile whose digest does not match those
bytes, so the two canonical payloads must stay byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .registry import (
    HOST_FIELD_VALUE_KINDS,
    HOST_PREDICATES,
    HOST_SHORTHAND_TRIGGERS,
    HOST_SIGIL_CHARS,
)
from .types import (
    ArtifactQuerySchema,
    QueryFieldSpec,
    QueryShorthandSpec,
    QuerySigilSpec,
)


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
    shorthands: tuple[QueryShorthandSpec, ...]
    free_text_hint: str
    digest: str
    identity_field: str | None = None

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
            shorthands=self.shorthands,
            free_text_hint=self.free_text_hint,
        )
        payload["digest"] = self.digest
        return payload


def compile_query_profile(schema: ArtifactQuerySchema) -> CompiledQueryProfile:
    """Validate *schema* against the closed host vocabularies and compile it.

    Compilation is pure and order-independent: fields, sigils, predicates,
    and shorthands are sorted into a canonical order so that two schemas
    describing the same dialect always compile to byte-identical wire
    payloads and digests, regardless of the order they were authored in.
    """
    _validate(schema)
    fields = tuple(sorted(schema.fields, key=lambda item: item.key))
    sigils = tuple(sorted(schema.sigils, key=lambda item: item.sigil))
    predicates = tuple(sorted(schema.predicates))
    shorthands = tuple(
        sorted(schema.shorthands, key=lambda item: (item.trigger, item.letter))
    )
    payload = _canonical_payload(
        pane_id=schema.pane_id,
        boolean=schema.boolean,
        fields=fields,
        sigils=sigils,
        predicates=predicates,
        any_special=schema.any_special,
        shorthands=shorthands,
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
        shorthands=shorthands,
        free_text_hint=schema.free_text_hint,
        digest=digest,
        identity_field=schema.identity_field,
    )


def _canonical_payload(
    *,
    pane_id: str,
    boolean: bool,
    fields: tuple[QueryFieldSpec, ...],
    sigils: tuple[QuerySigilSpec, ...],
    predicates: tuple[str, ...],
    any_special: bool,
    shorthands: tuple[QueryShorthandSpec, ...],
    free_text_hint: str,
) -> dict[str, Any]:
    # Mirrors ``canonical_payload`` in sase-core's ``query/profile.rs`` key for
    # key: a renamed or added key changes the digest core recomputes.
    return {
        "pane_id": pane_id,
        "boolean": boolean,
        "fields": [_field_payload(item) for item in fields],
        "sigils": [{"sigil": item.sigil, "field": item.field} for item in sigils],
        "predicates": list(predicates),
        "any_special": any_special,
        "shorthands": [
            {
                "trigger": item.trigger,
                "letter": item.letter,
                "field": item.field,
                "value": item.value,
            }
            for item in shorthands
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

    shorthand_keys: set[tuple[str, str]] = set()
    for shorthand in schema.shorthands:
        if shorthand.trigger not in HOST_SHORTHAND_TRIGGERS:
            raise QueryProfileError(
                f"shorthand trigger {shorthand.trigger!r} is not host-recognized "
                f"(valid triggers: {', '.join(sorted(HOST_SHORTHAND_TRIGGERS))})"
            )
        shorthand_key = (shorthand.trigger, shorthand.letter)
        if shorthand_key in shorthand_keys:
            raise QueryProfileError(
                f"duplicate shorthand: {shorthand.trigger}{shorthand.letter}"
            )
        shorthand_keys.add(shorthand_key)
        if shorthand.field not in field_keys:
            raise QueryProfileError(
                f"shorthand {shorthand.trigger}{shorthand.letter} targets "
                f"undeclared field {shorthand.field!r}"
            )

    if schema.identity_field is None:
        return
    if schema.identity_field not in field_keys:
        raise QueryProfileError(
            f"identity_field {schema.identity_field!r} is not a declared field"
        )
    spec = next(item for item in schema.fields if item.key == schema.identity_field)
    if not spec.filterable:
        raise QueryProfileError(
            f"identity_field {schema.identity_field!r} must be filterable"
        )


__all__ = ["CompiledQueryProfile", "QueryProfileError", "compile_query_profile"]
