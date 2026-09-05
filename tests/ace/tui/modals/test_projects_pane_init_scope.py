"""Unit tests for Projects-tab init scope → argv mapping."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.projects_pane_init import (
    INIT_APPLY_PER_PROJECT_SECONDS,
    INIT_APPLY_STARTUP_SECONDS,
    INIT_CHECK_PER_PROJECT_SECONDS,
    INIT_CHECK_STARTUP_SECONDS,
    InitScope,
    apply_timeout,
    check_timeout,
    init_cwd,
)


def test_single_project_argv_label_and_cl_name() -> None:
    scope = InitScope.for_projects(("sase",), ("SASE",))

    assert scope.check_argv() == [
        "sase",
        "init",
        "-p",
        "sase",
        "--check",
        "--json",
    ]
    assert scope.apply_argv() == ["sase", "init", "-p", "sase", "--yes"]
    assert scope.scope_key == "sase"
    assert scope.label == "SASE"
    assert scope.cl_name == "sase"
    assert scope.scope_flags == ("-p", "sase")


def test_multi_project_argv_preserves_request_order() -> None:
    scope = InitScope.for_projects(("beta", "alpha"), ("Beta", "Alpha"))

    assert scope.check_argv() == [
        "sase",
        "init",
        "-p",
        "beta",
        "-p",
        "alpha",
        "--check",
        "--json",
    ]
    assert scope.apply_argv() == [
        "sase",
        "init",
        "-p",
        "beta",
        "-p",
        "alpha",
        "--yes",
    ]
    assert scope.label == "2 projects"
    assert scope.cl_name == ""
    assert scope.scope_flags == ("-p", "beta", "-p", "alpha")


def test_terminal_argv_has_no_check_json_or_yes() -> None:
    scope = InitScope.for_projects(("sase",), ("SASE",))

    assert scope.terminal_argv() == ["sase", "init", "-p", "sase"]


def test_terminal_argv_multi_project_preserves_request_order() -> None:
    scope = InitScope.for_projects(("beta", "alpha"), ("Beta", "Alpha"))

    assert scope.terminal_argv() == ["sase", "init", "-p", "beta", "-p", "alpha"]


def test_scope_key_is_stable_under_reordering() -> None:
    first = InitScope.for_projects(("beta", "alpha"), ("Beta", "Alpha"))
    second = InitScope.for_projects(("alpha", "beta"), ("Alpha", "Beta"))

    assert first.scope_key == "alpha:beta"
    assert first.scope_key == second.scope_key


def test_all_projects_scope() -> None:
    scope = InitScope.everything()

    assert scope.check_argv() == [
        "sase",
        "init",
        "--all",
        "--check",
        "--json",
    ]
    assert scope.apply_argv() == ["sase", "init", "--all", "--yes"]
    assert scope.scope_key == "all"
    assert scope.label == "all projects"
    assert scope.cl_name == ""
    assert scope.scope_flags == ("--all",)


def test_timeouts_scale_for_one_three_and_eight_targets() -> None:
    assert (
        check_timeout(1) == INIT_CHECK_STARTUP_SECONDS + INIT_CHECK_PER_PROJECT_SECONDS
    )
    assert check_timeout(3) == INIT_CHECK_STARTUP_SECONDS + (
        INIT_CHECK_PER_PROJECT_SECONDS * 3
    )
    assert check_timeout(8) == INIT_CHECK_STARTUP_SECONDS + (
        INIT_CHECK_PER_PROJECT_SECONDS * 8
    )
    assert (
        apply_timeout(1) == INIT_APPLY_STARTUP_SECONDS + INIT_APPLY_PER_PROJECT_SECONDS
    )
    assert apply_timeout(3) == INIT_APPLY_STARTUP_SECONDS + (
        INIT_APPLY_PER_PROJECT_SECONDS * 3
    )
    assert apply_timeout(8) == INIT_APPLY_STARTUP_SECONDS + (
        INIT_APPLY_PER_PROJECT_SECONDS * 8
    )
    assert check_timeout(0) == check_timeout(1)
    assert apply_timeout(0) == apply_timeout(1)


def test_init_cwd_is_home() -> None:
    assert init_cwd() == Path.home()
