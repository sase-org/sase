from __future__ import annotations

import re
from unittest.mock import patch

from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
from sase.xprompt.models import InputArg, XPrompt


def expand_xprompt_swarms(segments: list[str], **kwargs) -> list[str]:
    return [
        segment.prompt
        for segment in expand_xprompt_swarms_with_metadata(segments, **kwargs)
    ]


def xp(name: str, content: str, *, inputs: list[InputArg] | None = None) -> XPrompt:
    return XPrompt(name=name, content=content, inputs=inputs or [])


def patch_catalog(catalog: dict[str, XPrompt]):
    """Patch ``get_all_xprompts`` in both the helper and the inline expander."""
    return patch("sase.agent.xprompt_swarm.get_all_xprompts", return_value=catalog)


def patch_vcs_patterns():
    return patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value={
            "gh": re.compile(r"#gh(?::([^\s]+)|\(([^)]*)\))"),
            "git": re.compile(r"#git(?::([^\s]+)|\(([^)]*)\))"),
        },
    )
