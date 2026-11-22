"""``tool_runs.admission``: per-host caps on concurrently executing named tools.

The section uses ordinary merged-config precedence; its intended home is the
machine layer (``sase_<host>.yml``) because the cap is counted host-wide,
across every project. An absent tool, or an absent section, is unlimited.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from sase.config.tools import ToolRunsConfigError

DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS = 3600

_ADMISSION_FIELDS = ("max_concurrent", "max_wait_seconds")


@dataclass(frozen=True)
class _ToolAdmissionPolicy:
    """Validated ``tool_runs.admission`` values."""

    max_concurrent: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )
    max_wait_seconds: int = DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS

    def limit_for(self, tool_name: str | None) -> int | None:
        """Return the cap for *tool_name*, or ``None`` when it is unlimited."""

        if not tool_name:
            return None
        return self.max_concurrent.get(tool_name)


def get_tool_runs_admission_config() -> _ToolAdmissionPolicy:
    """Return the validated ``tool_runs.admission`` policy from merged config.

    Raises :class:`ToolRunsConfigError` naming the offending field when the
    section is malformed. Callers on the run path treat that as fail-open.
    """

    from sase.config.core import load_merged_config

    raw = load_merged_config().get("tool_runs", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ToolRunsConfigError("tool_runs must be a mapping")
    return _parse_tool_runs_admission(raw.get("admission"))


def _parse_tool_runs_admission(section: object) -> _ToolAdmissionPolicy:
    """Validate one raw ``tool_runs.admission`` value."""

    if section is None:
        return _ToolAdmissionPolicy()
    if not isinstance(section, Mapping):
        raise ToolRunsConfigError("tool_runs.admission must be a mapping")
    unknown = sorted(str(key) for key in section if key not in _ADMISSION_FIELDS)
    if unknown:
        raise ToolRunsConfigError(
            "unknown tool_runs.admission field(s): " + ", ".join(unknown)
        )
    return _ToolAdmissionPolicy(
        max_concurrent=MappingProxyType(
            _parse_max_concurrent(section.get("max_concurrent"))
        ),
        max_wait_seconds=_parse_max_wait(section.get("max_wait_seconds")),
    )


def _parse_max_concurrent(value: object) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ToolRunsConfigError(
            "tool_runs.admission.max_concurrent must be a mapping of tool name to limit"
        )
    limits: dict[str, int] = {}
    for name, limit in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ToolRunsConfigError(
                "tool_runs.admission.max_concurrent keys must be nonempty tool names"
            )
        if type(limit) is not int or limit < 1:
            raise ToolRunsConfigError(
                f"tool_runs.admission.max_concurrent.{name.strip()} must be an "
                "integer >= 1"
            )
        limits[name.strip()] = limit
    return limits


def _parse_max_wait(value: object) -> int:
    if value is None:
        return DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS
    if type(value) is not int or value < 0:
        raise ToolRunsConfigError(
            "tool_runs.admission.max_wait_seconds must be an integer >= 0"
        )
    return value


__all__ = [
    "DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS",
    "get_tool_runs_admission_config",
]
