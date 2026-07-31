"""Tribe description checks for ``sase doctor``."""

from __future__ import annotations

from sase.config import load_merged_config
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_tribes() -> DiagnosticCheck:
    """Flag configured ``ace.tribes`` entries missing a required description."""
    config = load_merged_config()
    ace = config.get("ace", {})
    tribes = ace.get("tribes", {}) if isinstance(ace, dict) else {}
    if not isinstance(tribes, dict):
        tribes = {}

    problems: list[str] = []
    tribe_count = 0
    for name, entry in sorted(tribes.items(), key=lambda item: str(item[0])):
        if not isinstance(name, str):
            continue
        tribe_count += 1
        if not isinstance(entry, dict):
            problems.append(f"ace.tribes.{name} must be an object with a description")
            continue
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            problems.append(f"ace.tribes.{name}.description is missing or blank")

    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} configured tribe(s) missing a description"
        if problems
        else f"{tribe_count} configured tribe(s) documented"
    )
    next_steps = (
        (
            "Add a one-line `description` to each reported tribe under "
            "~/.config/sase/sase.yml (see docs/configuration.md#acetribes).",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.tribes",
        group="config",
        status=status,
        title="Tribe descriptions",
        summary=summary,
        details=tuple(problems)[:MAX_DETAIL_ROWS],
        next_steps=next_steps,
        data={
            "tribe_count": tribe_count,
            "problem_count": len(problems),
            "problems": problems,
        },
    )
