"""Editor completion catalog for configured dispatch machines."""

from __future__ import annotations

from typing import Any

from .config import load_dispatch_config


def machine_completion_catalog_payload() -> dict[str, Any]:
    """Return non-secret `%dispatch` completion rows from local config."""
    config = load_dispatch_config()
    entries: list[dict[str, object]] = []
    for machine in config.machines:
        status = "quarantined" if machine.quarantined else "ok"
        documentation = machine.quarantine_reason if machine.quarantined else ""
        entries.append(
            {
                "alias": machine.alias,
                "display": machine.alias,
                "provider_ref": machine.provider_ref,
                "installation_id": machine.pinned_installation_id,
                "endpoint": machine.endpoint,
                "status": status,
                "documentation": documentation,
            }
        )
    return {"schema_version": 1, "entries": entries}


__all__ = ["machine_completion_catalog_payload"]
