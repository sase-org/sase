"""Report step for the sync workflow: summarize the sync outcome."""


def main(*, success: bool, has_conflicts: bool, all_resolved: bool) -> None:
    """Summarize the sync workflow outcome.

    Four possible outcomes:
    - **success**: Clean sync, no conflicts encountered.
    - **resolved**: Conflicts were detected and the AI agent resolved them all.
    - **unresolved**: Conflicts were detected but max iterations were hit.
    - **error**: Sync failed for a non-conflict reason.

    Prints key=value output:
    - ``status``: one of ``success``, ``resolved``, ``unresolved``, ``error``
    - ``message``: human-readable summary
    """
    if success:
        print("status=success")
        print("message=Sync completed successfully — no conflicts.")
    elif has_conflicts and all_resolved:
        print("status=resolved")
        print("message=Sync completed — all conflicts were resolved by the AI agent.")
    elif has_conflicts and not all_resolved:
        print("status=unresolved")
        print(
            "message=Sync incomplete — some conflicts could not be resolved (max iterations reached)."
        )
    else:
        print("status=error")
        print("message=Sync failed due to a non-conflict error.")
