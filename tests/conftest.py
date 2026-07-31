"""Pytest configuration for sase tests."""

from collections.abc import Iterator
import os
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
)
from sase.directory_map_assets import DIRECTORY_MAP_ASSET_OVERRIDE_ENV
from sase.env_contracts import WORKSPACE_PIN_ENV_VARS
from sase.llm_provider.launch_alias_overrides import SASE_MODEL_ALIAS_OVERRIDES_ENV
from tests._suite_gate import configure_suite_gate, unconfigure_suite_gate
from tests._tmp_leak_guard import (
    finish_tmp_leak_guard,
    report_tmp_leak_guard,
    start_tmp_leak_guard,
)
from tests._project_display_case import ProjectDisplayCase

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIRECTORY_MAP_PLACEHOLDER = (
    _REPO_ROOT / "tests" / "fixtures" / "directory-map-placeholder.bin"
)
_PYTEST_SANDBOX_DIR_ENV_VAR = "SASE_PYTEST_SANDBOX_DIR"

_PLAN_CHAIN_GOLDEN_TEST_FILES = frozenset(
    Path(path)
    for path in (
        "tests/test_plan_rejection_response.py",
        "tests/test_plan_approval_modal_title.py",
        "tests/test_approve_options_modal_state.py",
        "tests/test_plan_approve_cli.py",
        "tests/main/test_parser_plan.py",
        "tests/test_plan_utils.py",
        "tests/test_axe_run_agent_exec_killed_iteration.py",
        "tests/test_axe_run_agent_exec_plan_followup_approval_effort.py",
        "tests/test_axe_run_agent_exec_plan_followup_approval_plan_refs.py",
        "tests/test_axe_run_agent_exec_plan_followup_approvals.py",
        "tests/test_axe_run_agent_exec_plan_followup_coder_prompt.py",
        "tests/test_axe_run_agent_exec_plan_followup_model_selection.py",
        "tests/test_axe_run_agent_exec_plan_epic_refs.py",
        "tests/test_axe_run_agent_exec_plan_chat_paths.py",
        "tests/test_epic_approval.py",
        "tests/test_followup_prompt_helpers.py",
        "tests/test_axe_run_agent_exec_plan_followup_questions.py",
        "tests/test_axe_run_agent_helpers_questions.py",
        "tests/plan_chain_golden/test_marker_and_loop_golden.py",
        "tests/plan_chain_golden/test_plan_approval_response_golden.py",
    )
)


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect notification gate persistence to a temporary directory."""
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


@pytest.fixture
def project_display_case() -> ProjectDisplayCase:
    """Return the shared canonical-key/display-label mismatch case."""
    return ProjectDisplayCase()


def pytest_configure(config: pytest.Config) -> None:
    """Acquire host-global worker tokens for an xdist controller."""
    configure_suite_gate(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Release host-global worker tokens held by an xdist controller."""
    unconfigure_suite_gate(config)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Snapshot the system temp directory before any test runs."""
    start_tmp_leak_guard(session)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the run when the suite leaked system temp-directory entries."""
    finish_tmp_leak_guard(session)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Name any leaked system temp-directory entries in the summary."""
    report_tmp_leak_guard(config, terminalreporter)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Attach the named plan/questions golden harness marker."""
    for item in items:
        try:
            relpath = Path(item.path).resolve().relative_to(_REPO_ROOT)
        except ValueError:
            continue
        if relpath in _PLAN_CHAIN_GOLDEN_TEST_FILES:
            item.add_marker(pytest.mark.plan_chain_golden)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sase-update-agents-goldens",
        action="store_true",
        default=False,
        help="Update agents-sync Markdown goldens instead of asserting them.",
    )
    parser.addoption(
        "--sase-update-visual-snapshots",
        action="store_true",
        default=False,
        help="Update ACE visual snapshot goldens instead of asserting them.",
    )
    parser.addoption(
        "--sase-visual-artifact-dir",
        default=".pytest_cache/sase-visual",
        help="Directory for ACE visual snapshot failure artifacts.",
    )


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
def _clear_agent_env_vars(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear ambient SASE agent, launch, and chop-linkage env vars per test.

    Prevents launcher state from leaking into tests and causing side effects
    like bogus COMMITS entries in real ChangeSpec files, chop registry records,
    extra linked-repo dirty checks from the live agent workspace, or model alias
    overrides affecting resolution assertions.  Both the canonical
    ``SASE_LINKED_REPO*`` vars and the deprecated ``SASE_SIBLING_REPO*`` aliases
    are scrubbed so finalizer tests don't inherit the developer's real linked
    repositories (e.g. a dirty chezmoi checkout) from the surrounding agent.
    """
    keys_to_clear = {
        key
        for key in os.environ
        if (
            key.startswith("SASE_AGENT_")
            or key.startswith("SASE_LINKED_REPO_")
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
                "SASE_LINKED_REPOS_JSON",
                SASE_MODEL_ALIAS_OVERRIDES_ENV,
                "SASE_SIBLING_REPOS_JSON",
            }
        )
    }
    keys_to_clear.update(WORKSPACE_PIN_ENV_VARS)

    for key in keys_to_clear:
        monkeypatch.delenv(key, raising=False)

    yield

    for key in (*WORKSPACE_PIN_ENV_VARS, SASE_MODEL_ALIAS_OVERRIDES_ENV):
        os.environ.pop(key, None)


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
    from sase.config import mentor as mentor_config
    from sase.llm_provider import config as llm_provider_config
    from sase.llm_provider import launch_alias_overrides
    from sase.llm_provider.registry import provider_cli_available

    config_core.clear_config_cache()
    llm_provider_config._get_model_aliases_for_token.cache_clear()
    launch_alias_overrides._parse_env_value.cache_clear()
    provider_cli_available.cache_clear()

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


@pytest.fixture
def make_changespec(tmp_path: Path) -> "_ChangeSpecFactory":
    """Fixture that provides a factory for creating ChangeSpec objects for testing."""
    return _ChangeSpecFactory(tmp_path)


class _ChangeSpecFactory:
    """Factory class for creating ChangeSpec objects in tests."""

    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path

    @staticmethod
    def create(
        name: str = "test",
        description: str = "desc",
        status: str = "Ready",
        cl: str | None = None,
        parent: str | None = None,
        file_path: str = "/home/user/.sase/projects/myproject/myproject.sase",
        commits: list[CommitEntry] | None = None,
        hooks: list[HookEntry] | None = None,
        comments: list[CommentEntry] | None = None,
    ) -> ChangeSpec:
        """Create a ChangeSpec for testing."""
        return ChangeSpec(
            name=name,
            description=description,
            parent=parent,
            cl=cl,
            status=status,
            file_path=file_path,
            line_number=1,
            commits=commits,
            hooks=hooks,
            comments=comments,
        )

    def create_with_file(
        self,
        name: str = "test_feature",
        cl: str | None = "http://cl/123456789",
        status: str = "Mailed",
        parent: str | None = None,
    ) -> ChangeSpec:
        """Create a ChangeSpec backed by a temporary project spec file on disk.

        The caller is responsible for cleaning up the temp file via
        ``Path(cs.file_path).unlink()``.
        """
        with tempfile.NamedTemporaryFile(
            dir=self._tmp_path,
            mode="w",
            delete=False,
            suffix=".sase",
        ) as f:
            parent_val = parent if parent else "None"
            cl_val = cl if cl else "None"
            f.write(f"""# Test Project

## ChangeSpec

NAME: {name}
DESCRIPTION:
  A test feature
PARENT: {parent_val}
PR: {cl_val}
STATUS: {status}

---
""")
            return ChangeSpec(
                name=name,
                description="A test feature",
                parent=parent,
                cl=cl,
                status=status,
                file_path=f.name,
                line_number=6,
            )
