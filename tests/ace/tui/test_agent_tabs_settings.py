"""Agent tabs settings parser, view config, and config parity coverage."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.ace.tui import agent_tabs_settings as settings
from sase.ace.tui.agent_tabs_settings import (
    DEFAULT_AGENT_TABS_SETTINGS,
    AgentTabsSettings,
    _AgentTabStyle,
    agent_tabs_view_config,
    parse_agent_tabs_settings,
)
from sase.dispatch.models import DispatchConfig, MachineRecord, ProviderSettings
from tests._config_schema_helpers import REPO_ROOT, schema


@pytest.fixture(autouse=True)
def _clear_view_cache() -> Iterator[None]:
    settings._agent_tabs_view_config_for_token.cache_clear()
    yield
    settings._agent_tabs_view_config_for_token.cache_clear()


def _machine(alias: str, installation_id: str) -> MachineRecord:
    return MachineRecord(
        alias=alias,
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref=f"fleet:{alias}",
        pinned_installation_id=installation_id,
    )


def _dispatch(*machines: MachineRecord) -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True)
        },
        machines=machines,
        request_timeout_seconds=5.0,
    )


def _install_view_config(
    monkeypatch: pytest.MonkeyPatch,
    ace_tabs: dict[str, Any],
    machines: tuple[MachineRecord, ...] = (),
    *,
    token: tuple[Any, ...] = ("config", 1),
    local_name: str = "",
) -> None:
    import sase.config as config_mod

    monkeypatch.setattr(
        settings, "load_merged_config", lambda: {"ace": {"agent_tabs": ace_tabs}}
    )
    monkeypatch.setattr(
        settings, "load_dispatch_config", lambda config: _dispatch(*machines)
    )
    monkeypatch.setattr(settings, "current_config_token", lambda: token)
    monkeypatch.setattr(config_mod, "get_local_machine_name", lambda: local_name)


def test_defaults() -> None:
    assert DEFAULT_AGENT_TABS_SETTINGS.machine_tabs == "auto"
    assert DEFAULT_AGENT_TABS_SETTINGS.launch_from_view is True
    assert DEFAULT_AGENT_TABS_SETTINGS.tabs == {}


def test_missing_or_malformed_blocks_use_the_default() -> None:
    assert parse_agent_tabs_settings({}) == DEFAULT_AGENT_TABS_SETTINGS
    assert parse_agent_tabs_settings(None) == DEFAULT_AGENT_TABS_SETTINGS
    assert parse_agent_tabs_settings("nope") == DEFAULT_AGENT_TABS_SETTINGS
    assert (
        parse_agent_tabs_settings({"agent_tabs": True}) == DEFAULT_AGENT_TABS_SETTINGS
    )
    assert parse_agent_tabs_settings({"agent_tabs": {}}) == DEFAULT_AGENT_TABS_SETTINGS


@pytest.mark.parametrize("value", ["on", "off", "auto"])
def test_machine_tabs_modes(value: str) -> None:
    parsed = parse_agent_tabs_settings({"agent_tabs": {"machine_tabs": value}})
    assert parsed.machine_tabs == value


@pytest.mark.parametrize("value", ["ON", "yes", True, 1, None, [], {}, "sometimes"])
def test_invalid_machine_tabs_falls_back_to_auto(value: object) -> None:
    parsed = parse_agent_tabs_settings({"agent_tabs": {"machine_tabs": value}})
    assert parsed.machine_tabs == "auto"


@pytest.mark.parametrize("value", [True, False])
def test_launch_from_view_booleans(value: bool) -> None:
    parsed = parse_agent_tabs_settings({"agent_tabs": {"launch_from_view": value}})
    assert parsed.launch_from_view is value


@pytest.mark.parametrize("value", ["yes", 1, 0, None, [], {}])
def test_non_boolean_launch_from_view_falls_back_to_true(value: object) -> None:
    parsed = parse_agent_tabs_settings({"agent_tabs": {"launch_from_view": value}})
    assert parsed.launch_from_view is True


def test_tab_names_canonicalize_and_invalid_names_drop() -> None:
    parsed = parse_agent_tabs_settings(
        {
            "agent_tabs": {
                "tabs": {
                    "Sase": {"order": 2, "color": "#AF87FF"},
                    "  Blog  ": {"icon": "◈"},
                    "not a tab": {"order": 1},
                    "": {"order": 3},
                    "main": {"order": 0},
                    42: {"order": 4},
                }
            }
        }
    )
    assert set(parsed.tabs) == {"sase", "blog"}
    assert parsed.tabs["sase"] == _AgentTabStyle(
        color="#AF87FF", icon="", order=2, description=""
    )
    assert parsed.tabs["blog"] == _AgentTabStyle(
        color="", icon="◈", order=None, description=""
    )


def test_non_mapping_styles_and_orders_drop_or_default() -> None:
    parsed = parse_agent_tabs_settings(
        {
            "agent_tabs": {
                "tabs": {
                    "sase": "not a mapping",
                    "blog": {"order": True},
                    "docs": {"order": "first"},
                    "ops": {"order": -1, "description": "  Ops work.  "},
                }
            }
        }
    )
    assert set(parsed.tabs) == {"blog", "docs", "ops"}
    assert parsed.tabs["blog"].order is None
    assert parsed.tabs["docs"].order is None
    assert parsed.tabs["ops"].order == -1
    assert parsed.tabs["ops"].description == "Ops work."


def test_non_mapping_tabs_block_keeps_other_fields() -> None:
    parsed = parse_agent_tabs_settings(
        {"agent_tabs": {"machine_tabs": "off", "tabs": ["sase"]}}
    )
    assert parsed == AgentTabsSettings(
        machine_tabs="off", launch_from_view=True, tabs={}
    )


def test_machine_mode_on_off_and_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    apollo = _machine("apollo", "install-apollo")
    _install_view_config(monkeypatch, {}, (), token=("t", 1))
    assert agent_tabs_view_config().machine_mode is False
    _install_view_config(monkeypatch, {}, (apollo,), token=("t", 2))
    assert agent_tabs_view_config().machine_mode is True
    _install_view_config(monkeypatch, {"machine_tabs": "on"}, (), token=("t", 3))
    assert agent_tabs_view_config().machine_mode is True
    _install_view_config(
        monkeypatch, {"machine_tabs": "off"}, (apollo,), token=("t", 4)
    )
    assert agent_tabs_view_config().machine_mode is False


def test_machine_order_skips_records_without_pinned_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apollo = _machine("apollo", "install-apollo")
    bare = MachineRecord(
        alias="bare",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref="fleet:bare",
        pinned_installation_id="",
    )
    _install_view_config(monkeypatch, {}, (apollo, bare))
    view = agent_tabs_view_config()
    assert view.machine_order == (("install-apollo", "apollo"),)
    assert view.pinned_by_alias == {"apollo": "install-apollo"}
    assert view.token[0] is True


def test_named_order_comes_from_tab_styles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_view_config(
        monkeypatch,
        {"tabs": {"sase": {"order": 3}, "blog": {}}},
    )
    view = agent_tabs_view_config()
    assert view.named_order == {"sase": 3}
    assert view.token[0] is False


def test_view_config_is_cached_per_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_view_config(monkeypatch, {}, (), token=("t", 1))
    first = agent_tabs_view_config()
    second = agent_tabs_view_config()
    assert first is second
    _install_view_config(monkeypatch, {}, (), token=("t", 2))
    assert agent_tabs_view_config() is not first


def test_config_schema_agent_tabs_parity() -> None:
    public_schema = schema()
    validator = Draft7Validator(public_schema)
    agent_tabs = public_schema["properties"]["ace"]["properties"]["agent_tabs"]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    assert default_config["ace"]["agent_tabs"] == {
        "machine_tabs": "auto",
        "launch_from_view": True,
        "tabs": {},
    }
    assert agent_tabs["additionalProperties"] is False
    assert agent_tabs["properties"]["machine_tabs"]["default"] == "auto"
    assert agent_tabs["properties"]["launch_from_view"]["default"] is True
    for valid in (
        {"machine_tabs": "auto"},
        {"machine_tabs": "on"},
        {"machine_tabs": "off"},
        {"launch_from_view": False},
        {"tabs": {"sase": {"order": 1}}},
    ):
        validator.validate({"ace": {"agent_tabs": valid}})
    for invalid in (
        {"machine_tabs": "sometimes"},
        {"machine_tabs": True},
        {"launch_from_view": "yes"},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"agent_tabs": invalid}})


def test_launch_from_view_enabled_reads_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_view_config(monkeypatch, {}, (), token=("lfv", 1))
    assert settings.launch_from_view_enabled() is True
    _install_view_config(monkeypatch, {"launch_from_view": False}, (), token=("lfv", 2))
    assert settings.launch_from_view_enabled() is False


def test_launch_from_view_enabled_falls_back_on_bad_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "load_merged_config", lambda: None)
    assert settings.launch_from_view_enabled() is True


def test_view_config_resolves_local_machine_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_view_config(monkeypatch, {}, (), token=("t", 1), local_name="athena")
    view = agent_tabs_view_config()
    assert view.local_machine_name == "athena"
    assert settings.local_machine_tab_name(view) == "athena"


def test_view_config_token_changes_with_local_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_view_config(monkeypatch, {}, (), token=("t", 1), local_name="athena")
    first = agent_tabs_view_config()
    _install_view_config(monkeypatch, {}, (), token=("t", 2), local_name="apollo")
    second = agent_tabs_view_config()
    assert first.token != second.token
    assert "athena" in first.token
    assert "apollo" in second.token
    assert second.local_machine_name == "apollo"


def test_view_config_local_name_falls_back_on_resolver_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.config as config_mod

    monkeypatch.setattr(
        settings, "load_merged_config", lambda: {"ace": {"agent_tabs": {}}}
    )
    monkeypatch.setattr(settings, "load_dispatch_config", lambda config: _dispatch())
    monkeypatch.setattr(settings, "current_config_token", lambda: ("t", 9))

    def _boom() -> str:
        raise RuntimeError("no identity")

    monkeypatch.setattr(config_mod, "get_local_machine_name", _boom)
    view = agent_tabs_view_config()
    assert view.local_machine_name == ""
    assert settings.local_machine_tab_name(view) == "local"
    assert settings.local_machine_tab_name(None) == "local"
