"""Integrate the tmux Agent launcher into the Models panel."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sase.tmux_agent import (
    TmuxAgentCatalog,
    TmuxRunner,
    build_tmux_agent_catalog,
    inside_tmux,
)

from .tmux_agent_modal import TmuxAgentModal

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object

_EMPTY_TMUX_AGENT_CATALOG = TmuxAgentCatalog(
    entries=(), default_provider=None, directory=""
)

_NOT_IN_TMUX_WARNING = (
    "ACE is not running inside tmux; start ACE in a tmux window to launch agent CLIs."
)


class ModelsPanelTmuxAgentMixin(_MixinBase):
    """Open the tmux Agent panel to launch an agent CLI in a new tmux window."""

    def action_tmux_agent(self) -> None:
        """Open the tmux Agent panel, or warn when ACE is not inside tmux."""
        if not inside_tmux():
            self.notify(_NOT_IN_TMUX_WARNING, severity="warning")  # type: ignore[attr-defined]
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            TmuxAgentModal(
                _EMPTY_TMUX_AGENT_CATALOG,
                load_catalog=self._load_tmux_agent_catalog,
            )
        )

    def _load_tmux_agent_catalog(self) -> TmuxAgentCatalog:
        """Resolve the launch directory and build the tmux Agent catalog."""
        runner = TmuxRunner()
        directory = runner.current_pane_directory() or os.getcwd()
        return build_tmux_agent_catalog(directory=directory)


__all__ = ["ModelsPanelTmuxAgentMixin"]
