"""Runtime and configuration isolation fixtures shared by the test suite."""

from collections.abc import Iterator
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="session")
def _test_llm_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a harmless CLI stub for default-provider autodetection tests."""
    bin_dir = tmp_path_factory.mktemp("llm-bin")
    claude = bin_dir / "claude"
    claude.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--version" ]; then\n'
        "  printf 'Claude Code test stub\\n'\n"
        "  exit 0\n"
        "fi\n"
        "printf 'Claude Code test stub\\n' >&2\n"
        "exit 0\n",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    return bin_dir


@pytest.fixture(autouse=True)
def _default_test_llm_cli(monkeypatch: pytest.MonkeyPatch, _test_llm_bin: Path) -> None:
    """Keep tests deterministic on CI hosts without provider CLIs installed."""
    path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{_test_llm_bin}{os.pathsep}{path}")


@pytest.fixture(autouse=True)
def _isolate_default_llm_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent ambient config/state from forcing a default effort in tests."""
    monkeypatch.setattr("sase.llm_provider.config._get_default_effort", lambda: None)
    monkeypatch.setattr(
        "sase.llm_provider.config._get_temporary_default_effort", lambda now: None
    )


@pytest.fixture(autouse=True)
def _freeze_model_alias_defaults(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Use test-owned model-alias defaults unless a test asks for the real file."""
    from tests._model_alias_defaults_fixture import install_frozen_model_alias_defaults

    if "real_model_alias_defaults" not in request.fixturenames:
        install_frozen_model_alias_defaults(monkeypatch)
    yield


@pytest.fixture
def real_model_alias_defaults() -> Iterator[None]:
    """Exercise the packaged ``model_alias_defaults.yml`` instead of the fixture."""
    from sase.llm_provider import model_alias_policy

    model_alias_policy._load_model_alias_defaults.cache_clear()
    yield
    model_alias_policy._load_model_alias_defaults.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_runner_limit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent ambient machine-wide runner state from changing tests."""
    monkeypatch.setattr(
        "sase.config.runner_limit_override.get_active_runner_limit_override",
        lambda now=None: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel.get_active_runner_limit_override",
        lambda now=None: None,
    )


@pytest.fixture(autouse=True)
def _mock_system_clipboard(request: pytest.FixtureRequest):
    """Prevent tests from touching the real system clipboard / X11 display."""
    if request.node.get_closest_marker("real_clipboard"):
        yield
        return

    with patch("sase.core.clipboard._clipboard_commands", return_value=[]):
        yield


@pytest.fixture(autouse=True)
def _clear_config_caches() -> None:
    """Drop the merged-config / mentor-profile caches before each test.

    The runtime caches live at module scope and would otherwise carry parsed
    config across tests that patch ``load_merged_config`` or rewrite tmp_path
    sase.yml files between runs.
    """
    from sase.config import core as config_core
    from sase.config import file_hooks as file_hooks_config
    from sase.artifact_providers import reset_artifact_provider_registry_cache
    from sase.config import mentor as mentor_config
    from sase.llm_provider import config as llm_provider_config
    from sase.llm_provider import launch_alias_overrides
    from sase.llm_provider.registry import _provider_cli_available
    from sase._linked_repo_identity import reset_repo_identity_caches
    from sase.feature_flags.snapshot import reset_process_feature_flags

    reset_repo_identity_caches()
    reset_artifact_provider_registry_cache()
    reset_process_feature_flags()
    config_core.clear_config_cache()
    llm_provider_config._get_model_aliases_for_token.cache_clear()
    launch_alias_overrides._parse_env_value.cache_clear()
    _provider_cli_available.cache_clear()

    mentor_config._mentor_profiles_cache_token = None
    mentor_config._mentor_profiles_cache_value = None
    mentor_config._local_profile_names_cache_token = None
    mentor_config._local_profile_names_cache_value = None

    file_hooks_config._file_hooks_cache_token = None
    file_hooks_config._file_hooks_cache_value = None


@pytest.fixture(autouse=True)
def _pin_configured_timezone() -> Iterator[None]:
    """Pin the configured timezone to ``America/New_York`` for every test.

    Production resolves an unset ``timezone`` config to the host system tz (see
    :func:`sase.core.time.get_timezone`), which would make wall-clock rendering
    host-dependent — Eastern on a dev machine, UTC on CI — and break the visual
    snapshots and every ``get_timezone()``-relative assertion. Pinning the
    process cache here keeps all tests on one deterministic clock regardless of
    host. Tests that exercise timezone resolution or divergence (see
    ``tz_divergence``) reset and re-pin as needed.

    The cache is reset by poking the module global directly, mirroring how
    ``_clear_config_caches`` resets the config caches.
    """
    from zoneinfo import ZoneInfo

    from sase.core import time as core_time

    core_time._cached_timezone = ZoneInfo("America/New_York")
    yield
    core_time._cached_timezone = None


@pytest.fixture
def tz_divergence(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force configured tz (``America/New_York``) ≠ system tz (``UTC``).

    Reproduces the production bug class where the host's system timezone differs
    from the configured ``timezone``: bare ``datetime.now()`` / ``.astimezone()``
    / ``datetime.fromtimestamp()`` observe UTC while :func:`get_timezone` /
    :func:`local_now` observe Eastern. The system tz is restored on teardown.
    """
    import time as _time
    from zoneinfo import ZoneInfo

    from sase.core import time as core_time

    monkeypatch.setenv("TZ", "UTC")
    _time.tzset()
    core_time._cached_timezone = ZoneInfo("America/New_York")
    try:
        yield
    finally:
        monkeypatch.undo()
        _time.tzset()
        core_time._cached_timezone = ZoneInfo("America/New_York")
