"""Resolve chat transcript source metadata for ``#fork`` workflows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from sase.scripts._agent_chat_from_name_models import (
    ForkClanMemberSource,
    ForkExcludedFamilyMember,
    ForkFailure,
    ForkFamilyMemberSource,
    ForkSource,
)
from sase.scripts._agent_chat_from_name_resume import resolve_agent_chat_path
from sase.scripts._agent_chat_from_name_sources import resolve_agent_chat_sources

_ForkClanMemberSource = ForkClanMemberSource
_ForkExcludedFamilyMember = ForkExcludedFamilyMember
_ForkFailure = ForkFailure
_ForkFamilyMemberSource = ForkFamilyMemberSource
_ForkSource = ForkSource
_resolve_agent_chat_path = resolve_agent_chat_path
_resolve_agent_chat_sources = resolve_agent_chat_sources

__all__ = [
    "_ForkClanMemberSource",
    "_ForkExcludedFamilyMember",
    "_ForkFailure",
    "_ForkFamilyMemberSource",
    "_ForkSource",
    "_resolve_agent_chat_path",
    "_resolve_agent_chat_sources",
    "main",
]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point that prints resolved source metadata as JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="*")
    args = parser.parse_args(argv)
    sources = resolve_agent_chat_sources(args.name)
    source_data = [source.to_json_data() for source in sources]
    print(
        json.dumps(
            {
                # Keep the historical single-path field for compatibility.
                # Transcript-less failed parents intentionally report "" here;
                # the fork workflow consumes sources_json for typed context.
                "path": sources[0].path,
                "sources_json": json.dumps(source_data),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
