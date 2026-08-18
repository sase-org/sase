"""File-hook config checks for ``sase doctor``."""

from __future__ import annotations

from sase.config.file_hooks import get_file_hook_diagnostics
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_file_hooks() -> DiagnosticCheck:
    """Surface file hooks silently dropped by an unresolvable ``use:`` value.

    ``_resolve_file_hook_provider`` still fails soft for the running process
    so one broken hook cannot break every other hook, but a disappeared hook
    is otherwise invisible; this check is the actionable ``sase doctor``/
    ``sase validate`` surface for that gap.
    """
    diagnostics = get_file_hook_diagnostics()
    problems = [
        f"{diagnostic.source_layer}: {diagnostic.hook_name}: {diagnostic.message}"
        for diagnostic in diagnostics
    ]

    status: CheckStatus = "ERROR" if problems else "OK"
    return DiagnosticCheck(
        id="config.file_hooks",
        group="config",
        status=status,
        title="File hook config",
        summary=(
            f"{len(problems)} file_hooks entry(s) dropped by an invalid config"
            if problems
            else "file_hooks config is usable"
        ),
        details=tuple(problems)[:MAX_DETAIL_ROWS],
        next_steps=(
            (
                "Fix the named file_hooks entries, then rerun "
                "`sase doctor -C config.file_hooks`.",
            )
            if problems
            else ()
        ),
        data={"problems": problems},
    )


__all__ = ["check_config_file_hooks"]
