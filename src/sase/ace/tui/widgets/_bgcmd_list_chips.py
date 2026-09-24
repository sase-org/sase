"""Status chips and markers for the background command list widget."""

from typing import TYPE_CHECKING, Any

from ._bgcmd_list_styles import _SERVICE_DISABLED_STYLE, _SERVICE_WARN_STYLE

if TYPE_CHECKING:
    from sase.service.status import ServiceEnablement


def lumberjack_status_chip(status: Any) -> tuple[str, str] | None:
    """Return a compact (label, style) chip for a lumberjack status, or None."""
    if status is None:
        return None
    errors = getattr(status, "errors_encountered", 0) or 0
    cycles = getattr(status, "cycles_run", 0) or 0
    if errors > 0:
        return (f"{errors}e", "bold red")
    if cycles > 0:
        return (f"{cycles}c", "dim")
    return None


def service_proc_label(name: str) -> str:
    """Return the compact user-facing name for a service proc row."""
    if name == "scheduler":
        return "Scheduler"
    return name.replace("_", " ").title()


def service_proc_marker(proc: Any) -> tuple[str, str]:
    """Return the one-character service-proc status marker and style."""
    if proc is None:
        return ("·", "dim")
    from .._service_severity import proc_clean_exit, service_proc_marker

    enablement = getattr(proc, "enablement", None)
    return service_proc_marker(
        getattr(proc, "state", ""),
        getattr(proc, "desired", ""),
        available=getattr(proc, "available", True),
        enabled=True if enablement is None else getattr(enablement, "enabled", True),
        clean_exit=proc_clean_exit(proc),
    )


_SERVICE_CHIP_MAX_WIDTH = 32


def service_enablement_chip(enablement: "ServiceEnablement") -> str | None:
    """Return inline provenance text for a disabled proc, or ``None`` if enabled.

    The Rust-derived ``summary`` already reads ``disabled here`` for a local
    override and ``disabled by <layer>`` otherwise; it is only truncated here.
    """
    if enablement.enabled:
        return None
    text = getattr(enablement, "summary", "") or "disabled"
    if len(text) > _SERVICE_CHIP_MAX_WIDTH:
        text = text[: _SERVICE_CHIP_MAX_WIDTH - 1] + "…"
    return text


def service_proc_chip(proc: Any) -> tuple[str, str] | None:
    """Return a short service-proc state chip, or None when redundant."""
    from .._service_severity import proc_clean_exit, service_proc_style

    if not getattr(proc, "available", True):
        reason = getattr(proc, "unavailable_reason", None)
        text = f"unavailable: {reason}" if reason else "unavailable"
        if len(text) > _SERVICE_CHIP_MAX_WIDTH:
            text = text[: _SERVICE_CHIP_MAX_WIDTH - 1] + "…"
        return (text, _SERVICE_WARN_STYLE)
    enablement = getattr(proc, "enablement", None)
    if enablement is not None and not getattr(enablement, "enabled", True):
        disabled_text = service_enablement_chip(enablement)
        if disabled_text is not None:
            return (disabled_text, _SERVICE_DISABLED_STYLE)
    state = getattr(proc, "state", "")
    desired = getattr(proc, "desired", "")
    style = service_proc_style(
        state,
        desired,
        available=True,
        enabled=True,
        clean_exit=proc_clean_exit(proc),
    )
    restarts = int(getattr(proc, "restarts", 0) or 0)
    restarts_suffix = f" · {restarts}r" if restarts > 0 else ""
    if state == "running":
        if not restarts_suffix:
            return None
        return (f"{restarts}r", "dim")
    summary = getattr(proc, "summary", "") or state
    if not summary:
        return (f"{restarts}r", "dim") if restarts_suffix else None
    text = f"{summary}{restarts_suffix}"
    if len(text) > _SERVICE_CHIP_MAX_WIDTH:
        text = text[: _SERVICE_CHIP_MAX_WIDTH - 1] + "…"
    return (text, style)


__all__ = [
    "_SERVICE_CHIP_MAX_WIDTH",
    "lumberjack_status_chip",
    "service_enablement_chip",
    "service_proc_chip",
    "service_proc_label",
    "service_proc_marker",
]
