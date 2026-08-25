"""Coverage for the Admin Center Config hub catalog."""

from __future__ import annotations

import ast
from pathlib import Path

from sase.ace.tui.modals.config_center_catalog import (
    _TAB_SPECS,
    validated_center_tab,
)
from sase.ace.tui.modals.config_hub_catalog import (
    CONFIG_SUBTAB_BY_ID,
    CONFIG_SUBTAB_ORDER,
    CONFIG_SUBTAB_SPECS,
    config_panel_tabs,
    config_subtab_description_text,
    config_subtab_specs,
)
from sase.ace.tui.modals.config_hub_session import (
    CONFIG_SUBTAB_ORDER as SESSION_SUBTAB_ORDER,
    CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS,
    config_subtab_order,
    validated_config_subtab,
)
from sase.ace.tui.modals.help_modal.binding_common import admin_center_opener_help_label
from sase.feature_flags import FeatureFlag, override_flags

_ROOT = Path(__file__).resolve().parents[3]
_SESSION_PATH = (
    _ROOT / "src" / "sase" / "ace" / "tui" / "modals" / "config_hub_session.py"
)
_CATALOG_PATH = (
    _ROOT / "src" / "sase" / "ace" / "tui" / "modals" / "config_hub_catalog.py"
)
_CENTER_CATALOG_PATH = (
    _ROOT / "src" / "sase" / "ace" / "tui" / "modals" / "config_center_catalog.py"
)
_REVIEWED_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "misc": (
        "Inspect effective values, source layers, and schema-backed settings.",
        "Inspect effective values, sources, and other settings.",
    ),
    "flags": (
        "Review feature rollouts, effective state, provenance, and saved overrides.",
        "Control feature rollouts and saved overrides.",
    ),
    "launch": (
        "Tune model routing, reasoning effort, runner limits, and launch defaults.",
        "Tune model routing, effort, and launch limits.",
    ),
    "memory": (
        "Browse, edit, and publish the durable context agents receive.",
        "Manage the durable context agents receive.",
    ),
    "snippets": (
        "Build reusable prompt fragments and preview their composed output.",
        "Manage reusable prompt fragments and compositions.",
    ),
    "xprompts": (
        "Browse, preview, create, and edit reusable agent prompts and workflows.",
        "Manage reusable agent prompts and workflows.",
    ),
}


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


def test_registered_catalog_is_alphabetized_with_all_first() -> None:
    assert SESSION_SUBTAB_ORDER == (
        "misc",
        "flags",
        "launch",
        "memory",
        "snippets",
        "xprompts",
    )
    assert CONFIG_SUBTAB_ORDER == SESSION_SUBTAB_ORDER
    assert CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS == (
        "misc",
        "launch",
        "memory",
        "snippets",
        "xprompts",
    )


def test_config_subtab_order_includes_flags_when_rollout_is_on() -> None:
    with override_flags(admin_center_flags=True):
        assert config_subtab_order() == SESSION_SUBTAB_ORDER
        tabs = config_panel_tabs()
        assert tuple(spec.id for spec in config_subtab_specs()) == SESSION_SUBTAB_ORDER
        assert tuple(tab.id for tab in tabs) == SESSION_SUBTAB_ORDER
        assert tuple(tab.shortcut for tab in tabs) == (
            "01",
            "02",
            "03",
            "04",
            "05",
            "06",
        )
        misc_spec = next(spec for spec in config_subtab_specs() if spec.id == "misc")
        assert misc_spec.label == "All"
        assert misc_spec.compact_label == "All"
        assert misc_spec.micro_label == "All"
        flags_spec = next(spec for spec in config_subtab_specs() if spec.id == "flags")
        assert flags_spec.label == "Flags"
        assert flags_spec.micro_label == "Flag"
        assert validated_config_subtab("flags") == "flags"
        launch_spec = next(
            spec for spec in config_subtab_specs() if spec.id == "launch"
        )
        assert launch_spec.label == "Launch"
        assert launch_spec.micro_label == "Run"


