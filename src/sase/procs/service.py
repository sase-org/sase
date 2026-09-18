"""Compatibility facade for proc submission service imports."""

from .runner import ProcControlError, ProcSubmitError, submit_proc_request

__all__ = [
    "ProcControlError",
    "ProcSubmitError",
    "submit_proc_request",
]
