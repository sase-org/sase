"""CLI entry point for named-agent chat source resolution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from sase.scripts._agent_chat_from_name_sources import resolve_agent_chat_sources


def main(argv: Sequence[str] | None = None) -> int:
    """Print resolved fork-source metadata as JSON."""
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