def test_registered_specs_carry_reviewed_full_and_compact_copy() -> None:
    assert tuple(spec.id for spec in CONFIG_SUBTAB_SPECS) == tuple(
        _REVIEWED_DESCRIPTIONS
    )
    for spec in CONFIG_SUBTAB_SPECS:
        full, compact = _REVIEWED_DESCRIPTIONS[spec.id]
        assert spec.description == full
        assert spec.compact_description == compact
        assert CONFIG_SUBTAB_BY_ID[spec.id] is spec


def test_active_specs_keep_catalog_derived_description_order() -> None:
    with override_flags(admin_center_flags=True):
        specs = config_subtab_specs()
        assert tuple(spec.id for spec in specs) == SESSION_SUBTAB_ORDER
        assert tuple(
            (spec.description, spec.compact_description) for spec in specs
        ) == tuple(_REVIEWED_DESCRIPTIONS[subtab] for subtab in SESSION_SUBTAB_ORDER)

    with override_flags(admin_center_flags=False):
        specs = config_subtab_specs()
        assert tuple(spec.id for spec in specs) == CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS
        assert "flags" not in {spec.id for spec in specs}
        assert tuple(
            (spec.description, spec.compact_description) for spec in specs
        ) == tuple(
            _REVIEWED_DESCRIPTIONS[subtab]
            for subtab in CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS
        )
        tabs = config_panel_tabs()
        assert tuple(tab.shortcut for tab in tabs) == (
            "01",
            "02",
            "03",
            "04",
            "05",
        )


def test_config_subtab_description_text_uses_cell_width() -> None:
    spec = CONFIG_SUBTAB_BY_ID["flags"]
    full = config_subtab_description_text(spec, width=10_000)
    compact = config_subtab_description_text(spec, width=1)
    assert full.plain == f"› {spec.description}"
    assert compact.plain == f"› {spec.compact_description}"
    assert str(full.style) == "#00D7AF"
    assert str(compact.style) == "#00D7AF"
    assert config_subtab_description_text(spec, width=full.cell_len).plain == (
        full.plain
    )
    assert config_subtab_description_text(spec, width=full.cell_len - 1).plain == (
        compact.plain
    )
    assert config_subtab_description_text(spec, width=0).plain == full.plain


def test_config_subtab_order_omits_flags_when_rollout_is_off() -> None:
    with override_flags(admin_center_flags=False):
        assert config_subtab_order() == CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS
        tabs = config_panel_tabs()
        assert tuple(spec.id for spec in config_subtab_specs()) == (
            CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS
        )
        assert tuple(tab.id for tab in tabs) == CONFIG_SUBTAB_ORDER_WITHOUT_FLAGS
        assert tuple(tab.shortcut for tab in tabs) == (
            "01",
            "02",
            "03",
            "04",
            "05",
        )
        assert validated_config_subtab("flags") is None
        assert validated_config_subtab("memory") == "memory"
        assert validated_config_subtab("launch") == "launch"


def test_config_catalog_does_not_resolve_flags_at_import() -> None:
    for path in (_SESSION_PATH, _CATALOG_PATH, _CENTER_CATALOG_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not _module_calls_current_flags(tree), path


def test_admin_center_flags_call_site_uses_snapshot_enabled() -> None:
    source = _SESSION_PATH.read_text(encoding="utf-8")
    assert "current_flags().enabled(FeatureFlag.admin_center_flags)" in source
    assert FeatureFlag.admin_center_flags == "admin_center_flags"


def _module_calls_current_flags(tree: ast.AST) -> bool:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "current_flags"
            ):
                return True
            if isinstance(child, ast.Name) and child.id == "current_flags":
                parent_calls = [
                    parent
                    for parent in ast.walk(node)
                    if isinstance(parent, ast.Call)
                    and isinstance(parent.func, ast.Name)
                    and parent.func.id == "current_flags"
                ]
                if parent_calls and not _call_is_inside_function(tree, parent_calls[0]):
                    return True
    return False


def _call_is_inside_function(tree: ast.AST, target: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if child is target:
                return True
    return False
