"""Guide view construction for the ACE Help panel."""

from __future__ import annotations

from textual.containers import VerticalScroll

from ...keymaps import KeymapRegistry
from ...widgets import AgentOnboarding, AxeOnboarding, PatchOnboarding
from .binding_common import TabName


def build_guide_view(
    *,
    current_tab: TabName,
    registry: KeymapRegistry,
    agents_launch_targets_available: bool = False,
    agents_plugins_installed: bool = True,
) -> VerticalScroll:
    """Build a fresh onboarding guide widget for the selected app tab."""
    if current_tab == "artifacts":
        patches_guide = PatchOnboarding(classes="help-guide-content")
        patches_guide.set_keymap_registry(registry)
        return patches_guide
    if current_tab == "agents":
        agents_guide = AgentOnboarding(classes="help-guide-content")
        agents_guide.set_launch_targets_available(
            agents_launch_targets_available,
            refresh=False,
        )
        agents_guide.set_plugins_installed(agents_plugins_installed)
        agents_guide.set_keymap_registry(registry)
        return agents_guide

    axe_guide = AxeOnboarding(classes="help-guide-content")
    axe_guide.set_keymap_registry(registry)
    return axe_guide
