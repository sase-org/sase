"""Question gate shells: the question gate as a family-attached gate shell."""

from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "create_question_gate_shell": (
        "sase.question_shell.create",
        "create_question_gate_shell",
    ),
    "question_base_prompt": ("sase.question_shell.rounds", "question_base_prompt"),
    "question_next_action": ("sase.question_shell.followup", "question_next_action"),
    "question_rounds": ("sase.question_shell.rounds", "question_rounds"),
    "resolve_question_chain_parent": (
        "sase.question_shell.create",
        "resolve_question_chain_parent",
    ),
}


def __getattr__(name: str) -> Any:
    """Lazily load question-shell helpers to keep this package cheap to import."""
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


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)


__all__ = [
    "create_question_gate_shell",
    "question_base_prompt",
    "question_next_action",
    "question_rounds",
    "resolve_question_chain_parent",
]
