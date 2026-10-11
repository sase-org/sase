"""Provider-neutral repository reference parsing for onboarding flows."""

from __future__ import annotations

from sase import workspace_provider
from sase.workspace_provider._hookspec import ParsedRepoRef


class UserRefError(ValueError):
    """A pasted or typed repository reference could not be resolved."""


def _known_workflow_types() -> list[str]:
    """Return every registered provider workflow type, in metadata order."""

    return [
        metadata.workflow_type
        for metadata in workspace_provider.get_all_workflow_metadata()
    ]


def parse_user_ref(text: str, *, workflow_type: str | None = None) -> ParsedRepoRef:
    """Parse *text* into a provider-canonical repository reference.

    A ``gh:``/``git:`` prefix (any registered ``workflow_type``) selects the
    provider directly. Otherwise every provider's ``ws_parse_repo_ref`` is
    tried and exactly one must match.

    Raises:
        UserRefError: When no provider recognizes the text, or more than one
            does. The messages carry the ``not recognized`` and ``ambiguous —
            prefix with gh: or git:`` verdicts the wizard surfaces.
    """

    raw = text.strip()
    if not raw:
        raise UserRefError(f"not recognized as a repository reference: {text!r}")
    known = _known_workflow_types()
    if workflow_type is not None:
        if workflow_type not in known:
            raise UserRefError(
                f"not recognized as a repository reference: {raw!r} "
                f"(unknown provider {workflow_type!r})"
            )
        candidates = [workflow_type]
    else:
        prefix, sep, _ = raw.partition(":")
        if sep and prefix in known:
            candidates = [prefix]
        else:
            candidates = list(known)
    matches: list[ParsedRepoRef] = []
    for candidate in candidates:
        parsed = workspace_provider.parse_repo_ref(candidate, raw)
        if parsed is not None:
            matches.append(parsed)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UserRefError(f"not recognized as a repository reference: {raw!r}")
    raise UserRefError(
        f"ambiguous repository reference {raw!r} — prefix with gh: or git:"
    )


__all__ = ["UserRefError", "parse_user_ref"]
