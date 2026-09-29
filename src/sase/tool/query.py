"""``sase tool runs`` and ``sase tool show`` query presentation.

This module is a facade: the runs implementation lives in
``sase.tool.query_runs``, the show implementation in ``sase.tool.query_show``
(with follow-up streaming in ``sase.tool.query_follow``), and the helpers
they share in the private ``sase.tool._query_shared`` module. Import the
public names from here, never from the siblings directly.
"""

from __future__ import annotations

from sase.tool.query_runs import (
    ToolRunsCliRequest as ToolRunsCliRequest,
    handle_runs as handle_runs,
)
from sase.tool.query_show import (
    ToolShowCliRequest as ToolShowCliRequest,
    handle_show as handle_show,
)


__all__ = [
    "ToolRunsCliRequest",
    "ToolShowCliRequest",
    "handle_runs",
    "handle_show",
]
