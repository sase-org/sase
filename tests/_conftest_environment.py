"""Filesystem and environment isolation fixtures shared by the test suite."""

from collections.abc import Iterator
import os
import warnings
from pathlib import Path

import pytest
from sase.directory_map_assets import DIRECTORY_MAP_ASSET_OVERRIDE_ENV
from sase.env_contracts import WORKSPACE_PIN_ENV_VARS


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIRECTORY_MAP_PLACEHOLDER = (
    _REPO_ROOT / "tests" / "fixtures" / "directory-map-placeholder.bin"
)
_PYTEST_SANDBOX_DIR_ENV_VAR = "SASE_PYTEST_SANDBOX_DIR"
SASE_MODEL_ALIAS_OVERRIDES_ENV = "SASE_MODEL_ALIAS_OVERRIDES"
_CONSOLE_COLOR_OVERRIDE_ENV_VARS = (
    "CLICOLOR",
    "CLICOLOR_FORCE",
    "FORCE_COLOR",
    "NO_COLOR",
)


def _clear_ambient_console_color_override_env_vars() -> None:
    """Scrub color overrides before test modules construct shared consoles."""
    for key in _CONSOLE_COLOR_OVERRIDE_ENV_VARS:
        os.environ.pop(key, None)


_clear_ambient_console_color_override_env_vars()


