"""Frozen observation and row models for the instruction scoreboard."""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SessionObservation:
    """One provider session's observed instruction loads."""

    provider: str
    run_name: str
    session_id: str
    contract_count: int
    # Tri-state layer presence: True/False, or None when unverifiable.
    home: bool | None = None
    project: bool | None = None
    directive: bool | None = None
    native_full_count: int = 0
    # Provider-specific foreign-load signal (auto-memory, memory flag, ...).
    foreign: str | None = None
    helper_type: str | None = None
    has_helper_template: bool = False
    final_attempts: int = 0
    final_denied: int = 0
    final_accepted: int = 0
    root_guard_denial: bool = False
    partial: bool = False


@dataclass(frozen=True)
class ProviderRow:
    """One scoreboard table row aggregating a provider's observations."""

    provider: str
    runs: int = 0
    sessions: int = 0
    contract: str = "0"
    home: str = "◌"
    project: str = "◌"
    directive: str = "◌"
    native_full: str = "0"
    foreign: str = "—"
    helpers: str = "—"
    root_denials: int = 0
    coverage: str = "0/0"


@dataclass(frozen=True)
class VerifyReport:
    """Full ``sase instructions verify`` result."""

    provider_rows: tuple[ProviderRow, ...] = ()
    observations: tuple[SessionObservation, ...] = field(default_factory=tuple)
    filters: dict[str, object] = field(default_factory=dict)
    generated_at: str = ""

    def to_json_dict(self, *, include_observations: bool) -> dict[str, object]:
        """Return the stable ``-j`` JSON document."""
        rows = [
            {
                "provider": row.provider,
                "runs": row.runs,
                "sessions": row.sessions,
                "contract": row.contract,
                "home": row.home,
                "project": row.project,
                "directive": row.directive,
                "native_full": row.native_full,
                "foreign": row.foreign,
                "helpers": row.helpers,
                "root_denials": row.root_denials,
                "coverage": row.coverage,
            }
            for row in self.provider_rows
        ]
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "filters": dict(self.filters),
            "providers": rows,
        }
        if include_observations:
            payload["observations"] = [
                {
                    "provider": obs.provider,
                    "run": obs.run_name,
                    "session": obs.session_id,
                    "contract_count": obs.contract_count,
                    "home": obs.home,
                    "project": obs.project,
                    "directive": obs.directive,
                    "native_full_count": obs.native_full_count,
                    "foreign": obs.foreign,
                    "helper_type": obs.helper_type,
                    "has_helper_template": obs.has_helper_template,
                    "final_attempts": obs.final_attempts,
                    "final_denied": obs.final_denied,
                    "final_accepted": obs.final_accepted,
                    "root_guard_denial": obs.root_guard_denial,
                    "partial": obs.partial,
                }
                for obs in self.observations
            ]
        return payload


__all__ = [
    "SCHEMA_VERSION",
    "ProviderRow",
    "SessionObservation",
    "VerifyReport",
]
