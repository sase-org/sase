"""Deep diagnostic check registry for ``sase doctor``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec
from sase.doctor.checks_deep_agent_index import check_agent_index_verify
from sase.doctor.checks_deep_axe import check_axe_state
from sase.doctor.checks_deep_providers import check_provider_cli_versions
from sase.doctor.checks_deep_terminal import (
    check_kitty_graphics,
    check_tmux_version,
    check_truecolor,
)
from sase.doctor.checks_deep_purge_local_state import check_local_import_state
from sase.doctor.checks_deep_xprompt_lsp import check_xprompt_lsp

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def deep_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return deep diagnostic check specs not owned by another subsystem module."""
    return (
        CheckSpec(
            id="state.agent_index_verify",
            group="state",
            title="Agent artifact index verify",
            runner=check_agent_index_verify,
            deep=True,
        ),
        CheckSpec(
            id="state.imported_local_state",
            group="state",
            title="Imported local state",
            runner=check_local_import_state,
            deep=True,
        ),
        CheckSpec(
            id="ops.axe",
            group="ops",
            title="Axe runtime state",
            runner=check_axe_state,
            deep=True,
        ),
        CheckSpec(
            id="providers.cli_version",
            group="providers",
            title="Provider CLI versions",
            runner=lambda: check_provider_cli_versions(context),
            deep=True,
        ),
        CheckSpec(
            id="tools.xprompt_lsp",
            group="tools",
            title="xprompt LSP command",
            runner=lambda: check_xprompt_lsp(context),
            deep=True,
        ),
        CheckSpec(
            id="terminal.kitty_graphics",
            group="terminal",
            title="Kitty graphics protocol",
            runner=lambda: check_kitty_graphics(context),
            deep=True,
        ),
        CheckSpec(
            id="tools.tmux_version",
            group="tools",
            title="tmux passthrough version",
            runner=lambda: check_tmux_version(context),
            deep=True,
        ),
        CheckSpec(
            id="terminal.truecolor",
            group="terminal",
            title="Terminal truecolor",
            runner=lambda: check_truecolor(context),
            deep=True,
        ),
    )


__all__ = [
    "deep_check_specs",
]
