"""Compatibility facade for agent detail and info-panel display helpers."""

from __future__ import annotations

from ._display_detail_footer import AgentFooterDisplayMixin
from ._display_detail_info import AgentInfoDisplayMixin
from ._display_detail_onboarding import AgentsOnboardingMixin
from ._display_detail_render import AgentDetailRenderMixin


class DetailMixin(
    AgentDetailRenderMixin,
    AgentsOnboardingMixin,
    AgentFooterDisplayMixin,
    AgentInfoDisplayMixin,
):
    """Aggregate agent detail, onboarding, footer, and info-panel helpers."""


__all__ = ["DetailMixin"]
