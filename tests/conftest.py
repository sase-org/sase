"""Pytest configuration for sase tests."""

from collections.abc import Iterator
import sys
from pathlib import Path

import pytest
from tests._conftest_environment import (
    _clear_agent_env_vars,
    _isolate_sase_home,
    _publish_pytest_sandbox,
    _restore_workflow_metadata_derived_caches,
    _restore_working_directory,
    _use_placeholder_directory_map_assets,
    allow_axe_lifecycle_in_tests,
    real_directory_map_assets,
    redirect_sase_home,
)
from tests._conftest_runtime import (
    _clear_config_caches,
    _default_test_llm_cli,
    _freeze_model_alias_defaults,
    _isolate_default_llm_effort,
    _isolate_runner_limit_override,
    _mock_system_clipboard,
    _pin_configured_timezone,
    _test_llm_bin,
    real_model_alias_defaults,
    tz_divergence,
)
from tests._conftest_shared import (
    _PatchFactory,
    gate_home,
    make_changespec,  # legacy compatibility fixture alias
    make_patch,
    project_display_case,
)
from tests._sase_global_state_isolation import (
    restore_sase_environment,
    snapshot_sase_environment,
)
from tests._suite_gate import configure_suite_gate, unconfigure_suite_gate
from tests._tmp_leak_guard import (
    check_tmp_env_leak_guard,
    finish_tmp_leak_guard,
    report_tmp_leak_guard,
    start_tmp_env_leak_guard,
    start_tmp_leak_guard,
)

# ``pytester`` is used by ordering-regression tests that run a handful of real
# node IDs through a nested pytest subprocess. The imports above expose the
# split fixture modules to pytest while preserving existing direct imports
# from ``tests.conftest``.
pytest_plugins = ["pytester"]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL: object | None = None

_PLAN_CHAIN_GOLDEN_TEST_FILES = frozenset(
    Path(path)
    for path in (
        "tests/test_plan_rejection_response.py",
        "tests/test_tui_plan_approval_archive.py",
        "tests/test_tui_plan_epic_approval.py",
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


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Iterator[None]:
    """Restore ambient env state before detector after-snapshots run."""
    environment = snapshot_sase_environment()
    yield
    restore_sase_environment(environment)


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
    _restore_hypothesis_local_constant_prescan()
    finish_tmp_leak_guard(session)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Snapshot the per-test TMPDIR env-leak guard baseline before ``item`` runs."""
    start_tmp_env_leak_guard(item)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Iterator[None]:
    """Fail ``item`` if it leaked TMPDIR/SASE_PYTEST_TMP_REDIRECTED past teardown.

    Runs as a hookwrapper so the check fires strictly after this item's own
    fixture teardown (including ``monkeypatch``'s automatic restoration) has
    completed, regardless of where this hook's fixtures would otherwise land
    relative to ``monkeypatch`` in the teardown stack.
    """
    yield
    check_tmp_env_leak_guard(item)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Name any leaked system temp-directory entries in the summary."""
    report_tmp_leak_guard(config, terminalreporter)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Attach the named plan/questions golden harness marker."""
    _disable_hypothesis_local_constant_prescan_for_collect_only(config)
    for item in items:
        path = Path(item.path)
        try:
            relpath = path.relative_to(_REPO_ROOT) if path.is_absolute() else path
        except ValueError:
            continue
        if relpath in _PLAN_CHAIN_GOLDEN_TEST_FILES:
            item.add_marker(pytest.mark.plan_chain_golden)


def _disable_hypothesis_local_constant_prescan_for_collect_only(
    config: pytest.Config,
) -> None:
    """Avoid Hypothesis' local-constant scan in collection-only diagnostics."""
    global _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL

    if not bool(getattr(config.option, "collectonly", False)):
        return
    if "hypothesis" not in sys.modules:
        return
    if _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL is not None:
        return
    try:
        from hypothesis.internal.conjecture import providers
    except ImportError:
        return

    _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL = providers._get_local_constants

    def _cached_local_constants_only() -> object:
        return providers._local_constants

    providers._get_local_constants = _cached_local_constants_only


def _restore_hypothesis_local_constant_prescan() -> None:
    """Restore Hypothesis internals after a collection-only diagnostics run."""
    global _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL

    if _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL is None:
        return
    try:
        from hypothesis.internal.conjecture import providers
    except ImportError:
        _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL = None
        return
    providers._get_local_constants = _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL
    _HYPOTHESIS_LOCAL_CONSTANTS_ORIGINAL = None


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
