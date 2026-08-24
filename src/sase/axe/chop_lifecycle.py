"""Public facade for chop action lifecycle finalization.

This module preserves the historical ``sase.axe.chop_lifecycle`` import
surface while the implementation lives in smaller focused modules.
"""

from ._chop_lifecycle_completion import _agent_completion
from ._chop_lifecycle_runner import finalize_launched_chop_runs

__all__ = ["finalize_launched_chop_runs"]
