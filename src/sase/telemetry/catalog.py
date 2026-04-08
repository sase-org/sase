"""Structured metric catalog derived from METRIC_DEFS.

Provides ``MetricInfo`` metadata and ``SUBSYSTEMS`` grouping used by
the ``sase telemetry list`` and ``sase telemetry status`` CLI commands.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.telemetry.metrics import METRIC_DEFS

# Prometheus name prefix → human-readable subsystem name
_PREFIX_TO_SUBSYSTEM: dict[str, str] = {
    "sase_agent": "Agent Lifecycle",
    "sase_llm": "LLM Provider",
    "sase_axe": "Axe Orchestrator",
    "sase_hook": "Hooks / Mentors / Workflows",
    "sase_mentor": "Hooks / Mentors / Workflows",
    "sase_workflow": "Hooks / Mentors / Workflows",
    "sase_zombie": "Hooks / Mentors / Workflows",
    "sase_bead": "Beads",
    "sase_vcs": "VCS / Workspace",
    "sase_workspace": "VCS / Workspace",
    "sase_notifications": "Notifications",
}

# Stable display order for subsystems.
SUBSYSTEM_ORDER: list[str] = [
    "Agent Lifecycle",
    "LLM Provider",
    "Axe Orchestrator",
    "Hooks / Mentors / Workflows",
    "Beads",
    "VCS / Workspace",
    "Notifications",
]


@dataclass(frozen=True)
class MetricInfo:
    """Metadata for a single metric definition."""

    attr: str  # Module attribute name, e.g. "AGENT_RUNS"
    kind: str  # "counter", "gauge", or "histogram"
    prometheus_name: str  # e.g. "sase_agent_runs_total"
    description: str  # Human-readable description
    labels: list[str]  # Label names
    subsystem: str  # e.g. "Agent Lifecycle"


def _derive_subsystem(prometheus_name: str) -> str:
    """Derive subsystem from the Prometheus metric name prefix."""
    for prefix, subsystem in _PREFIX_TO_SUBSYSTEM.items():
        if prometheus_name.startswith(prefix):
            return subsystem
    return "Other"


def get_catalog() -> list[MetricInfo]:
    """Return the full metric catalog as a list of MetricInfo."""
    return [
        MetricInfo(
            attr=attr,
            kind=kind,
            prometheus_name=name,
            description=doc,
            labels=list(labels),
            subsystem=_derive_subsystem(name),
        )
        for attr, kind, name, doc, labels, _ in METRIC_DEFS
    ]


def get_subsystems() -> dict[str, list[MetricInfo]]:
    """Return metrics grouped by subsystem in display order."""
    catalog = get_catalog()
    grouped: dict[str, list[MetricInfo]] = {}
    for info in catalog:
        grouped.setdefault(info.subsystem, []).append(info)
    # Return in stable display order, skipping empty subsystems.
    result: dict[str, list[MetricInfo]] = {}
    for name in SUBSYSTEM_ORDER:
        if name in grouped:
            result[name] = grouped[name]
    # Append any subsystems not in SUBSYSTEM_ORDER (shouldn't happen, but safe).
    for name, metrics in grouped.items():
        if name not in result:
            result[name] = metrics
    return result
