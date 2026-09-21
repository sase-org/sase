"""Service metadata carried on durable proc rows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

SERVICE_PROC_MODE_DAEMON: Final = "daemon"
SERVICE_PROC_MODE_ONESHOT: Final = "oneshot"
SERVICE_PROC_MODES: Final = frozenset(
    {SERVICE_PROC_MODE_DAEMON, SERVICE_PROC_MODE_ONESHOT}
)

SERVICE_PROC_SOURCE_BUILTIN: Final = "builtin"
SERVICE_PROC_SOURCE_PLUGIN: Final = "plugin"
SERVICE_PROC_SOURCE_USER: Final = "user"
SERVICE_PROC_SOURCE_TRANSIENT: Final = "transient"
SERVICE_PROC_SOURCES: Final = frozenset(
    {
        SERVICE_PROC_SOURCE_BUILTIN,
        SERVICE_PROC_SOURCE_PLUGIN,
        SERVICE_PROC_SOURCE_USER,
        SERVICE_PROC_SOURCE_TRANSIENT,
    }
)

RESERVED_BUILTIN_SERVICE_PROCS: Final = ("gateway", "scheduler")

# Proc ``origin`` values the service subsystem writes. They are host-written
# and independent of the wire ``service`` block, so readers can still classify
# a row when that additive field is missing.
SERVICE_HOST_ORIGIN: Final = "service-host"
SERVICE_ONESHOT_ORIGIN: Final = "service-proc"
# The host also tags (and labels) each daemon row ``service:<name>``.
SERVICE_HOST_TAG_PREFIX: Final = "service:"


@dataclass(frozen=True)
class ProcServiceBlock:
    """The optional service marker on one durable proc row."""

    name: str | None
    mode: str
    source: str

    @classmethod
    def from_dict(cls, data: object) -> ProcServiceBlock | None:
        if not isinstance(data, Mapping):
            return None
        name = data.get("name")
        return cls(
            name=None if name is None else str(name),
            mode=str(data.get("mode") or ""),
            source=str(data.get("source") or ""),
        )

    @property
    def is_named(self) -> bool:
        return bool(self.name)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "source": self.source,
        }
        if self.name is not None:
            payload["name"] = self.name
        return payload


def host_service_tag_name(values: Iterable[str]) -> str | None:
    """Return ``<name>`` from the first host-written ``service:<name>`` value."""
    for value in values:
        if value.startswith(SERVICE_HOST_TAG_PREFIX):
            name = value[len(SERVICE_HOST_TAG_PREFIX) :]
            if name:
                return name
    return None


__all__ = [
    "RESERVED_BUILTIN_SERVICE_PROCS",
    "SERVICE_HOST_ORIGIN",
    "SERVICE_HOST_TAG_PREFIX",
    "SERVICE_ONESHOT_ORIGIN",
    "SERVICE_PROC_MODE_DAEMON",
    "SERVICE_PROC_MODE_ONESHOT",
    "SERVICE_PROC_MODES",
    "SERVICE_PROC_SOURCE_BUILTIN",
    "SERVICE_PROC_SOURCE_PLUGIN",
    "SERVICE_PROC_SOURCE_TRANSIENT",
    "SERVICE_PROC_SOURCE_USER",
    "SERVICE_PROC_SOURCES",
    "ProcServiceBlock",
    "host_service_tag_name",
]
