"""Handler for ``sase project suggest`` (onboarding discovery without writes)."""

from __future__ import annotations

import argparse
import sys

from sase import workspace_provider
from sase.project_onboarding.discovery import suggest
from sase.project_onboarding.render import print_suggest, render_suggest_json


def _known_providers() -> list[str]:
    """Return registered workspace provider types in metadata order."""

    try:
        return [
            metadata.workflow_type
            for metadata in workspace_provider.get_all_workflow_metadata()
        ]
    except Exception:
        return []


def handle_suggest(args: argparse.Namespace) -> int:
    """Rank likely repositories per provider without creating anything."""

    provider = getattr(args, "provider", None)
    known = _known_providers()
    if isinstance(provider, str) and provider and provider not in known:
        expected = ", ".join(known) if known else "no registered providers"
        print(
            f"unknown provider {provider!r} (expected one of: {expected})",
            file=sys.stderr,
        )
        return 2
    try:
        payload = suggest(
            providers=[provider] if isinstance(provider, str) and provider else None,
            include_hidden=bool(getattr(args, "all", False)),
            owners=getattr(args, "owner", None),
            refresh=bool(getattr(args, "refresh", False)),
        )
    except Exception as exc:
        print(f"sase project suggest failed: {exc}", file=sys.stderr)
        return 1
    if bool(getattr(args, "json", False)):
        print(render_suggest_json(payload))
    else:
        print_suggest(payload, include_hidden=bool(getattr(args, "all", False)))
    if isinstance(provider, str) and provider:
        try:
            from sase.project_onboarding.preferences import (
                record_provider_selection,
            )

            record_provider_selection(provider)
        except Exception:
            pass
    return 0


__all__ = ["handle_suggest"]
