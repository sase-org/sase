"""Off-thread Record deck loading (epic sase-1jm.4.2, ``shell``).

The worker refreshes Relations extras, reuses the cached document when
those extras are unchanged, and otherwise loads Facts and builds the
four-card document. The LRU cache is keyed by subject identity and the
captured subject signature. There is no I/O in compose,
render, keystroke, or pump paths: every read happens here, inside the
worker.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .document import build_record_document, record_default_card
from .facts import FactsExtras, load_facts_extras
from .model import RecordSubject
from .relations import RelationsExtras, load_relations_extras

#: Bound for the per-subject document cache (subject, signature pairs).
RECORD_CACHE_SIZE = 32


@dataclass(frozen=True)
class RecordDeckLoadResult:
    """One loaded Record deck: document plus chrome facts."""

    subject_identity: object | None
    generation: int
    signature: str
    document: Any
    default_card: str | None
    relations_signature: str | None = None


_RECORD_CACHE: OrderedDict[tuple[Any, str], RecordDeckLoadResult] = OrderedDict()


def record_cache_key(subject: RecordSubject) -> str:
    """Return the cache signature for ``subject`` (no I/O)."""
    try:
        return repr(subject)
    except Exception:
        return ""


def cached_record_result(
    subject_identity: object | None, signature: str
) -> RecordDeckLoadResult | None:
    """Return the cached result for ``(subject, signature)``, if any."""
    try:
        result = _RECORD_CACHE.get((subject_identity, signature))
    except TypeError:
        return None
    if result is None:
        return None
    try:
        _RECORD_CACHE.move_to_end((subject_identity, signature))
    except (KeyError, TypeError):
        pass
    return result


def store_record_result(result: RecordDeckLoadResult) -> None:
    """Store ``result`` in the cache, evicting the oldest."""
    try:
        _RECORD_CACHE[(result.subject_identity, result.signature)] = result
        _RECORD_CACHE.move_to_end((result.subject_identity, result.signature))
    except TypeError:
        return
    while len(_RECORD_CACHE) > RECORD_CACHE_SIZE:
        try:
            _RECORD_CACHE.popitem(last=False)
        except KeyError:
            break


def clear_record_cache() -> None:
    """Drop every cached Record result (tests only)."""
    _RECORD_CACHE.clear()


def load_record_deck(
    subject: RecordSubject,
    *,
    generation: int,
) -> RecordDeckLoadResult:
    """Load both extras and build one Record deck (worker body).

    Relations extras are refreshed on each worker request so the shared
    artifact-link snapshot key can invalidate the document cache. An
    unchanged result still refreshes ``generation`` for stale-paint checks.
    """
    signature = record_cache_key(subject)
    relations: RelationsExtras | None = None
    try:
        relations = load_relations_extras(subject)
    except Exception:
        relations = None
    relations_signature = repr(relations) if relations is not None else None
    cached = cached_record_result(subject.identity, signature)
    if cached is not None and cached.relations_signature == relations_signature:
        return RecordDeckLoadResult(
            subject_identity=cached.subject_identity,
            generation=generation,
            signature=cached.signature,
            document=cached.document,
            default_card=cached.default_card,
            relations_signature=cached.relations_signature,
        )

    facts: FactsExtras | None = None
    try:
        facts = load_facts_extras(subject)
    except Exception:
        facts = None
    document = build_record_document(subject, facts, relations)
    try:
        default_card = record_default_card(document.card_ids, None)
    except Exception:
        default_card = None
    result = RecordDeckLoadResult(
        subject_identity=subject.identity,
        generation=generation,
        signature=signature,
        document=document,
        default_card=default_card,
        relations_signature=relations_signature,
    )
    store_record_result(result)
    return result


__all__ = [
    "RECORD_CACHE_SIZE",
    "RecordDeckLoadResult",
    "cached_record_result",
    "clear_record_cache",
    "load_record_deck",
    "record_cache_key",
    "store_record_result",
]
