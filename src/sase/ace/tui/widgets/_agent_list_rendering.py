"""Public façade for agent-list row rendering.

Implementation lives in sibling ``_agent_list_render_*`` modules; this
file re-exports the names that callers (and tests) historically import
from ``_agent_list_rendering``:

- ``_agent_list_render_layout`` — shared style constants and layout helpers.
- ``_agent_list_render_cache`` — LRU-backed render cache and key builders.
- ``_agent_list_render_agent`` — agent row formatter (+ cached wrapper).
- ``_agent_list_render_banner`` — group banner formatter (+ cached wrapper).
- ``_agent_list_render_attempt`` — prior-attempt row formatter.
"""

from ._agent_list_render_agent import (
    cached_format_agent_option,
    format_agent_option,
)
from ._agent_list_render_attempt import format_attempt_option
from ._agent_list_render_banner import (
    cached_format_banner_option,
    format_banner_option,
)
from ._agent_list_render_cache import (
    AgentRenderCache,
    agent_render_key,
    banner_render_key,
)
from ._agent_list_render_layout import assemble_padded_option

__all__ = [
    "AgentRenderCache",
    "agent_render_key",
    "assemble_padded_option",
    "banner_render_key",
    "cached_format_agent_option",
    "cached_format_banner_option",
    "format_agent_option",
    "format_attempt_option",
    "format_banner_option",
]
