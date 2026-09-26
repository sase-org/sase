"""Plan gate turn creation and settlement helpers."""

from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "create_plan_gate_turn": ("sase.plan_gate_turn.create", "create_plan_gate_turn"),
    "plan_gate_turn_block": ("sase.plan_gate_turn.create", "plan_gate_turn_block"),
    "plan_result_from_gate_creation": (
        "sase.plan_gate_turn.followup",
        "plan_result_from_gate_creation",
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


_PEP562_HOOKS = (__getattr__, __dir__)

__all__ = [
    "create_plan_gate_turn",
    "plan_gate_turn_block",
    "plan_gate_turn_block",
    "plan_result_from_gate_creation",
]
