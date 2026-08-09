"""TUI module for the ace subcommand using Textual."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["AceApp", "AceExitAction"]

_LAZY_EXPORTS = {
    "AceApp": (".app", "AceApp"),
    "AceExitAction": (".exit_action", "AceExitAction"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)
