"""Additive per-provider enrichers for FINAL instance cards (``final-instance-cards``).

Each enricher returns **additional** renderables built from typed
projection data only. The generic card in :mod:`instance_card` renders
first and completely on its own; a provider without an entry here —
every plugin included — renders through the generic path with no
provider-specific branch running anywhere.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Callable

from rich.text import Text

from sase.finalizers.view_vocabulary import FAILURE_COLOR, SUCCESS_COLOR, WARNING_COLOR

#: Cap for failing-line and argv values shown inline before truncation.
ENRICHER_VALUE_CAP = 160


def _fit(line: str, width: int) -> str:
    width = max(20, int(width))
    if len(line) <= width:
        return line
    return line[: max(0, width - 1)] + "…"


def _iter_run_items(node_item: Any, runs: Any) -> list[Any]:
    """Return every per-run detail record for one node-level instance."""
    instance_id = str(getattr(node_item, "instance_id", "") or "")
    items: list[Any] = []
    for run in runs or ():
        for item in getattr(run, "instances", ()) or ():
            if str(getattr(item, "instance_id", "") or "") == instance_id:
                items.append(item)
    return items


def _iter_evidence(items: list[Any]) -> list[Any]:
    evidence: list[Any] = []
    for item in items:
        evidence.extend(list(getattr(item, "evidence", ()) or ()))
    return evidence


def _iter_operations(items: list[Any]) -> list[Any]:
    operations: list[Any] = []
    for item in items:
        operations.extend(list(getattr(item, "operations", ()) or ()))
    return operations


def _evidence_by_type(evidence: list[Any], evidence_type: str) -> list[Any]:
    return [
        item
        for item in evidence
        if str(getattr(item, "evidence_type", "") or "") == evidence_type
    ]


def _commit_enrichments(
    node_item: Any, runs: Any, *, width: int = 120
) -> tuple[Any, ...]:
    """Return the per-repo commit table for a ``builtin@commit`` instance."""
    items = _iter_run_items(node_item, runs)
    evidence = _iter_evidence(items)
    if not items and not evidence:
        return ()
    lines: list[Any] = [Text("  commit detail", style="bold")]
    shas = _evidence_by_type(evidence, "sha")
    urls = _evidence_by_type(evidence, "url")
    beads = _evidence_by_type(evidence, "bead")
    rendered_any = False
    for record in shas:
        value = str(getattr(record, "display", None) or getattr(record, "value", ""))
        short = value[:7] if len(value) >= 7 else value
        kind = str(getattr(record, "kind", "") or "sha")
        lines.append(Text(_fit(f"    {kind} {short}  ↗ commit view", width)))
        rendered_any = True
    for record in urls:
        value = str(getattr(record, "display", None) or getattr(record, "value", ""))
        kind = str(getattr(record, "kind", "") or "url")
        lines.append(Text(_fit(f"    {kind} {value}", width)))
        rendered_any = True
    for record in beads:
        value = str(getattr(record, "display", None) or getattr(record, "value", ""))
        lines.append(Text(_fit(f"    bead {value}", width)))
        rendered_any = True
    deferrals = [
        getattr(item, "deferral", None)
        for item in items
        if getattr(item, "deferral", None) is not None
    ]
    for deferral in deferrals:
        reason = str(getattr(deferral, "reason", "") or "")
        paths = [str(path) for path in (getattr(deferral, "paths", ()) or ())]
        detail = reason
        if paths:
            detail += f" · {', '.join(paths[:5])}"
            if len(paths) > 5:
                detail += f" +{len(paths) - 5} more"
        lines.append(
            Text(_fit(f"    deferred {detail}".rstrip(), width), style=WARNING_COLOR)
        )
        rendered_any = True
    warnings = 0
    for item in items:
        try:
            warnings = max(warnings, int(getattr(item, "warnings", 0) or 0))
        except (TypeError, ValueError):
            pass
    if warnings > 0:
        lines.append(
            Text(
                f"    ⚠{warnings} warning{'s' if warnings != 1 else ''} (see steps above)",
                style=WARNING_COLOR,
            )
        )
        rendered_any = True
    if not rendered_any:
        return ()
    return tuple(lines)


def _command_enrichments(
    node_item: Any, runs: Any, *, width: int = 120
) -> tuple[Any, ...]:
    """Return the argv line and failing-op summary for ``builtin@command``."""
    items = _iter_run_items(node_item, runs)
    operations = _iter_operations(items)
    argv_seen: list[str] = []
    for operation in operations:
        argv = list(getattr(operation, "argv", ()) or ())
        if argv:
            rendered = " ".join(str(part) for part in argv)
            if rendered and rendered not in argv_seen:
                argv_seen.append(rendered)
    failing: list[Any] = []
    for operation in operations:
        returncode = getattr(operation, "returncode", None)
        if (
            isinstance(returncode, int)
            and not isinstance(returncode, bool)
            and returncode != 0
        ):
            failing.append(operation)
        elif getattr(operation, "timed_out", False):
            failing.append(operation)
    if not argv_seen and not failing:
        return ()
    lines: list[Any] = [Text("  command detail", style="bold")]
    for rendered in argv_seen:
        lines.append(
            Text(_fit(f"    $ {rendered[:ENRICHER_VALUE_CAP]}", width), style="dim")
        )
    for operation in failing:
        label = (
            getattr(operation, "label", None) or getattr(operation, "op", "") or "run"
        )
        returncode = getattr(operation, "returncode", None)
        if getattr(operation, "timed_out", False):
            lines.append(
                Text(_fit(f"    ✗ {label} timed out", width), style=FAILURE_COLOR)
            )
        else:
            lines.append(
                Text(
                    _fit(f"    ✗ {label} · exit {returncode}", width),
                    style=FAILURE_COLOR,
                )
            )
    succeeded = [op for op in operations if getattr(op, "returncode", None) == 0]
    if succeeded and not failing:
        lines.append(Text("    ✓ exit 0", style=SUCCESS_COLOR))
    return tuple(lines)


#: Registry of additive enrichers keyed by ``provider_ref``. Plugins get
#: none: the generic card is their whole render.
ENRICHERS: dict[str, Callable[..., tuple[Any, ...]]] = {
    "builtin@commit": _commit_enrichments,
    "builtin@command": _command_enrichments,
}


def instance_enrichments(
    provider_ref: str | None, node_item: Any, runs: Any, *, width: int = 120
) -> tuple[Any, ...]:
    """Return additive enricher renderables for ``provider_ref`` (possibly none)."""
    if not provider_ref:
        return ()
    enricher = ENRICHERS.get(str(provider_ref))
    if enricher is None:
        return ()
    try:
        return tuple(enricher(node_item, runs, width=width))
    except Exception:
        return ()


__all__ = [
    "ENRICHERS",
    "ENRICHER_VALUE_CAP",
    "instance_enrichments",
]
