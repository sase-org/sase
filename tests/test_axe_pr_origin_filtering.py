"""AXE exclusion tests for externally imported PR Patches."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.patch import Patch
from sase.axe.check_cycles import CheckCycleRunner
from sase.axe.chop_runner_context import build_oneshot_context
from sase.axe.chop_script_context import load_patches_from_file, read_chop_context
from sase.axe.config import AxeConfig

pytest_plugins = ("tests._axe_lumberjack_fixtures",)


def _patch(name: str, *, pr_origin: str = "unknown") -> Patch:
    return Patch(
        name=name,
        description=name,
        parent=None,
        pr_url=f"https://example.test/pull/{name}",
        pr_origin=pr_origin,
        status="WIP",
        file_path=f"/tmp/{name}.sase",
        line_number=1,
    )


def _context_filtered_names(context_path: str) -> list[str]:
    context = read_chop_context(context_path)
    return [
        patch.name for patch in load_patches_from_file(context.filtered_patches_file)
    ]


def _context_all_names(context_path: str) -> list[str]:
    context = read_chop_context(context_path)
    return [patch.name for patch in load_patches_from_file(context.all_patches_file)]


def test_oneshot_context_excludes_external_patches_with_empty_query(
    temp_state_dir,
) -> None:
    del temp_state_dir
    patches = [
        _patch("sase_owned", pr_origin="sase"),
        _patch("external_owned", pr_origin="external"),
        _patch("unknown_owned"),
    ]

    context_path = build_oneshot_context(
        "origin_empty",
        AxeConfig(query=""),
        find_all_patches_fn=lambda: patches,
    )

    assert _context_all_names(context_path) == ["sase_owned", "unknown_owned"]
    assert _context_filtered_names(context_path) == ["sase_owned", "unknown_owned"]


def test_oneshot_context_excludes_external_before_matching_user_query(
    temp_state_dir,
) -> None:
    del temp_state_dir
    patches = [
        _patch("sase_owned", pr_origin="sase"),
        _patch("external_owned", pr_origin="external"),
    ]
    evaluated_names: list[str] = []

    def evaluator(query: str, candidates: list[Patch]) -> list[bool]:
        assert query == "external_owned"
        evaluated_names.extend(patch.name for patch in candidates)
        return [patch.name == "external_owned" for patch in candidates]

    context_path = build_oneshot_context(
        "origin_match",
        AxeConfig(query="external_owned"),
        find_all_patches_fn=lambda: patches,
        evaluate_query_many_fn=evaluator,
    )

    assert evaluated_names == ["sase_owned"]
    assert _context_all_names(context_path) == ["sase_owned"]
    assert _context_filtered_names(context_path) == []


def test_oneshot_context_no_match_query_still_keeps_external_excluded(
    temp_state_dir,
) -> None:
    del temp_state_dir
    patches = [
        _patch("sase_owned", pr_origin="sase"),
        _patch("external_owned", pr_origin="external"),
    ]
    evaluated_names: list[str] = []

    def evaluator(_query: str, candidates: list[Patch]) -> list[bool]:
        evaluated_names.extend(patch.name for patch in candidates)
        return [False for _ in candidates]

    context_path = build_oneshot_context(
        "origin_no_match",
        AxeConfig(query="missing"),
        find_all_patches_fn=lambda: patches,
        evaluate_query_many_fn=evaluator,
    )

    assert evaluated_names == ["sase_owned"]
    assert _context_all_names(context_path) == ["sase_owned"]
    assert _context_filtered_names(context_path) == []


def test_pr_submitted_checks_skip_external_patches() -> None:
    patches = [
        _patch("sase_owned", pr_origin="sase"),
        _patch("external_owned", pr_origin="external"),
    ]
    runner = CheckCycleRunner(None, lambda _message, _style=None: None)

    with (
        patch("sase.axe.check_cycles.find_all_patches", return_value=patches),
        patch("sase.axe.check_cycles.is_edit_locked", return_value=False),
        patch("sase.axe.check_cycles.write_cycle_result"),
        patch.object(runner, "is_leaf_cl", return_value=True),
        patch.object(
            runner,
            "_start_cl_submitted_check",
            return_value=["started"],
        ) as start_check,
    ):
        _timestamp, processed, updates = runner.run_full_check_cycle()

    assert processed == 1
    assert updates == [{"patch": "sase_owned", "message": "started"}]
    assert [call.args[0].name for call in start_check.call_args_list] == ["sase_owned"]
