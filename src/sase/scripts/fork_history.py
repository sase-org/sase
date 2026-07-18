"""Render the typed history sources resolved for the ``#fork`` workflow."""

import json
from collections.abc import Mapping, Sequence

from sase.history.chat import build_fork_injected_history


def main(sources: Sequence[Mapping[str, object]]) -> None:
    """Print the injected fork history as workflow-step JSON output."""
    injected_history = build_fork_injected_history(sources)
    print(json.dumps({"injected_history": injected_history}))
