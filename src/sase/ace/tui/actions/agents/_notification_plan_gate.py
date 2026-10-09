"""Neutral plan gate loading and response execution.

Compatibility facade: focused implementations live in
:mod:`._notification_plan_gate_load`,
:mod:`._notification_plan_gate_submit`, and
:mod:`._notification_plan_gate_stale`.
"""

from __future__ import annotations

from ._notification_plan_gate_load import (
    PlanGateModalLoad as PlanGateModalLoad,
    apply_settled_text_to_open_modal as apply_settled_text_to_open_modal,
    load_neutral_plan_modal_data as load_neutral_plan_modal_data,
    prepare_settled_texts_for_notifications as prepare_settled_texts_for_notifications,
)
from ._notification_plan_gate_submit import (
    submit_neutral_plan_response as submit_neutral_plan_response,
)

__all__ = [
    "PlanGateModalLoad",
    "apply_settled_text_to_open_modal",
    "load_neutral_plan_modal_data",
    "prepare_settled_texts_for_notifications",
    "submit_neutral_plan_response",
]
