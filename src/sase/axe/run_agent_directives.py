"""Directive extraction and agent metadata setup for the run agent runner.

Compatibility facade preserving the historical
``sase.axe.run_agent_directives`` import surface. The implementation lives in
smaller focused ``run_agent_directives_*`` modules.
"""

from sase.axe.run_agent_directives_extract import extract_directives_and_write_meta
from sase.axe.run_agent_directives_types import AgentInfo

__all__ = ["AgentInfo", "extract_directives_and_write_meta"]
