"""Backward-compat shim — use ``sase.agent.multi_prompt`` instead."""

from sase.agent.multi_prompt import (  # noqa: F401
    MultiPrompt,
    is_multi_prompt,
    parse_multi_prompt,
)
