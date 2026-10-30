#!/usr/bin/env python3
"""Enforce indexed artifact-file retention from the hourly housekeeping lane.

The runner only keeps a throttled fallback: it runs the same pass when the
stamp is missing or older than 24 hours, and skips immediately when this job
holds the exclusive lock.
"""

from __future__ import annotations

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.artifact_file_retention_pass import enforce_artifact_retention


def _reason_for(outcome: str) -> str | None:
    if outcome == "enforced":
        return None
    return outcome


@builtin_chop("artifact_retention")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    result = enforce_artifact_retention()
    if result.outcome == "enforced":
        runtime.log(
            (
                "trashed "
                f"{result.rows_trashed} rows, "
                f"reclaimed {result.bytes_reclaimed} bytes, "
                f"purged {result.purged_entries} trash entries"
            ),
            "cyan",
        )
    elif result.outcome == "protection_unavailable":
        sources = ", ".join(result.sources_unavailable) or "unknown"
        runtime.log.warning(
            f"artifact_retention skipped: protection sources unavailable: {sources}"
        )
    elif result.outcome == "failed":
        runtime.log.warning(
            f"artifact_retention failed: {result.error or 'unknown error'}"
        )
    builder = runtime.emit_summary(
        {
            "outcome": result.outcome,
            "stamped": int(result.stamped),
            "trashed": result.rows_trashed,
            "bytes": result.bytes_reclaimed,
            "purged": result.purged_entries,
        },
        reason=_reason_for(result.outcome),
    )
    if result.outcome == "failed":
        builder.status = "check_error"
    return builder


def main() -> None:
    run_builtin_chop("artifact_retention")


if __name__ == "__main__":
    main()
