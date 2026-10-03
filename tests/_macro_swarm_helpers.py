from __future__ import annotations

import re
from unittest.mock import patch

from sase.agent.macro_swarm import expand_macro_swarms_with_metadata
from sase.macro.models import InputArg, Macro


def expand_macro_swarms(segments: list[str], **kwargs) -> list[str]:
    return [
        segment.prompt
        for segment in expand_macro_swarms_with_metadata(segments, **kwargs)
    ]


def xp(name: str, content: str, *, inputs: list[InputArg] | None = None) -> Macro:
    return Macro(name=name, content=content, inputs=inputs or [])


def patch_catalog(catalog: dict[str, Macro]):
    """Patch ``get_all_macros`` in both the helper and the inline expander."""
    return patch("sase.agent.macro_swarm.get_all_macros", return_value=catalog)


def patch_vcs_patterns():
    return patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value={
            "gh": re.compile(r"#gh(?::([^\s]+)|\(([^)]*)\))"),
            "git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))"),
        },
    )
