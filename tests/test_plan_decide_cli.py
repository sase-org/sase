"""CLI-phase coverage for Plan Decisions (sase-1hi.5).

Facade preserving the original ``tests.test_plan_decide_cli`` import
path. Test coverage now lives in ``test_plan_decide_cli_parse``,
``test_plan_decide_cli_card``, and ``test_plan_decide_cli_outputs``;
shared fixtures live in ``tests._plan_decide_cli_shared``.
"""

from __future__ import annotations

from tests._plan_decide_cli_shared import PENDING_TALE

__all__ = ["PENDING_TALE"]
