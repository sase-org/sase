"""Runtime and configuration isolation fixtures shared by the test suite."""

from collections.abc import Iterator
import os
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

_CONFIG_TOKEN_REFRESH_JOIN_TIMEOUT_SECONDS = 2.0


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


def _drain_config_token_refresh(
    *, timeout: float = _CONFIG_TOKEN_REFRESH_JOIN_TIMEOUT_SECONDS
) -> None:
    """Invalidate the token generation and join a live refresh worker.

    The module pointer is cleared only when the observed worker has exited.
    A timed-out join leaves a still-live worker registered and raises so a
    later test cannot inherit a silently orphaned single-flight slot.
    """
    from sase.config import core as config_core

    with config_core._current_config_token_cache_lock:
        config_core._reset_current_config_token_cache_locked()
        thread = config_core._current_config_token_refresh_thread
    skipped_join = thread is None or thread is threading.current_thread()
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=timeout)
    with config_core._current_config_token_cache_lock:
        if config_core._current_config_token_refresh_thread is not thread:
            return
        if thread is not None and thread.is_alive():
            if skipped_join:
                return
            raise RuntimeError(
                f"{config_core.CONFIG_TOKEN_REFRESH_THREAD_NAME} did not exit "
                f"within {timeout}s; leaving the live worker registered"
            )
        config_core._current_config_token_refresh_thread = None


def _clear_function_cache(cached: object) -> None:
    """Clear a functools cache when the object still exposes ``cache_clear``.

    Yield teardown of ``_clear_config_caches`` runs while the test's
    ``monkeypatch`` is still active (it is owned by ``_isolate_sase_home``).
    Tests often replace these helpers with lambdas, so the live module
    attribute cannot be assumed to be the original cached function.
    """
    cache_clear = getattr(cached, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def _capture_derived_config_cache_helpers() -> tuple[object, object, object]:
    """Bind the real cached helpers before tests replace their names."""
    from sase.llm_provider import config as llm_provider_config
    from sase.llm_provider import launch_alias_overrides
    from sase.llm_provider.registry import _provider_cli_available

    return (
        llm_provider_config._get_model_aliases_for_token,
        launch_alias_overrides._parse_env_value,
        _provider_cli_available,
    )


_DERIVED_CONFIG_CACHE_HELPERS: tuple[object, object, object] | None = None


def _derived_config_cache_helpers() -> tuple[object, object, object]:
    """Return the original cached helpers captured on first isolation setup."""
    global _DERIVED_CONFIG_CACHE_HELPERS
    if _DERIVED_CONFIG_CACHE_HELPERS is None:
        _DERIVED_CONFIG_CACHE_HELPERS = _capture_derived_config_cache_helpers()
    return _DERIVED_CONFIG_CACHE_HELPERS


def reset_process_feature_flags() -> None:
    """Unpin the process feature-flag snapshot so the next read re-resolves.

    Installation is deliberately once-per-process, so nothing in ``src``
    resets a pinned snapshot and this seam belongs to the test harness.
    """
    from sase.feature_flags import snapshot as flag_snapshot

    with flag_snapshot._lock:
        flag_snapshot._snapshot = None
        flag_snapshot._installed = False
        flag_snapshot._override_stack.clear()
        flag_snapshot._cli_values.clear()


def _stop_orphaned_proc_observers_if_loaded() -> None:
    """Stop leaked ACE proc observers without importing the TUI into every test."""
    import sys

    module = sys.modules.get("sase.ace.tui.proc_observer")
    if module is None:
        return
    stop = getattr(module, "stop_orphaned_proc_observers", None)
    if callable(stop):
        stop()


def _reset_derived_config_caches() -> None:
    """Drop process-global config, identity, and derived layer caches."""
    from sase.config import core as config_core
    from sase.config import file_hooks as file_hooks_config
    from sase.artifact_providers import reset_artifact_provider_registry_cache
    from sase.config import mentor as mentor_config
    from sase._linked_repo_identity import reset_repo_identity_caches

    reset_repo_identity_caches()
    reset_artifact_provider_registry_cache()
    reset_process_feature_flags()
    _stop_orphaned_proc_observers_if_loaded()
    _drain_config_token_refresh()
    config_core.clear_config_cache()
    for cached in _derived_config_cache_helpers():
        _clear_function_cache(cached)

    mentor_config._mentor_profiles_cache_token = None
    mentor_config._mentor_profiles_cache_value = None
    mentor_config._local_profile_names_cache_token = None
    mentor_config._local_profile_names_cache_value = None

    file_hooks_config._file_hooks_cache_token = None
    file_hooks_config._file_hooks_cache_value = None
    file_hooks_config._file_hook_diagnostics_cache_value = None


@pytest.fixture(autouse=True)
def _isolate_plugin_config(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Keep plugin-contributed ``sase_config`` layers out of default tests.

    Tests assert bundled defaults. A required plugin's ``default_config.yml``
    (for example ``ace.tribes.research`` from sase-research-artifacts) must
    not change suite expectations just because that plugin is installed.
    Request ``real_plugin_config`` to exercise the production merge.
    """
    if "real_plugin_config" not in request.fixturenames:
        monkeypatch.setenv("SASE_DISABLE_PLUGIN_CONFIG", "1")


@pytest.fixture
def real_plugin_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Load installed plugin ``sase_config`` layers into merged config."""
    monkeypatch.delenv("SASE_DISABLE_PLUGIN_CONFIG", raising=False)
    monkeypatch.delenv("SASE_DISABLE_PLUGINS", raising=False)
    _reset_derived_config_caches()
    yield
    _reset_derived_config_caches()


@pytest.fixture(autouse=True)
def _clear_config_caches(
    _isolate_sase_home: None,
    _isolate_plugin_config: None,
) -> Iterator[None]:
    """Isolate the process-global config cache around each test.

    Setup runs after ``_isolate_sase_home`` has redirected ``CONFIG_DIR`` and
    ``_isolate_plugin_config`` has decided whether plugin ``sase_config``
    layers belong, so a leftover reader cannot install a host-path token or
    a plugin layer into the successor's generation. Teardown stops orphaned
    ``sase-ace-proc-observer`` threads, drains ``sase-config-token-refresh``,
    and clears derived caches again before monkeypatch restores host paths.
    """
    _reset_derived_config_caches()
    yield
    _reset_derived_config_caches()


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
