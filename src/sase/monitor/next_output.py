"""Import-light ``--next-output`` defaults shared by monitor models and results.

``sase.monitor.models`` is on the always-on stale-running sweep's import path,
so these constants live in a leaf module instead of the result-projection and
follow-up-prompt modules, whose imports pull in the LLM-provider graph.
"""

from __future__ import annotations

from sase.core.continuation_wire import ContinuationEvidencePolicy

DEFAULT_NEXT_OUTPUT: ContinuationEvidencePolicy = "auto"
LEGACY_NEXT_OUTPUT: ContinuationEvidencePolicy = "tail"

__all__ = ["DEFAULT_NEXT_OUTPUT", "LEGACY_NEXT_OUTPUT"]
