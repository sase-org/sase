"""Coverage for the unconditional Admin Center Config hub catalog."""

from __future__ import annotations

from sase.ace.tui.modals.config_center_catalog import (
    _TAB_SPECS,
    validated_center_tab,
)
from sase.ace.tui.modals.config_hub_catalog import (
    CONFIG_SUBTAB_ORDER,
    config_panel_tabs,
    config_subtab_specs,
)
from sase.ace.tui.modals.config_hub_session import (
    config_subtab_order,
    validated_config_subtab,
)
from sase.ace.tui.modals.help_modal.binding_common import admin_center_opener_help_label
from sase.feature_flags import override_flags


def test_catalog_drops_top_level_xprompts_and_maps_legacy_resume() -> None:
    assert tuple(spec.id for spec in _TAB_SPECS) == (
        "config",
        "logs",
        "procs",
        "projects",
        "statistics",
        "updates",
    )
    assert tuple(spec.number for spec in _TAB_SPECS) == tuple(range(1, 7))
    assert "xprompts" not in {spec.id for spec in _TAB_SPECS}
    assert _TAB_SPECS[0].pane_identity == "ConfigHubPane"
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
    assert config_subtab_order() == CONFIG_SUBTAB_ORDER
    assert tuple(spec.id for spec in config_subtab_specs()) == CONFIG_SUBTAB_ORDER
    assert validated_config_subtab("launch") is None


def test_config_launch_subtab_order_when_flag_enabled() -> None:
    with override_flags(admin_center_launch_subtab=True):
        assert config_subtab_order() == (
            "xprompts",
            "snippets",
            "glossary",
            "memory",
            "launch",
            "misc",
        )
        specs = config_subtab_specs()
        assert tuple(spec.id for spec in specs) == config_subtab_order()
        assert tuple(tab.id for tab in config_panel_tabs()) == config_subtab_order()
        launch_spec = next(spec for spec in specs if spec.id == "launch")
        assert launch_spec.label == "Launch"
        assert launch_spec.micro_label == "Run"
        assert validated_config_subtab("launch") == "launch"