@pytest.fixture(scope="session", autouse=True)
def _publish_pytest_sandbox(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Publish this worker's sandbox root for in-process and child-process checks."""
    sandbox = tmp_path_factory.getbasetemp().resolve()
    os.environ[_PYTEST_SANDBOX_DIR_ENV_VAR] = str(sandbox)
    try:
        yield
    finally:
        os.environ.pop(_PYTEST_SANDBOX_DIR_ENV_VAR, None)


@pytest.fixture(autouse=True)
def _restore_working_directory(request: pytest.FixtureRequest) -> Iterator[None]:
    """Restore the process working directory after tests that leak it."""
    start_cwd = os.getcwd()
    yield

    try:
        current_cwd = os.getcwd()
    except FileNotFoundError:
        current_cwd = "<deleted>"

    if current_cwd == start_cwd:
        return

    monkeypatch = request.node.funcargs.get("monkeypatch")
    # ``monkeypatch.chdir`` may be restored after this autouse fixture finalizes.
    if monkeypatch is not None and getattr(monkeypatch, "_cwd", None) is not None:
        return

    os.chdir(start_cwd)
    warnings.warn(
        (
            f"{request.node.nodeid} changed the process working directory "
            f"from {start_cwd!r} to {current_cwd!r}; restored it."
        ),
        RuntimeWarning,
        stacklevel=2,
    )


def redirect_sase_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> Path:
    """Redirect all ``~/.sase/...`` expansions to ``home``.

    Intended for tests that touch ``~/.sase/`` state and need
    writes/reads to land inside a tmp_path without each call site
    threading module-level constants.  Patches both :meth:`Path.expanduser`
    and :func:`os.path.expanduser` because different call sites in the
    codebase use different APIs (``Path.expanduser`` only expands the
    leading ``~`` segment, so patching it at the Path level is required
    to redirect multi-segment ``~/.sase/...`` paths).

    Returns ``home`` for convenience.
    """
    home.mkdir(parents=True, exist_ok=True)
    original_path_expanduser = Path.expanduser
    original_os_expanduser = os.path.expanduser
    ambient_home_env = os.environ.get("HOME")

    if home.name == ".sase":
        monkeypatch.setenv("HOME", str(home.parent))
        monkeypatch.setenv("SASE_HOME", "~/.sase")
    else:
        monkeypatch.setenv("SASE_HOME", str(home))
    redirect_home_env = (
        os.environ.get("HOME") if home.name == ".sase" else ambient_home_env
    )

    def _current_sase_home() -> Path:
        if home.name == ".sase":
            return Path.home() / ".sase"
        return home

    def _home_env_overridden() -> bool:
        """True if a test has set HOME to a different value than at setup time."""
        return os.environ.get("HOME") != redirect_home_env

    def _fake_os(path):  # accepts str or os.PathLike
        s = os.fspath(path) if hasattr(path, "__fspath__") else path
        if (
            isinstance(s, str)
            and (s.startswith("~/.sase/") or s == "~/.sase")
            and not _home_env_overridden()
        ):
            current_home = _current_sase_home()
            if s.startswith("~/.sase/"):
                return str(current_home / s[len("~/.sase/") :])
            return str(current_home)
        return original_os_expanduser(path)

    def _fake_path(self: Path) -> Path:
        # Defer when either a test has further patched os.path.expanduser
        # or a test has redirected HOME itself.
        if os.path.expanduser is not _fake_os or _home_env_overridden():
            return original_path_expanduser(self)
        s = str(self)
        if s.startswith("~/.sase/"):
            return _current_sase_home() / s[len("~/.sase/") :]
        if s == "~/.sase":
            return _current_sase_home()
        return original_path_expanduser(self)

    monkeypatch.setattr(os.path, "expanduser", _fake_os)
    monkeypatch.setattr(Path, "expanduser", _fake_path)
    return home


@pytest.fixture(autouse=True)
def _isolate_sase_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Redirect per-user SASE state/config to per-test tmpdirs.

    Uses ``tmp_path_factory`` (not ``tmp_path``) so the fake sase home lives
    in a sibling directory and doesn't pollute tests that iterate over their
    own ``tmp_path``.
    """
    fake_home = tmp_path_factory.mktemp("home")
    redirect_sase_home(monkeypatch, fake_home / ".sase")
    fake_config_dir = fake_home / ".config" / "sase"

    from sase.config import core as config_core
    from sase.config import targets as config_targets

    monkeypatch.setattr(config_core, "CONFIG_DIR", fake_config_dir)
    monkeypatch.setattr(config_targets, "CONFIG_DIR", fake_config_dir)


@pytest.fixture(autouse=True)
def _restore_workflow_metadata_derived_caches() -> Iterator[None]:
    """Restore VCS-tag caches derived from workspace-provider metadata.

    These globals have no invalidation link back to their source (see
    ``sase.workspace_provider.reset_workflow_metadata_caches``); this is the
    backstop for any test that mutates them directly instead of going
    through that entry point. Snapshot-and-restore, not an unconditional
    clear, so ordinary tests don't pay for a plugin-discovery cache rebuild
    every run.
    """
    from sase.history import prompt_metadata
    from sase.xprompt import _parsing, _parsing_vcs_refs, _parsing_vcs_tags

    def snapshot() -> tuple[object, ...]:
        return (
            _parsing._VCS_TAG_PATTERN,
            _parsing._VCS_TAG_EMBEDDED_PATTERN,
            _parsing._VCS_REPLACE_PATTERN,
            _parsing_vcs_tags._VCS_TAG_PATTERN,
            _parsing_vcs_tags._VCS_TAG_EMBEDDED_PATTERN,
            _parsing_vcs_tags._VCS_REPLACE_PATTERN,
            _parsing_vcs_refs._VCS_UNDERSCORE_NORMALIZER,
            _parsing_vcs_refs._LAUNCH_XPROMPT_AT_REF_RE,
        )

    before = snapshot()
    yield
    if snapshot() == before:
        return

    (
        _parsing._VCS_TAG_PATTERN,
        _parsing._VCS_TAG_EMBEDDED_PATTERN,
        _parsing._VCS_REPLACE_PATTERN,
        _parsing_vcs_tags._VCS_TAG_PATTERN,
        _parsing_vcs_tags._VCS_TAG_EMBEDDED_PATTERN,
        _parsing_vcs_tags._VCS_REPLACE_PATTERN,
        _parsing_vcs_refs._VCS_UNDERSCORE_NORMALIZER,
        _parsing_vcs_refs._LAUNCH_XPROMPT_AT_REF_RE,
    ) = before
    prompt_metadata.known_workflow_names.cache_clear()


@pytest.fixture(autouse=True)
def _use_placeholder_directory_map_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep scaffolded test homes small while preserving asset behavior."""
    monkeypatch.setenv(
        DIRECTORY_MAP_ASSET_OVERRIDE_ENV,
        str(_DIRECTORY_MAP_PLACEHOLDER),
    )


@pytest.fixture
def real_directory_map_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise production packaged directory-map asset installation."""
    monkeypatch.delenv(DIRECTORY_MAP_ASSET_OVERRIDE_ENV, raising=False)


@pytest.fixture
def allow_axe_lifecycle_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow lifecycle tests to operate only against their isolated fake home."""
    monkeypatch.setenv("SASE_AXE_ALLOW_LIFECYCLE_IN_TESTS", "1")


@pytest.fixture(autouse=True)
def _clear_console_color_override_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep captured-output tests independent of the caller's color policy."""
    for key in _CONSOLE_COLOR_OVERRIDE_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _clear_agent_env_vars(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear ambient SASE agent, launch, proc, and chop-linkage env vars per test.

    Prevents launcher state from leaking into tests and causing side effects
    like bogus COMMITS entries in real ChangeSpec files, chop registry records,
    extra linked-repo dirty checks from the live agent workspace, model alias
    overrides affecting resolution assertions, or a live supervisor
    ``SASE_PROC_*`` sidecar being consumed by ordinary gate/ops/launch
    handlers.  Both the canonical ``SASE_LINKED_REPO*`` vars and the deprecated
    ``SASE_SIBLING_REPO*`` aliases are scrubbed so finalizer tests don't inherit
    the developer's real linked repositories (e.g. a dirty chezmoi checkout)
    from the surrounding agent.
    """
    keys_to_clear = {
        key
        for key in os.environ
        if (
            key.startswith("SASE_AGENT_")
            or key.startswith("SASE_LINKED_REPO_")
            or key.startswith("SASE_PROC_")
            or key.startswith("SASE_SIBLING_REPO_")
            or key
            in {
                "SASE_AGENT",
                "SASE_ARTIFACTS_DIR",
                "SASE_BEAD_ID",
                "SASE_CHOP_LUMBERJACK",
                "SASE_CHOP_NAME",
                "SASE_CHOP_PROMPT_HASH",
                "SASE_CHOP_RUN_ID",
                "SASE_FEATURE_FLAGS",
                "SASE_LINKED_REPOS_JSON",
                SASE_MODEL_ALIAS_OVERRIDES_ENV,
                "SASE_SIBLING_REPOS_JSON",
                "TMUX_PANE",
            }
        )
    }
    keys_to_clear.update(WORKSPACE_PIN_ENV_VARS)

    for key in keys_to_clear:
        monkeypatch.delenv(key, raising=False)

    yield

    leaked_proc_keys = [key for key in os.environ if key.startswith("SASE_PROC_")]
    for key in (
        *WORKSPACE_PIN_ENV_VARS,
        "SASE_FEATURE_FLAGS",
        SASE_MODEL_ALIAS_OVERRIDES_ENV,
        *leaked_proc_keys,
    ):
        os.environ.pop(key, None)
