"""Subjects and feed queries for ACE memory history.

One section of :class:`sase.ace.tui.memory_history.AceMemoryHistory`:
the change-token memos for one scope's subjects and the merged
changesets feed. Import from :mod:`sase.ace.tui.memory_history`, not
from here.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui._memory_history_tokens import TokenQueries
from sase.ace.tui.util.trace import tui_trace


class CollectionQueries(TokenQueries):
    """Change-token-memoized subjects and feed queries."""

    def subjects(self, scope: Any) -> dict[str, Any]:
        """Return one scope's subjects, memoized by its change token."""
        scope_key = str(getattr(scope, "scope_key", "") or "")
        with tui_trace("memory.history.query", op="subjects") as extra:
            token = self.change_token(scope)
            with self._lock:
                memo = self._subjects_memo.get(scope_key)
                if memo is not None and memo[0] == token:
                    extra["hit"] = True
                    return memo[1]
            extra["hit"] = False
            owner, flight = self._join_flight(("subjects", scope_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                result = dict(self._service.subjects(scope))
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("subjects", scope_key), flight)
                raise
            with self._lock:
                self._subjects_memo[scope_key] = (self.change_token(scope), result)
            self._settle_flight(("subjects", scope_key), flight, result=result)
            return result

    def feed(self, scopes: list[Any]) -> dict[str, Any]:
        """Return the merged changesets feed, memoized by change tokens."""
        keys = tuple(str(getattr(scope, "scope_key", "") or "") for scope in scopes)
        with tui_trace("memory.history.query", op="feed") as extra:
            tokens = tuple(self.change_token(scope) for scope in scopes)
            with self._lock:
                memo = self._feed_memo.get(keys)
                if memo is not None and memo[0] == tokens:
                    extra["hit"] = True
                    return memo[1]
            extra["hit"] = False
            owner, flight = self._join_flight(("feed", *keys))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                result = dict(
                    self._service.feed(
                        scopes, since=None, limit=None, include_hidden=True
                    )
                )
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("feed", *keys), flight)
                raise
            with self._lock:
                self._feed_memo[keys] = (
                    tuple(self.change_token(scope) for scope in scopes),
                    result,
                )
            self._settle_flight(("feed", *keys), flight, result=result)
            return result
