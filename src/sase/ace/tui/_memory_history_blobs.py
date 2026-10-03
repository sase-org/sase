"""Blob-version queries for ACE memory history (agents-bridge).

One section of :class:`sase.ace.tui.memory_history.AceMemoryHistory`:
resolving the blob OID an agent read to its committed version, the
number of newer versions, and whether now still matches. Results
memoize by ``(scope_key, selector, oid, timeline fingerprint)`` through
the single-flight. Import from :mod:`sase.ace.tui.memory_history`, not
from here.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui._memory_history_timelines import TimelineQueries
from sase.ace.tui.util.trace import tui_trace


def _committed_ordinal(row: dict[str, Any]) -> int:
    """Return a timeline row's ordinal (``0`` for now/staged rows)."""
    return int(row.get("ordinal", 0) or 0)


class BlobQueries(TimelineQueries):
    """Blob-OID version lookups over the memoized timeline."""

    def version_for_blob(self, scope: Any, selector: str, oid: str) -> dict[str, Any]:
        """Resolve a read blob OID to its version moment.

        Returns ``ordinal`` (the newest committed version with that
        blob), ``version`` (its row), ``newest`` (the newest committed
        ordinal), ``newest_version``, ``newer_count``, and
        ``now_matches``. Deleted rows never match; a reverted blob
        resolves to its newest match. Raises ``ValueError`` for a
        malformed or ambiguous prefix and ``LookupError`` when no
        committed version carries the blob (an uncommitted read).
        """
        raw = str(oid or "")
        if len(raw) < 7 or any(ch not in "0123456789abcdefABCDEF" for ch in raw):
            raise ValueError(f"invalid version selector: blob:{oid}")
        scope_key = str(getattr(scope, "scope_key", "") or "")
        sel = str(selector)
        with tui_trace("memory.history.query", op="version_for_blob") as extra:
            wire = self.timeline(scope, sel, include_hidden=True)
            memo_key = (scope_key, sel, raw.lower(), self._fingerprint(wire))
            with self._lock:
                cached = self._blob_memo.get(memo_key)
                if cached is not None:
                    extra["hit"] = True
                    return cached
            extra["hit"] = False
            owner, flight = self._join_flight(("blob", *memo_key))
            if not owner:
                flight.event.wait()
                if flight.error is not None:
                    raise flight.error
                return flight.result
            try:
                result = self._resolve_blob_version(sel, raw, wire)
            except Exception as exc:
                flight.error = exc
                self._settle_flight(("blob", *memo_key), flight)
                raise
            with self._lock:
                self._blob_memo[memo_key] = result
            self._settle_flight(("blob", *memo_key), flight, result=result)
            return result

    def _resolve_blob_version(
        self, selector: str, raw: str, wire: dict[str, Any]
    ) -> dict[str, Any]:
        """Build the version-for-blob result from a timeline wire."""
        from sase.memory.history._cli_history_common import (
            blob_ordinal_from_timeline,
        )

        matched = blob_ordinal_from_timeline(wire, raw)
        if matched is None:
            raise LookupError(f"no version blob:{raw} for subject {selector!r}")
        if matched == -1:
            raise ValueError(
                f"ambiguous blob prefix blob:{raw} for subject {selector!r}"
            )
        ordinal = int(matched)
        committed = [
            row
            for row in wire.get("versions", ())
            if isinstance(row, dict) and _committed_ordinal(row) > 0
        ]
        newest = max((_committed_ordinal(row) for row in committed), default=ordinal)
        version_row = next(
            (dict(row) for row in committed if _committed_ordinal(row) == ordinal),
            {},
        )
        newest_row = next(
            (dict(row) for row in committed if _committed_ordinal(row) == newest),
            dict(version_row),
        )
        return {
            "ordinal": ordinal,
            "version": version_row,
            "newest": newest,
            "newest_version": newest_row,
            "newer_count": sum(
                1 for row in committed if _committed_ordinal(row) > ordinal
            ),
            "now_matches": _blob_now_matches(wire, committed, ordinal, newest),
        }


def _no_live_row(wire: dict[str, Any]) -> bool:
    """Return whether the timeline carries no now/staged (ordinal 0) row."""
    return not any(
        isinstance(row, dict) and _committed_ordinal(row) == 0
        for row in wire.get("versions", ())
    )


def _blob_now_matches(
    wire: dict[str, Any],
    committed: list[dict[str, Any]],
    ordinal: int,
    newest: int,
) -> bool:
    """Return whether a blob read at *ordinal* is still current."""
    if ordinal != newest:
        return False
    try:
        from sase.pager.history_kit import (
            build_moment,
            committed_pin_for_ordinal,
            visible_ordinals_for_timeline,
        )
    except Exception:
        return _no_live_row(wire)
    try:
        visible = visible_ordinals_for_timeline(wire)
        if not isinstance(visible, (list, tuple)):
            visible = tuple(_committed_ordinal(row) for row in committed)
        subject_id = next(
            (
                str(row.get("subject_id") or row.get("subject"))
                for row in committed
                if row.get("subject_id") or row.get("subject")
            ),
            "",
        )
        moment = build_moment(
            rows=wire.get("versions", ()),
            meta={
                key: wire.get(key)
                for key in ("worktree_oid", "head_oid", "index_oid", "state")
            },
            visible_ordinals=visible,
            pin=committed_pin_for_ordinal(subject_id, ordinal),
            status=str(wire.get("status", "live")),
        )
        return str(getattr(moment, "kind", "")) == "now"
    except Exception:
        return _no_live_row(wire)
