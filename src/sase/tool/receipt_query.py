"""``sase tool receipt`` query presentation.

Reports the covering verdict receipt for one named tool at the current
fingerprint, or a typed refusal. The query never claims the result meets
any completion policy; it only states what the ledger holds.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Any

from sase.core.tool_run import tool_run_receipt_lookup
from sase.tool.argv import ToolRunUsageError, resolve_run_argv
from sase.tool.liveness import reconcile_unsettled_tool_runs
from sase.tool.observe import observe_fingerprint

_ACCEPT_CLI_TO_WIRE = {
    "pass": "pass",
    "no-new": "no_new_failures",
}


@dataclass(frozen=True)
class ToolReceiptCliRequest:
    tool: str
    accept: str = "pass"
    json: bool = False


def handle_receipt(request: ToolReceiptCliRequest) -> int:
    """Render ``sase tool receipt TOOL``; 0 covered, 1 refused, 2 usage."""

    accept = _ACCEPT_CLI_TO_WIRE.get(request.accept)
    if accept is None:
        print(
            f"invalid --accept {request.accept!r} (expected 'pass' or 'no-new')",
            file=sys.stderr,
        )
        return 2
    tool_name = request.tool.strip()
    if not tool_name:
        print(
            "Usage: sase tool receipt TOOL [-a/--accept ...] [-j/--json]",
            file=sys.stderr,
        )
        return 2
    try:
        resolved = resolve_run_argv([tool_name])
    except ToolRunUsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if resolved.adhoc or not resolved.tool_name:
        print(f"unknown tool {tool_name!r}", file=sys.stderr)
        return 2
    reconcile_unsettled_tool_runs()
    fingerprint = observe_fingerprint(resolved)
    payload: dict[str, Any] = {
        "project": resolved.resolved_project_identity(),
        "tool_name": resolved.tool_name,
        "definition_digest": resolved.digest
        or str(fingerprint.get("definition_digest") or ""),
        "extra_args_digest": str(fingerprint.get("extra_args_digest") or ""),
        "fingerprint": fingerprint,
        "accept": [accept],
    }
    try:
        result = tool_run_receipt_lookup(payload)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if request.json:
        print(
            json.dumps(
                _receipt_envelope(resolved.tool_name, result), indent=2, sort_keys=True
            )
        )
    else:
        _print_receipt_human(resolved.tool_name, result)
    for diagnostic in result.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0 if result.get("outcome") == "covered" else 1


def _receipt_envelope(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return the versioned machine-readable receipt query envelope."""

    return {
        "schema_version": 1,
        "tool": tool_name,
        "outcome": result.get("outcome"),
        "refusal": result.get("refusal"),
        "receipt": result.get("receipt"),
        "age_seconds": result.get("age_seconds"),
        "reason": result.get("reason"),
        "changed_paths": list(result.get("changed_paths") or ()),
        "paths_truncated": bool(result.get("paths_truncated") or False),
        "diagnostics": list(result.get("diagnostics") or ()),
    }


def _print_receipt_human(tool_name: str, result: dict[str, Any]) -> None:
    """Print the human receipt report without any policy claim."""

    if result.get("outcome") == "covered":
        receipt = result.get("receipt") or {}
        print(f"covered: {tool_name}")
        print(f"  receipt: {receipt.get('receipt_id') or '-'}")
        print(f"  run: {receipt.get('source_run_id') or '-'}")
        print(f"  verdict: {receipt.get('verdict') or '-'}")
        print(f"  age: {_format_age(result.get('age_seconds'))}")
        return
    refusal = result.get("refusal") or "refused"
    reason = result.get("reason") or str(refusal)
    print(f"refused: {tool_name} ({refusal}: {reason})")
    changed = [str(path) for path in result.get("changed_paths") or ()]
    for path in changed:
        print(f"  changed: {path}")
    if result.get("paths_truncated"):
        print("  changed: ... (truncated)")


def _format_age(age_seconds: object) -> str:
    """Format an age in seconds for human display."""

    if type(age_seconds) is bool or not isinstance(age_seconds, (int, float)):
        return "-"
    total = max(0, int(age_seconds))
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


__all__ = ["ToolReceiptCliRequest", "handle_receipt"]
