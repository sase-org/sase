"""Title formatting for the ACE TUI app.

The header title shows the running ``sase`` version. It is resolved in two
phases: an instant, I/O-free ``__version__`` string at ``__init__`` and a
best-effort, git-aware refinement applied off-thread during ``on_mount``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from textual.pilot import Pilot

import sase
from sase.ace.tui.app import AceApp
from sase.ace.tui.util.app_version import (
    format_app_title,
    initial_app_version,
    resolved_app_version,
)


def test_app_title_shows_initial_version() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)

    assert app.title == f"sase ace (v{sase.__version__})"
    assert app.title.startswith("sase ace ")
    assert app.title.endswith(")")


def test_app_default_initial_tab_is_agents() -> None:
    app = AceApp(query="!!!", auto_start_axe=False)

    assert app.current_tab == "agents"


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])
def test_app_initial_tab_assigned_during_init(tab: str) -> None:
    app = AceApp(query="!!!", auto_start_axe=False, initial_tab=tab)  # type: ignore[arg-type]

    assert app.current_tab == tab


def test_initial_app_version_is_dunder_version() -> None:
    assert initial_app_version() == sase.__version__


def test_format_app_title_prefixes_with_v() -> None:
    assert format_app_title("0.7.1") == "sase ace (v0.7.1)"
    assert format_app_title("0.8.0+3.g084a6a2.dirty") == (
        "sase ace (v0.8.0+3.g084a6a2.dirty)"
    )


def test_resolved_app_version_returns_host_display_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ACE_RELEASE_VERSION_TITLE", raising=False)
    monkeypatch.setattr(
        "sase.version.host_display_version", lambda: "0.8.0+3.g084a6a2.dirty"
    )

    assert resolved_app_version() == "0.8.0+3.g084a6a2.dirty"


def test_resolved_app_version_is_none_when_release_title_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> str | None:
        raise AssertionError("host display version should not be resolved")

    monkeypatch.setenv("SASE_ACE_RELEASE_VERSION_TITLE", "1")
    monkeypatch.setattr("sase.version.host_display_version", _boom)

    assert resolved_app_version() is None


def test_resolved_app_version_is_none_when_resolver_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> str | None:
        raise RuntimeError("git exploded")

    monkeypatch.setattr("sase.version.host_display_version", _boom)

    assert resolved_app_version() is None


def test_resolved_app_version_passes_through_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.version.host_display_version", lambda: None)

    assert resolved_app_version() is None


def test_host_display_version_returns_record_display_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.version import host_display_version

    monkeypatch.setattr(
        "sase.version._host.collect_package_record",
        lambda *a, **kw: SimpleNamespace(display_version="1.2.3"),
    )

    assert host_display_version() == "1.2.3"


def test_host_display_version_normalizes_unknown_sentinel_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.version import host_display_version

    monkeypatch.setattr(
        "sase.version._host.collect_package_record",
        lambda *a, **kw: SimpleNamespace(display_version="<unknown>"),
    )

    assert host_display_version() is None


async def _wait_for_mount_state_loads(app: AceApp, pilot: Pilot[None]) -> None:
    """Poll until the title write's barrier fires, or fail with a clear message."""
    deadline = asyncio.get_running_loop().time() + 15.0
    while not app._mount_state_loads_done:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("mount state loads did not finish within 15 seconds")
        await pilot.pause()


async def test_on_mount_refines_title_to_resolved_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolved dev version replaces the instant ``__version__`` title."""
    dev_version = f"{sase.__version__}+9.gdeadbee.dirty"
    monkeypatch.setattr(
        "sase.ace.tui.util.app_version.resolved_app_version",
        lambda: dev_version,
    )

    app = AceApp(query="!!!", auto_start_axe=False)
    async with app.run_test() as pilot:
        await _wait_for_mount_state_loads(app, pilot)
        assert app.title == format_app_title(dev_version)


async def test_on_mount_keeps_initial_title_when_resolver_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``None`` resolution leaves the instant ``__version__`` title intact."""
    monkeypatch.setattr(
        "sase.ace.tui.util.app_version.resolved_app_version",
        lambda: None,
    )

    app = AceApp(query="!!!", auto_start_axe=False)
    async with app.run_test() as pilot:
        await _wait_for_mount_state_loads(app, pilot)
        assert app.title == f"sase ace (v{sase.__version__})"
