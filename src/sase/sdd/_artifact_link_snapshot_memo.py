"""Opt-in, operation-scoped memo for artifact-link snapshot inputs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class _ArtifactLinkSnapshotMemo:
    durable_inputs: dict[tuple[str, str, str, int, int, int], object] = field(
        default_factory=dict
    )
    pending_outboxes: dict[
        tuple[str, str, int, int, int],
        tuple[tuple[Any, ...], tuple[float, ...]],
    ] = field(default_factory=dict)


_ACTIVE_MEMO: ContextVar[_ArtifactLinkSnapshotMemo | None] = ContextVar(
    "artifact_link_snapshot_memo", default=None
)


@contextmanager
def artifact_link_snapshot_memo() -> Iterator[None]:
    """Share snapshot inputs for one operation, reusing any outer scope."""

    if _ACTIVE_MEMO.get() is not None:
        yield
        return
    token: Token[_ArtifactLinkSnapshotMemo | None] = _ACTIVE_MEMO.set(
        _ArtifactLinkSnapshotMemo()
    )
    try:
        yield
    finally:
        _ACTIVE_MEMO.reset(token)


def lookup_durable_input(
    key: tuple[str, str, str, int, int, int],
) -> tuple[bool, object | None]:
    """Return a scoped durable-file result, if one has already been read."""

    memo = _ACTIVE_MEMO.get()
    if memo is None or key not in memo.durable_inputs:
        return False, None
    return True, memo.durable_inputs[key]


def remember_durable_input(
    key: tuple[str, str, str, int, int, int],
    value: object,
) -> None:
    """Remember one validated durable event or validation finding."""

    memo = _ACTIVE_MEMO.get()
    if memo is not None:
        memo.durable_inputs[key] = value


def lookup_pending_outbox(
    key: tuple[str, str, int, int, int],
) -> tuple[tuple[Any, ...], tuple[float, ...]] | None:
    """Return the full parsed pending queue for a scoped outbox version."""

    memo = _ACTIVE_MEMO.get()
    if memo is None:
        return None
    return memo.pending_outboxes.get(key)


def remember_pending_outbox(
    key: tuple[str, str, int, int, int],
    candidates: tuple[Any, ...],
    created_at: tuple[float, ...],
) -> None:
    """Remember unfiltered pending candidates and their queue timestamps."""

    memo = _ACTIVE_MEMO.get()
    if memo is not None:
        memo.pending_outboxes[key] = (candidates, created_at)
