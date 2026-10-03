"""Frozen reference composer for the virtual body line model.

Facade preserving the ``tests.pager._reference_compose`` import path. The
frozen oracle implementation now lives in ``tests.pager._reference_body``
(composer), ``tests.pager._reference_gutter`` (gutter), and
``tests.pager._reference_labels`` (label capsules and target markers).

Do not edit the oracle implementation. If a parity test fails after a src
change, the src change moved rendering — that is the signal, not an excuse
to update the oracle.
"""

from __future__ import annotations

from tests.pager._reference_body import (
    ReferenceBody,
    expand_group_rows,
    reference_compose_body,
)

__all__ = [
    "ReferenceBody",
    "expand_group_rows",
    "reference_compose_body",
]
