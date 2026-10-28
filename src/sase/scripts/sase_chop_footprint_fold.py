"""Fold Footprint spool data as an hourly housekeeping job."""

from __future__ import annotations

from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.footprint.fold import fold_ledger


@builtin_chop("footprint_fold")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    outcome = fold_ledger()
    folded = _mapping(outcome.get("fold"))
    pruned = _mapping(outcome.get("prune"))
    if int(folded.get("records_folded", 0)):
        runtime.log(
            f"folded {folded['records_folded']} Footprint record(s) "
            f"from {folded.get('files_folded', 0)} spool file(s)",
            "cyan",
        )
    reason = outcome.get("reason")
    if reason is None and not int(folded.get("files_folded", 0)):
        reason = "nothing_pending"
    return runtime.emit_summary(
        {
            "folded": bool(outcome.get("folded")),
            "reason": reason,
            "files_folded": int(folded.get("files_folded", 0)),
            "records_folded": int(folded.get("records_folded", 0)),
            "torn": int(folded.get("torn", 0)),
            "dropped": int(folded.get("dropped", 0)),
            "unknown_ids": int(folded.get("unknown_ids", 0)),
            "spool_files_deleted": int(folded.get("files_deleted", 0)),
            "spool_files_expired": int(folded.get("files_expired", 0)),
            "daily_pruned": int(pruned.get("daily_deleted", 0)),
            "coverage_pruned": int(pruned.get("coverage_deleted", 0)),
        },
        reason=str(reason) if reason else None,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main() -> None:
    run_builtin_chop("footprint_fold")


if __name__ == "__main__":
    main()
