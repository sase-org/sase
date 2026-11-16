"""Short-lived memos shared by one Agents loader decode batch."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar, cast


_T = TypeVar("_T")
_UNSET = object()


class _AgentLoaderMemos:
    """Per-load caches for decode work repeated across agent rows."""

    def __init__(self) -> None:
        self._artifact_dirs: dict[int, tuple[object, str | None]] = {}
        self._retention: dict[str | None, object] = {}
        self._held_claim_ttl_days: object = _UNSET

    def artifacts_dir(
        self,
        agent: object,
        compute: Callable[[], str | None],
    ) -> str | None:
        key = id(agent)
        cached = self._artifact_dirs.get(key)
        if cached is not None and cached[0] is agent:
            return cached[1]
        value = compute()
        # Retain the object for this batch so its id cannot be reused.
        self._artifact_dirs[key] = (agent, value)
        return value

    def workspace_retention(
        self,
        artifacts_dir: str | None,
        compute: Callable[[Callable[[], int | None]], _T],
    ) -> _T:
        if artifacts_dir in self._retention:
            return cast(_T, self._retention[artifacts_dir])
        value = compute(self.held_claim_ttl_days)
        self._retention[artifacts_dir] = value
        return value

    def held_claim_ttl_days(self) -> int | None:
        if self._held_claim_ttl_days is _UNSET:
            from sase.workspace_provider.retention_record import (
                configured_held_claim_ttl_days,
            )

            self._held_claim_ttl_days = configured_held_claim_ttl_days()
        return cast(int | None, self._held_claim_ttl_days)


_CURRENT: ContextVar[_AgentLoaderMemos | None] = ContextVar(
    "sase_agent_loader_memos", default=None
)


def current_agent_loader_memos() -> _AgentLoaderMemos | None:
    """Return the active decode batch, if this call is inside one."""
    return _CURRENT.get()


@contextmanager
def agent_loader_memos() -> Iterator[_AgentLoaderMemos]:
    """Create one memo scope, reusing an outer loader scope when nested."""
    current = _CURRENT.get()
    if current is not None:
        yield current
        return
    memos = _AgentLoaderMemos()
    token = _CURRENT.set(memos)
    try:
        yield memos
    finally:
        _CURRENT.reset(token)


__all__ = ["agent_loader_memos", "current_agent_loader_memos"]
