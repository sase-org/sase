"""Agent list widget for sase's TUI.

Public facade: the implementation lives in ``_agent_list_base`` (state
and list updates) and ``_agent_list_widget`` (highlight, patching,
formatting, and events). Only the public ``AgentList`` name is
re-exported here.
"""

from ._agent_list_widget import AgentList

__all__ = ["AgentList"]
