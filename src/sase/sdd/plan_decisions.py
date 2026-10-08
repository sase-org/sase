"""Single Python entry point for Plan Decisions.

Telegram and every other surface import this module, not ``sase_core_rs``,
for decisions. It wraps the seven core bindings and owns the two host
steps: memory-scope resolution and quote verification.

This module is a facade: the implementation lives in
``sase.sdd._plan_decisions_shared``,
``sase.sdd.plan_decisions_bindings``,
``sase.sdd.plan_decisions_wire``, and
``sase.sdd.plan_decisions_host``. Only public names are re-exported here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.sdd.plan_decision_handoff import StampedDecisions

from sase.sdd import plan_decisions_host as _plan_decisions_host
from sase.sdd._plan_decisions_shared import (
    DECISION_SCHEMA_PREFIX as DECISION_SCHEMA_PREFIX,
    OVERLAP_CODE as OVERLAP_CODE,
    SEVEN_BINDINGS as SEVEN_BINDINGS,
    UNVERIFIED_CODE as UNVERIFIED_CODE,
    artifacts_dir_from_env as artifacts_dir_from_env,
    in_agent_context as in_agent_context,
)
from sase.sdd.plan_decisions_bindings import (
    digest_binding as digest_binding,
    payload_binding as payload_binding,
    prompt_block_binding as prompt_block_binding,
    resolve_binding as resolve_binding,
    sheet_binding as sheet_binding,
    summary_binding as summary_binding,
)
from sase.sdd.plan_decisions_host import (
    build_definitions as build_definitions,
    resolve_direct_with_definitions as resolve_direct_with_definitions,
    validate_host_checks as validate_host_checks,
)
from sase.sdd.plan_decisions_wire import (
    compile_input_properties as compile_input_properties,
    count_memory as count_memory,
    validated_to_wire_dict as validated_to_wire_dict,
)

resolve_plan_decisions_for_direct_approval = (
    _plan_decisions_host.resolve_plan_decisions_for_direct_approval
)

try:
    from sase.notification_gates.model_results import (
        effective_response_input as effective_response_input,
    )
except Exception:  # pragma: no cover - import surface stays available

    def effective_response_input(
        response: Mapping[str, Any], option_id: str
    ) -> dict[str, Any]:  # type: ignore[no-redef]
        """Fallback effective input when the gate model is unavailable."""
        return {}


try:
    from sase.sdd.plan_decision_handoff import (
        load_stamped_decisions as load_stamped_decisions,
    )
except Exception:  # pragma: no cover - import surface stays available

    def load_stamped_decisions(
        plan_path: str | Path, tier: str | None = None
    ) -> StampedDecisions | None:  # type: ignore[no-redef]
        """Fallback loader when the handoff leg is unavailable."""
        return None


__all__ = [
    "DECISION_SCHEMA_PREFIX",
    "OVERLAP_CODE",
    "SEVEN_BINDINGS",
    "UNVERIFIED_CODE",
    "build_definitions",
    "resolve_direct_with_definitions",
    "compile_input_properties",
    "count_memory",
    "digest_binding",
    "effective_response_input",
    "in_agent_context",
    "artifacts_dir_from_env",
    "load_stamped_decisions",
    "payload_binding",
    "prompt_block_binding",
    "resolve_binding",
    "resolve_plan_decisions_for_direct_approval",
    "sheet_binding",
    "summary_binding",
    "validate_host_checks",
    "validated_to_wire_dict",
]
