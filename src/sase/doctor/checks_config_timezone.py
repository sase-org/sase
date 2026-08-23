"""Configured-vs-system timezone check for ``sase doctor``."""

from __future__ import annotations

from sase.config.core import ConfigLayer, load_config_layers
from sase.core.time import get_timezone, system_timezone
from sase.diagnostics import CheckStatus, DiagnosticCheck


def _zone_label(tz: object) -> str:
    return str(getattr(tz, "key", None) or tz)


def _timezone_source_layer_path(layers: list[ConfigLayer]) -> str | None:
    """Return the path of the last loaded layer that sets ``timezone``."""
    path: str | None = None
    for layer in layers:
        if layer.loaded and "timezone" in layer.keys:
            path = layer.path or layer.name
    return path


def check_config_timezone() -> DiagnosticCheck:
    """Report the resolved timezone, its source layer, and the system zone."""
    layers = load_config_layers()
    source_path = _timezone_source_layer_path(layers)

    configured_tz = get_timezone()
    system_tz = system_timezone()
    configured_label = _zone_label(configured_tz)
    system_label = _zone_label(system_tz)
    matches = configured_label == system_label

    status: CheckStatus = "OK" if matches else "WARN"
    summary = (
        f"configured timezone {configured_label} matches the system timezone"
        if matches
        else (
            f"configured timezone {configured_label} diverges from the "
            f"system timezone {system_label}"
        )
    )
    details: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    if not matches:
        layer_desc = source_path or "an unknown config layer"
        details = (
            f"{layer_desc} sets timezone to {configured_label!r}; the host "
            f"system timezone is {system_label!r}",
        )
        next_steps = (
            f"If {system_label} is correct for this host, remove or fix the "
            f"timezone key in {layer_desc}. If {configured_label} is "
            "intentional (a remote or deliberately UTC host), no action is "
            "needed.",
        )

    return DiagnosticCheck(
        id="config.timezone",
        group="config",
        status=status,
        title="Configured timezone",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "configured_timezone": configured_label,
            "source_layer_path": source_path,
            "system_timezone": system_label,
        },
    )


__all__ = ["check_config_timezone"]
