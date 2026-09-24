"""Version-label parity tests for the plugins-browser row model."""

from __future__ import annotations

from sase.ace.tui.modals.plugins_browser_rows import (
    _core_version_label,
    _agent_cli_version_label,
    _plugin_version_label,
    dev_state_label,
)
from sase.agent_clis.models import (
    AgentCliStatus,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from tests.ace.tui._plugins_browser_rows_helpers import (
    _core_package,
    _entry,
    _not_installed_cli_status,
    _ready_cli_status,
)


# -- version_label parity with today's renderers -------------------------------


def test_plugin_version_label_installed_with_update() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.1.0", source="index"),
    )
    assert _plugin_version_label(entry) == "v1.0.0 → v1.1.0"


def test_plugin_version_label_installed_no_update() -> None:
    entry = _entry(
        "telegram",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(checked=True, version="0.5.0", source="index"),
    )
    assert _plugin_version_label(entry) == "v0.5.0"


def test_plugin_version_label_not_installed_with_latest() -> None:
    entry = _entry(
        "nvim", latest=LatestInfo(checked=True, version="2.0.0", source="index")
    )
    assert _plugin_version_label(entry) == "latest v2.0.0"


def test_plugin_version_label_not_installed_unknown() -> None:
    assert _plugin_version_label(_entry("nvim")) == ""


def test_plugin_version_label_git_source() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, source="git"),
    )
    assert _plugin_version_label(entry) == "git"


def test_plugin_version_label_editable_with_update() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(
            checked=True,
            source="editable",
            current_version="1.0.0",
            version="1.1.0",
            update_available=True,
        ),
    )
    assert _plugin_version_label(entry) == "v1.0.0 → v1.1.0  dev"


def test_plugin_version_label_editable_current_state() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(
            checked=True,
            source="editable",
            current_version="1.0.0",
            state="dirty",
        ),
    )
    assert _plugin_version_label(entry) == "v1.0.0  dev · local changes"


def test_dev_state_label_known_and_unknown_states() -> None:
    assert dev_state_label("dirty") == "local changes"
    assert dev_state_label("current") == ""
    assert dev_state_label(None) == ""
    assert dev_state_label("mystery") == "mystery"


def test_agent_cli_version_label_variants() -> None:
    assert _agent_cli_version_label(_ready_cli_status()) == "v1.0.0 → v1.1.0"
    assert (
        _agent_cli_version_label(_ready_cli_status(update_available=False)) == "v1.0.0"
    )
    assert _agent_cli_version_label(_not_installed_cli_status()) == "latest v0.8.0"
    assert (
        _agent_cli_version_label(
            AgentCliStatus(
                **{**_not_installed_cli_status().__dict__, "latest_version": None}
            )
        )
        == "not installed"
    )


def test_core_version_label_variants() -> None:
    assert (
        _core_version_label(
            _core_package(installed_version="1.0.0", latest_version="1.1.0")
        )
        == "v1.0.0 → v1.1.0"
    )
    assert (
        _core_version_label(
            _core_package(installed_version="1.0.0", latest_version="1.0.0")
        )
        == "v1.0.0"
    )
    assert (
        _core_version_label(_core_package(installed_version=None, latest_version=None))
        == "not installed"
    )
    assert (
        _core_version_label(
            _core_package(
                installed_version="1.0.0",
                latest_version="1.0.0",
                install_type="editable",
            )
        )
        == "v1.0.0   dev"
    )
