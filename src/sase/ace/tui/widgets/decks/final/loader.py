"""Off-thread FINAL deck loading over the run-view projection.

The worker collects capped artifact inputs for the node's run targets,
projects them through the Rust ``finalizer::run_view`` binding, and builds
the card document. A stat-only ``(mtime_ns, size)`` signature cache skips
re-projection when nothing changed. There is no artifact I/O in
``compose``, ``render``, keystroke or pump paths: every read happens here,
inside the worker.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from sase.core.finalizer_run_view import FinalizerNodeView
from sase.finalizers.run_view_inputs import (
    RunTarget,
    build_node_request,
    run_inputs_signature,
)

from .document import build_final_deck_document

#: Bound for the per-subject signature cache (subject, signature pairs).
FINAL_CACHE_SIZE = 32


@dataclass(frozen=True)
class FinalDeckLoadResult:
    """One projected FINAL deck: document plus chrome facts."""

    subject_identity: object | None
    generation: int
    signature: str
    document: Any
    default_card: str | None
    status: str
    glyph: str
    attention_instance_id: str | None
    run_level_trouble: bool


_FINAL_CACHE: OrderedDict[tuple[Any, str], FinalDeckLoadResult] = OrderedDict()


def final_cache_key(targets: tuple[RunTarget, ...] | list[RunTarget]) -> str:
    """Return the stat-only signature over every target's inputs."""
    return run_inputs_signature(targets)


def cached_final_result(
    subject_identity: object | None, signature: str
) -> FinalDeckLoadResult | None:
    """Return the cached result for ``(subject, signature)``, if any."""
    try:
        result = _FINAL_CACHE.get((subject_identity, signature))
    except TypeError:
        return None
    if result is None:
        return None
    try:
        _FINAL_CACHE.move_to_end((subject_identity, signature))
    except (KeyError, TypeError):
        pass
    return result


def store_final_result(result: FinalDeckLoadResult) -> None:
    """Store ``result`` in the signature cache, evicting the oldest."""
    try:
        _FINAL_CACHE[(result.subject_identity, result.signature)] = result
        _FINAL_CACHE.move_to_end((result.subject_identity, result.signature))
    except TypeError:
        return
    while len(_FINAL_CACHE) > FINAL_CACHE_SIZE:
        try:
            _FINAL_CACHE.popitem(last=False)
        except KeyError:
            break


def clear_final_cache() -> None:
    """Drop every cached FINAL result (tests only)."""
    _FINAL_CACHE.clear()


def project_node_view(targets: tuple[RunTarget, ...] | list[RunTarget]) -> Any | None:
    """Project the node view for ``targets``; None when unavailable.

    A missing or outdated Rust binding degrades to ``None`` (the view
    paints a calm unavailable line) instead of raising.
    """
    try:
        from sase.core.finalizer_run_view import project_finalizer_node_view

        request = build_node_request(targets)
        return project_finalizer_node_view(request)
    except Exception:
        return None


def load_final_deck(
    targets: tuple[RunTarget, ...] | list[RunTarget],
    *,
    subject: object | None,
    subject_identity: object | None,
    generation: int,
    live_tail_delay: float | None = None,
    live_now: float | None = None,
    fresh: bool = False,
) -> FinalDeckLoadResult:
    """Collect, project and build one FINAL deck (worker body).

    A cache hit skips collection and projection but still refreshes the
    ``generation`` so the caller can reject stale paints. When
    ``live_tail_delay`` is given, the followed newest run's active op
    renders its gated in-card live tail (plan §3.7). The 1 Hz live tick
    passes ``fresh=True`` to bypass the lookup: the cached document
    freezes its elapsed header at collection time, so the tick always
    rebuilds (the result is still stored for the drift path).
    """
    from .document import final_default_card

    signature = final_cache_key(targets)
    cached = None if fresh else cached_final_result(subject_identity, signature)
    if cached is not None:
        return FinalDeckLoadResult(
            subject_identity=cached.subject_identity,
            generation=generation,
            signature=cached.signature,
            document=cached.document,
            default_card=cached.default_card,
            status=cached.status,
            glyph=cached.glyph,
            attention_instance_id=cached.attention_instance_id,
            run_level_trouble=cached.run_level_trouble,
        )
    node_view = project_node_view(targets)
    document = build_final_deck_document(
        node_view,
        subject=subject,
        digest=signature,
        live_tail_delay=live_tail_delay,
        live_now=live_now,
    )
    attention: str | None = None
    trouble = False
    status = ""
    glyph = ""
    if isinstance(node_view, FinalizerNodeView):
        attention = node_view.attention_instance_id
        trouble = bool(node_view.run_level_trouble)
        status = node_view.status or ""
        glyph = node_view.glyph or ""
    default_card = final_default_card(
        document.card_ids,
        None,
        attention_instance_id=attention,
        run_level_trouble=trouble,
    )
    result = FinalDeckLoadResult(
        subject_identity=subject_identity,
        generation=generation,
        signature=signature,
        document=document,
        default_card=default_card,
        status=status,
        glyph=glyph,
        attention_instance_id=attention,
        run_level_trouble=trouble,
    )
    store_final_result(result)
    return result


__all__ = [
    "FINAL_CACHE_SIZE",
    "FinalDeckLoadResult",
    "cached_final_result",
    "clear_final_cache",
    "final_cache_key",
    "load_final_deck",
    "project_node_view",
    "store_final_result",
]
