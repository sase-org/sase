"""Pure Procs query facade: row adapter, output gating, and cached filtering.

Holds the ``ObservedProc`` -> query-row adapter and the small stateful
:class:`ProcQueryFilter` the Procs pane (and any future CLI) calls to parse
and evaluate a proc query, without either caller touching the shared
profile-driven query stack directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import shlex
from typing import Any

from sase.ace.query.profile_evaluator import (
    ArtifactQueryRow,
    evaluate_query_for_profile,
)
from sase.ace.query.profile_reference import (
    ProfileQueryError,
    coerce_artifact_query_row,
    parse_query_for_profile,
)
from sase.ace.query.types import (
    AndExpr,
    NotExpr,
    OrExpr,
    PropertyMatch,
    QueryExpr,
    StringMatch,
)
from sase.ace.query_profile import CompiledQueryProfile, compile_query_profile
from sase.ace.query_profile.profiles import procs_query_schema
from sase.project_display_names import project_display_name_for

from ._proc_observer_models import (
    ObservedProc,
    is_monitor_shell_row,
    monitor_row_agent_name,
    proc_status_is_active,
)

#: Per-row output cap, matching the tail the pane itself renders.
PROC_QUERY_OUTPUT_TAIL_CHARS = 32_768

_FAILED_STATUSES = frozenset({"error", "killed"})
_OUTPUT_NEEDING_KEYS = frozenset({"text", "out"})

#: Cache key: a row's content is fully determined by these fields.
_RowCacheKey = tuple[str, int, str, datetime | None]


def proc_query_row(
    proc: ObservedProc, *, now: datetime, with_output: bool
) -> dict[str, Any]:
    """Build the mapping row the shared profile coercer consumes for *proc*."""

    command_text = shlex.join(proc.command) if proc.command else ""
    name_text = proc.label
    output_text = _output_tail(proc) if with_output else ""
    runtime_seconds = int(((proc.finished_at or now) - proc.started_at).total_seconds())
    started_epoch = int(proc.started_at.timestamp())
    is_running = proc_status_is_active(proc.status) and (
        proc.session_id is None or proc.session_live
    )

    fields: dict[str, object] = {
        "cmd": command_text,
        "name": name_text,
        "status": proc.status,
        "kind": proc.proc_type,
        "monitor": is_monitor_shell_row(proc),
        "running": is_running,
        "failed": proc.status in _FAILED_STATUSES,
        "min": runtime_seconds,
        "max": runtime_seconds,
        "since": started_epoch,
        "until": started_epoch,
    }
    if with_output:
        fields["out"] = output_text
        fields["text"] = _corpus_text(command_text, name_text, output_text)
    agent_name = monitor_row_agent_name(proc)
    if agent_name:
        fields["agent"] = agent_name
    if proc.project:
        fields["project"] = tuple(
            dict.fromkeys(
                value
                for value in (proc.project, project_display_name_for(proc.project))
                if value
            )
        )
    if proc.exit_code is not None:
        fields["exit"] = proc.exit_code
    if proc.finished_at is not None:
        finished_epoch = int(proc.finished_at.timestamp())
        fields["after"] = finished_epoch
        fields["before"] = finished_epoch

    return {
        "stable_id": proc.proc_id,
        "fields": fields,
        "searchable_text": _corpus_text(command_text, name_text, output_text),
    }


def _output_tail(proc: ObservedProc) -> str:
    text = proc.get_live_output()
    if len(text) <= PROC_QUERY_OUTPUT_TAIL_CHARS:
        return text
    return text[-PROC_QUERY_OUTPUT_TAIL_CHARS:]


def _corpus_text(command_text: str, name_text: str, output_text: str) -> str:
    return "\n".join(part for part in (command_text, name_text, output_text) if part)


def query_needs_output(expr: QueryExpr) -> bool:
    """Return whether *expr* touches free text, ``text:``, or ``out:``."""

    if isinstance(expr, StringMatch):
        return True
    if isinstance(expr, PropertyMatch):
        return expr.key in _OUTPUT_NEEDING_KEYS
    if isinstance(expr, NotExpr):
        return query_needs_output(expr.operand)
    if isinstance(expr, (AndExpr, OrExpr)):
        return any(query_needs_output(operand) for operand in expr.operands)
    raise TypeError(f"Unknown expression type: {type(expr)}")


@dataclass(slots=True)
class ProcQueryFilter:
    """Parses and evaluates proc queries against ``ObservedProc`` rows.

    Owns the compiled ``procs`` profile plus two small caches: parsed query
    ASTs keyed on the raw query string, and coerced query rows keyed on
    ``(proc_id, log.version, status, finished_at)`` so an unrelated
    keystroke re-evaluates already-built rows instead of rebuilding them.
    """

    profile: CompiledQueryProfile = field(
        default_factory=lambda: compile_query_profile(procs_query_schema())
    )
    _parsed: dict[str, QueryExpr] = field(default_factory=dict, init=False, repr=False)
    _rows: dict[_RowCacheKey, tuple[bool, ArtifactQueryRow]] = field(
        default_factory=dict, init=False, repr=False
    )

    def parse(self, query: str) -> QueryExpr:
        """Parse *query* under the ``procs`` profile, raising ``ProfileQueryError``."""

        cached = self._parsed.get(query)
        if cached is None:
            cached = parse_query_for_profile(query, self.profile)
            self._parsed[query] = cached
        return cached

    def matching(
        self,
        query: str,
        rows: Sequence[ObservedProc],
        *,
        now: datetime,
    ) -> list[ObservedProc]:
        """Return the subset of *rows* matching *query*, in their given order."""

        self._prune(row.proc_id for row in rows)
        if not query.strip():
            return list(rows)
        expr = self.parse(query)
        with_output = query_needs_output(expr)
        return [
            proc
            for proc in rows
            if evaluate_query_for_profile(
                expr,
                self._row_for(proc, now=now, with_output=with_output),
                self.profile,
            )
        ]

    def _row_for(
        self, proc: ObservedProc, *, now: datetime, with_output: bool
    ) -> ArtifactQueryRow:
        key: _RowCacheKey = (
            proc.proc_id,
            proc.log.version,
            proc.status,
            proc.finished_at,
        )
        cached = self._rows.get(key)
        # A cached row built without output can't answer a query that now
        # needs output; anything else (including an output-carrying row
        # answering an output-free query) is safe to reuse as-is.
        if cached is not None and (cached[0] or not with_output):
            return cached[1]
        row = coerce_artifact_query_row(
            self.profile,
            proc_query_row(proc, now=now, with_output=with_output),
        )
        self._rows[key] = (with_output, row)
        return row

    def _prune(self, live_proc_ids: Iterable[str]) -> None:
        live_ids = frozenset(live_proc_ids)
        stale = [key for key in self._rows if key[0] not in live_ids]
        for key in stale:
            del self._rows[key]


__all__ = [
    "PROC_QUERY_OUTPUT_TAIL_CHARS",
    "ProcQueryFilter",
    "ProfileQueryError",
    "proc_query_row",
    "query_needs_output",
]
