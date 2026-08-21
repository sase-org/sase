"""Rich rendering helpers shared by the ``sase flag`` subcommands."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.text import Text

from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FlagKind,
)

FLAG_KIND_STYLE = "italic"
FLAG_ENABLED_STYLE = "bold green"
FLAG_DISABLED_STYLE = "bold"


def resolve_console(console: Console | None) -> Console:
    """Return the caller's console, or a plain one for real CLI runs."""
    if console is not None:
        return console
    return Console(highlight=False)


def on_off(value: bool) -> str:
    """Render a boolean flag value the way the CLI spells it."""
    return "on" if value else "off"


def kind_text(kind: FlagKind) -> Text:
    """Render a flag kind with the shared list and footer treatment."""
    return Text(kind, style=FLAG_KIND_STYLE)


def enabled_text(enabled: bool) -> Text:
    """Render an effective on/off value with the shared list and footer treatment."""
    return Text(
        on_off(enabled),
        style=FLAG_ENABLED_STYLE if enabled else FLAG_DISABLED_STYLE,
    )


def source_text(decision: FeatureFlagDecision) -> Text:
    """Render where a resolved value came from."""
    if decision.source == "env":
        env_name = decision.source_detail or SASE_FEATURE_FLAGS_ENV
        return Text(f"ENV:{env_name}", style="bold reverse")
    if decision.source == "cli":
        option = decision.source_detail or (
            "--enable-feature" if decision.enabled else "--disable-feature"
        )
        return Text(f"CLI:{option}", style="bold reverse")
    if decision.source == "state":
        if decision.source_detail:
            return Text(f"SAVED:{decision.source_detail}")
        return Text("SAVED")
    if decision.source == "default":
        return Text("default", style="dim")
    if decision.source_detail:
        return Text(f"{decision.source}:{decision.source_detail}")
    return Text(decision.source)


def render_diagnostics(
    diagnostics: Sequence[FeatureFlagDiagnostic],
    console: Console,
) -> None:
    """Print resolver diagnostics below whatever the subcommand rendered."""
    if not diagnostics:
        return
    console.print()
    for diagnostic in diagnostics:
        style = "bold red" if diagnostic.severity == "error" else "bold yellow"
        console.print(Text(f"{diagnostic.severity}: {diagnostic.message}", style=style))


__all__ = [
    "FLAG_DISABLED_STYLE",
    "FLAG_ENABLED_STYLE",
    "FLAG_KIND_STYLE",
    "enabled_text",
    "kind_text",
    "on_off",
    "render_diagnostics",
    "resolve_console",
    "source_text",
]
