"""Host-set instruction facts and their closed vocabulary (E2 decision 4).

The host sets facts; project content cannot set or override them, and cannot
select a lifecycle section for the wrong actor. Python validates ``provider``
against :func:`registered_provider_names`; the Rust wire validates only its
identifier shape.
"""

from __future__ import annotations

import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Fact names set by the host (decision 4).
FACT_NAMES = (
    "actor",
    "mode",
    "purpose",
    "provider",
    "project",
    "host",
    "vcs",
)

#: Closed ``actor`` vocabulary.
ACTORS = ("sase_root", "native_helper", "interactive")

#: Closed ``mode`` vocabulary.
MODES = ("runtime", "interactive", "export")

#: Closed ``purpose`` vocabulary.
PURPOSES = ("ordinary", "declaration_recovery", "conflict_repair")

#: Valid (actor, mode) combinations (decision 4).
_VALID_COMBINATIONS = frozenset(
    {
        ("sase_root", "runtime"),
        ("native_helper", "runtime"),
        ("interactive", "interactive"),
        ("interactive", "export"),
    }
)


class InstructionFactsError(ValueError):
    """Raised when instruction facts fail Python-side validation."""


@dataclass(frozen=True)
class InstructionFacts:
    """Host-set facts selecting one instruction bundle render."""

    actor: str = "sase_root"
    mode: str = "runtime"
    purpose: str = "ordinary"
    provider: str = ""
    project: str | None = None
    host: str = ""
    vcs: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the wire-shaped facts mapping."""
        return {
            "actor": self.actor,
            "mode": self.mode,
            "purpose": self.purpose,
            "provider": self.provider,
            "project": self.project,
            "host": self.host,
            "vcs": self.vcs,
        }


def _check_value(name: str, value: str, valid: tuple[str, ...]) -> None:
    if value not in valid:
        choices = ", ".join(valid)
        raise InstructionFactsError(
            f"invalid fact {name}={value!r}; valid values: {choices}"
        )


def _check_combination(actor: str, mode: str) -> None:
    if (actor, mode) not in _VALID_COMBINATIONS:
        raise InstructionFactsError(
            f"invalid fact combination: actor {actor!r} with mode {mode!r}; "
            "mode=runtime requires actor 'sase_root' or 'native_helper', "
            "mode=interactive and mode=export require actor 'interactive'"
        )


def registered_names() -> tuple[str, ...]:
    """Return all registered execution provider names.

    Reads ``importlib.metadata`` entry points (group ``sase_llm``) directly —
    the same source the provider registry builds on — so fact validation
    stays import-light and the render-cache hit path never pulls in the
    registry's heavier transitive modules.
    """
    import importlib.metadata

    try:
        points = importlib.metadata.entry_points(group="sase_llm")
    except Exception:
        return ()
    return tuple(sorted({point.name for point in points}))


def parse_facts(facts: Mapping[str, Any]) -> InstructionFacts:
    """Parse and validate a facts mapping into :class:`InstructionFacts`.

    Rejects unknown keys and unknown values, naming the valid choices, and
    rejects lifecycle-invalid actor/mode combinations. ``project`` and
    ``vcs`` may be null; every other fact must be a non-empty string.
    """
    unknown = sorted(set(facts) - set(FACT_NAMES))
    if unknown:
        raise InstructionFactsError(
            f"unknown fact(s) {', '.join(unknown)}; "
            f"valid facts: {', '.join(FACT_NAMES)}"
        )
    actor = facts.get("actor", "sase_root")
    mode = facts.get("mode", "runtime")
    purpose = facts.get("purpose", "ordinary")
    provider = facts.get("provider", "")
    project = facts.get("project")
    host = facts.get("host", "")
    vcs = facts.get("vcs")
    for name, value, valid in (
        ("actor", actor, ACTORS),
        ("mode", mode, MODES),
        ("purpose", purpose, PURPOSES),
    ):
        if not isinstance(value, str) or not value:
            raise InstructionFactsError(f"fact {name} must be a non-empty string")
        _check_value(name, value, valid)
    if not isinstance(provider, str) or not provider:
        raise InstructionFactsError("fact provider must be a non-empty string")
    if provider not in registered_names():
        raise InstructionFactsError(
            f"invalid fact provider={provider!r}; "
            f"valid values: {', '.join(registered_names())}"
        )
    if project is not None and (not isinstance(project, str) or not project):
        raise InstructionFactsError("fact project must be a non-empty string or null")
    if not isinstance(host, str) or not host:
        raise InstructionFactsError("fact host must be a non-empty string")
    if vcs is not None and (not isinstance(vcs, str) or not vcs):
        raise InstructionFactsError("fact vcs must be a non-empty string or null")
    _check_combination(actor, mode)
    return InstructionFacts(
        actor=actor,
        mode=mode,
        purpose=purpose,
        provider=provider,
        project=project,
        host=host,
        vcs=vcs,
    )


def _default_provider() -> str:
    """Return the configured default execution provider name."""
    try:
        from sase.llm_provider.model_launch_settings import (
            resolve_default_launch_provider_model,
        )

        provider, _model = resolve_default_launch_provider_model()
        if provider:
            return provider
    except Exception:
        pass
    names = registered_names()
    if not names:
        raise InstructionFactsError("no registered execution providers")
    return names[0]


def _detect_host() -> str:
    """Return the short hostname for the ``host`` fact."""
    return socket.gethostname().split(".", 1)[0] or "unknown"


def detect_vcs(root: Path) -> str | None:
    """Return the VCS provider name for *root*, or null when undetected."""
    try:
        from sase.vcs_provider._registry import detect_vcs as _detect_vcs

        return _detect_vcs(str(root))
    except Exception:
        return None


def detect_project(root: Path) -> str:
    """Return the project memory name for *root*."""
    from sase.main.init_memory.config import project_memory_name

    return project_memory_name(root)


def default_facts(
    project_root: Path | str,
    *,
    provider: str | None = None,
    purpose: str = "ordinary",
    project: str | None = None,
    detect_project_name: bool = True,
    vcs: str | None = None,
    detect_vcs_name: bool = True,
) -> InstructionFacts:
    """Return root-render facts with host-detected defaults for *project_root*.

    Defaults are ``sase_root``/``runtime``/``ordinary``, the configured
    default provider, the detected project memory name, the short hostname,
    and the detected VCS provider. Pass ``detect_project_name=False`` with
    ``project=None`` outside a project, or explicit values to override.
    """
    root = Path(project_root)
    resolved_project = project
    if resolved_project is None and detect_project_name:
        resolved_project = detect_project(root)
    resolved_vcs = vcs
    if resolved_vcs is None and detect_vcs_name:
        resolved_vcs = detect_vcs(root)
    return parse_facts(
        {
            "actor": "sase_root",
            "mode": "runtime",
            "purpose": purpose,
            "provider": provider or _default_provider(),
            "project": resolved_project,
            "host": _detect_host(),
            "vcs": resolved_vcs,
        }
    )


__all__ = [
    "ACTORS",
    "FACT_NAMES",
    "MODES",
    "PURPOSES",
    "InstructionFacts",
    "InstructionFactsError",
    "default_facts",
    "_default_provider",
    "_detect_host",
    "detect_project",
    "detect_vcs",
    "parse_facts",
    "registered_names",
]
