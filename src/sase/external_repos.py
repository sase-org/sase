"""Pure domain helpers for workspace-local external repositories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

DEFAULT_EXTERNAL_REPO_SCHEME = "gh"
EXTERNAL_PROJECTS_NAMESPACE = "projects"

_SCHEME_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*", re.IGNORECASE)


class ExternalRepoRefError(ValueError):
    """Raised when an external provider reference is malformed."""


@dataclass(frozen=True)
class ExternalRepoRef:
    """A canonical provider-owned external repository reference."""

    scheme: str
    owner: str
    repo: str

    @property
    def ref(self) -> str:
        """Return the provider-local ``owner/repo`` reference."""

        return f"{self.owner}/{self.repo}"

    @property
    def canonical_name(self) -> str:
        """Return the stable name used by inventory, logs, and markers."""

        return f"{self.scheme}:{self.ref}"

    @property
    def clone_parts(self) -> tuple[str, str, str]:
        """Return the path components below ``sase/repos/external``."""

        return (self.scheme, self.owner, self.repo)


def parse_external_repo_ref(
    value: str,
    *,
    default_scheme: str = DEFAULT_EXTERNAL_REPO_SCHEME,
) -> ExternalRepoRef:
    """Parse ``scheme:owner/repo`` or bare ``owner/repo`` shorthand."""

    candidate = value.strip()
    if not candidate:
        raise ExternalRepoRefError("external repo reference must not be empty")

    if ":" in candidate:
        scheme, separator, provider_ref = candidate.partition(":")
        if not separator:
            raise ExternalRepoRefError(
                f"invalid external repo reference {value!r}; expected scheme:owner/repo"
            )
    else:
        scheme = default_scheme
        provider_ref = candidate

    normalized_scheme = scheme.strip().lower()
    if not _SCHEME_PATTERN.fullmatch(normalized_scheme):
        raise ExternalRepoRefError(f"invalid external repo scheme {scheme!r}")

    parts = provider_ref.split("/")
    if len(parts) != 2 or any(not _valid_clone_component(part) for part in parts):
        raise ExternalRepoRefError(
            f"invalid external repo reference {value!r}; expected scheme:owner/repo"
        )
    return ExternalRepoRef(normalized_scheme, parts[0], parts[1])


def external_repo_clone_parts_from_name(name: str) -> tuple[str, ...]:
    """Map a canonical external display name to reversible clone components.

    Provider refs map to ``(<scheme>, <owner>, <repo>)``. A bare project name
    maps to ``("projects", <name>)``.
    """

    candidate = name.strip()
    if ":" in candidate or "/" in candidate:
        return parse_external_repo_ref(candidate).clone_parts
    if not _valid_clone_component(candidate):
        raise ExternalRepoRefError(f"invalid external project name {name!r}")
    return (EXTERNAL_PROJECTS_NAMESPACE, candidate)


def _external_repo_ref_from_clone_parts(
    parts: Sequence[str],
) -> ExternalRepoRef | None:
    """Reverse provider clone components, returning ``None`` when invalid."""

    values = tuple(parts)
    if len(values) != 3 or values[0] == EXTERNAL_PROJECTS_NAMESPACE:
        return None
    try:
        return parse_external_repo_ref(f"{values[0]}:{values[1]}/{values[2]}")
    except ExternalRepoRefError:
        return None


def external_repo_name_from_clone_parts(parts: Sequence[str]) -> str | None:
    """Reverse clone components into their canonical inventory display name."""

    values = tuple(parts)
    if len(values) == 2 and values[0] == EXTERNAL_PROJECTS_NAMESPACE:
        return values[1] if _valid_clone_component(values[1]) else None
    parsed = _external_repo_ref_from_clone_parts(values)
    return parsed.canonical_name if parsed is not None else None


def _valid_clone_component(value: str) -> bool:
    return bool(
        value
        and value not in {".", ".."}
        and value == value.strip()
        and not any(
            char.isspace() or char in {"/", "\\", ":", "\x00"} for char in value
        )
    )


__all__ = [
    "DEFAULT_EXTERNAL_REPO_SCHEME",
    "EXTERNAL_PROJECTS_NAMESPACE",
    "ExternalRepoRef",
    "ExternalRepoRefError",
    "external_repo_clone_parts_from_name",
    "external_repo_name_from_clone_parts",
    "parse_external_repo_ref",
]
