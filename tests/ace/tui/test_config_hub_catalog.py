"""Both-states coverage for the Admin Center Config hub catalog."""

from __future__ import annotations

from sase.ace.tui.modals.config_center_catalog import (
    _HUB_TAB_SPECS,
    _TAB_SPECS,
    active_tab_specs,
    config_hub_enabled,
    validated_center_tab,
)
from sase.ace.tui.modals.config_hub_catalog import CONFIG_SUBTAB_ORDER
from sase.ace.tui.modals.help_modal.binding_common import admin_center_opener_help_label
from sase.feature_flags import FeatureFlag, current_flags, override_flags


def test_disabled_catalog_keeps_seven_tabs_including_xprompts() -> None:
    with override_flags(admin_center_config_hub=False):
        assert config_hub_enabled() is False
        assert current_flags().enabled(FeatureFlag.admin_center_config_hub) is False
        specs = active_tab_specs()
        assert tuple(spec.id for spec in specs) == (
            "config",
            "logs",
            "procs",
            "projects",
            "statistics",
            "updates",
            "xprompts",
        )
        assert specs is _TAB_SPECS
        assert validated_center_tab("xprompts") == "xprompts"
        assert admin_center_opener_help_label() == "Admin Center: 1-7 jump, # back"


def test_enabled_catalog_drops_top_level_xprompts_and_maps_legacy_resume() -> None:
    with override_flags(admin_center_config_hub=True):
        assert config_hub_enabled() is True
        assert current_flags().enabled(FeatureFlag.admin_center_config_hub) is True
        specs = active_tab_specs()
        assert tuple(spec.id for spec in specs) == (
            "config",
            "logs",
            "procs",
            "projects",
            "statistics",
            "updates",
        )
        assert tuple(spec.number for spec in specs) == tuple(range(1, 7))
        assert specs is _HUB_TAB_SPECS
        assert "xprompts" not in {spec.id for spec in specs}
        assert specs[0].pane_identity == "ConfigHubPane"
        assert validated_center_tab("xprompts") == "config"
        assert validated_center_tab("config") == "config"
        assert validated_center_tab("missing") is None
        assert admin_center_opener_help_label() == "Admin Center: 1-6 jump, # back"


def test_config_subtab_order_matches_the_design() -> None:
    assert CONFIG_SUBTAB_ORDER == (
        "xprompts",
        "snippets",
        "glossary",
        "memory",
        "misc",
    )
