"""Routine-tick cost guards: Patch parsing and tick-file writes only where needed.

A routine tick used to parse every ProjectSpec and rewrite
``all_changespecs.json``, ``filtered_changespecs.json``, and ``context.json``
whatever its jobs were. These tests pin the cheaper contract with call counts
and on-disk file identities rather than wall-clock budgets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.patch import Patch
from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.chop_script_context import (
    ChopScriptContext,
    load_patches_from_file,
    serialize_patches,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig, load_axe_config
from sase.axe.lumberjack import Lumberjack
from sase.axe.tick_context import (
    PATCH_READING_BUILTIN_JOBS,
    _file_identity,
    _job_reads_tick_patches,
    routine_reads_tick_patches,
)
from sase.chops.builtin import BuiltinChopRuntime

pytest_plugins = ("tests._axe_lumberjack_fixtures",)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FINGERPRINT = "sase.axe.tick_context._patch_files_fingerprint"
_FIND_ALL = "sase.axe.check_cycles.find_all_patches"
_RUN_CHOP = "sase.axe._lumberjack_chop.run_configured_chop_once"
_SERIALIZE = "sase.axe.tick_context.serialize_patches"


def _patch(name: str, *, pr_origin: str = "sase") -> Patch:
    return Patch(
        name=name,
        description=name,
        parent=None,
        pr_url=None,
        pr_origin=pr_origin,
        status="WIP",
        file_path=f"/tmp/{name}.sase",
        line_number=1,
    )


def _axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3, max_agent_runners=3, zombie_timeout_seconds=3600, query=""
    )


def _routine(name: str, *scripts: str) -> Lumberjack:
    config = LumberjackConfig(
        name=name,
        description="Routine-tick fixture",
        interval=5,
        chops=[
            ChopConfig(
                name=script.removeprefix("sase_job_"), description="", script=script
            )
            for script in scripts
        ],
    )
    return Lumberjack(name, config, _axe_config())


def _success(name: str) -> ChopRunOutcome:
    return ChopRunOutcome(lumberjack_name="fixture", chop_name=name, status="success")


def _tick_files(state_dir: Path, routine: str) -> dict[str, Path]:
    tick = state_dir / "lumberjacks" / routine / "tick"
    return {
        "all": tick / "all_changespecs.json",
        "filtered": tick / "filtered_changespecs.json",
        "context": tick / "context.json",
    }


def _identities(files: dict[str, Path]) -> dict[str, object]:
    return {key: _file_identity(path) for key, path in files.items()}


def test_non_patch_routine_tick_never_parses_or_serializes_patches(
    temp_state_dir: Path,
) -> None:
    routine = _routine("usage", "sase_job_usage_refresh")
    with (
        patch(_FIND_ALL) as find_all,
        patch(_FINGERPRINT) as fingerprint,
        patch(_RUN_CHOP, return_value=_success("usage_refresh")),
    ):
        routine._run_tick()
        routine._run_tick()

    assert find_all.call_count == 0
    assert fingerprint.call_count == 0
    files = _tick_files(temp_state_dir, "usage")
    assert not files["all"].exists()
    assert not files["filtered"].exists()
    context = json.loads(files["context"].read_text(encoding="utf-8"))
    assert context["all_patches_file"] == ""
    assert context["filtered_patches_file"] == ""


def test_unchanged_patch_tick_parses_once_and_rewrites_nothing(
    temp_state_dir: Path,
) -> None:
    patches = [_patch("alpha"), _patch("beta"), _patch("ext", pr_origin="external")]
    routine = _routine("hooks", "sase_job_hook_checks")
    files = _tick_files(temp_state_dir, "hooks")
    with (
        patch(_FIND_ALL, return_value=patches) as find_all,
        patch(_FINGERPRINT, return_value=(("spec", None, (1, 2, 3)),)),
        patch(_SERIALIZE, wraps=serialize_patches) as serialize,
        patch(_RUN_CHOP, return_value=_success("hook_checks")),
    ):
        routine._run_tick()
        assert find_all.call_count == 1
        assert serialize.call_count == 2
        first = _identities(files)
        names = [p.name for p in load_patches_from_file(str(files["all"]))]
        assert names == ["alpha", "beta"]

        serialize.reset_mock()
        routine._run_tick()
        routine._run_tick()

    assert find_all.call_count == 1
    assert serialize.call_count == 0
    assert _identities(files) == first


def test_changed_inputs_or_foreign_rewrites_refresh_only_affected_files(
    temp_state_dir: Path,
) -> None:
    patches = [_patch("alpha"), _patch("beta")]
    fingerprint = MagicMock(return_value=(("spec", None, (1, 2, 3)),))
    routine = _routine("hooks", "sase_job_hook_checks")
    files = _tick_files(temp_state_dir, "hooks")
    with (
        patch(_FIND_ALL, return_value=patches) as find_all,
        patch(_FINGERPRINT, fingerprint),
        patch(_SERIALIZE, wraps=serialize_patches) as serialize,
        patch(_RUN_CHOP, return_value=_success("hook_checks")),
        patch("sase.axe.check_cycles.is_edit_locked", return_value=False) as locked,
    ):
        routine._run_tick()

        # An edit lock changes only the filtered selection.
        locked.side_effect = lambda path: path.endswith("beta.sase")
        serialize.reset_mock()
        routine._run_tick()
        assert find_all.call_count == 1
        assert [c.args[1] for c in serialize.call_args_list] == [str(files["filtered"])]
        filtered = load_patches_from_file(str(files["filtered"]))
        assert [p.name for p in filtered] == ["alpha"]

        # A ProjectSpec identity change re-parses; unchanged content is still
        # rewritten because the inputs changed.
        fingerprint.return_value = (("spec", None, (9, 2, 3)),)
        serialize.reset_mock()
        routine._run_tick()
        assert find_all.call_count == 2
        assert serialize.call_count == 2

        # A one-shot run rewriting the shared tick file is repaired.
        files["all"].write_text("[]", encoding="utf-8")
        serialize.reset_mock()
        routine._run_tick()
        assert find_all.call_count == 2
        assert [c.args[1] for c in serialize.call_args_list] == [str(files["all"])]
    assert len(load_patches_from_file(str(files["all"]))) == 2


def test_unavailable_fingerprint_falls_back_to_parsing_every_tick(
    temp_state_dir: Path,
) -> None:
    routine = _routine("hooks", "sase_job_hook_checks")
    with (
        patch(_FIND_ALL, return_value=[_patch("alpha")]) as find_all,
        patch(_FINGERPRINT, return_value=None),
        patch(_SERIALIZE, wraps=serialize_patches) as serialize,
        patch(_RUN_CHOP, return_value=_success("hook_checks")),
    ):
        routine._run_tick()
        routine._run_tick()
    assert find_all.call_count == 2
    assert serialize.call_count == 4


def test_patch_readers_are_guards_builtin_lifecycle_jobs_and_external_scripts() -> None:
    assert _job_reads_tick_patches(
        ChopConfig(name="hook_checks", description="", script="sase_job_hook_checks")
    )
    assert _job_reads_tick_patches(
        ChopConfig(name="legacy", description="", script="sase_chop_orphan_cleanup")
    )
    assert not _job_reads_tick_patches(
        ChopConfig(name="wait_checks", description="", script="sase_job_wait_checks")
    )
    # Plugin jobs in the SASE namespace read Patches through the job runtime.
    assert not _job_reads_tick_patches(
        ChopConfig(name="tg_outbound", description="", script="sase_job_tg_outbound")
    )
    # External scripts may read the documented context files directly.
    assert _job_reads_tick_patches(
        ChopConfig(name="ci_watch", description="", script="bugyi_chop_ci_watch")
    )
    guarded = ChopConfig(
        name="toobig",
        description="",
        script="sase_job_toobig",
        inhibit_if=[{"provider": "patch", "name_prefix": "x"}],
    )
    assert _job_reads_tick_patches(guarded)
    disabled = ChopConfig(
        name="hook_checks",
        description="",
        script="sase_job_hook_checks",
        enabled=False,
    )
    assert not routine_reads_tick_patches([disabled])


def test_patch_reading_builtin_jobs_match_the_scripts_that_read_patches() -> None:
    """Adding a Patch-reading builtin job must also register it as a reader."""
    readers = set()
    pattern = re.compile(r"\.(?:all|filtered)_patches\b")
    for script in (_REPO_ROOT / "src" / "sase" / "scripts").glob("sase_chop_*.py"):
        if pattern.search(script.read_text(encoding="utf-8")):
            readers.add(script.stem.removeprefix("sase_chop_"))
    assert readers == PATCH_READING_BUILTIN_JOBS


def test_only_the_hooks_lane_serializes_patches_in_the_default_config() -> None:
    config = load_axe_config()
    readers = {
        name
        for name, routine in config.lumberjacks.items()
        if routine_reads_tick_patches(
            chop for chop in routine.chops if chop.source == "builtin"
        )
    }
    assert readers == {"hooks"}


def test_job_runtime_parses_on_demand_when_the_tick_skipped_patches() -> None:
    context = ChopScriptContext(
        max_hook_runners=1,
        max_agent_runners=1,
        zombie_timeout_seconds=60,
        query="",
        lumberjack_name="waits",
        state_dir="/tmp",
        all_patches_file="",
        filtered_patches_file="",
    )
    runtime = BuiltinChopRuntime(name="probe", context=context, log=MagicMock())
    patches = [_patch("alpha"), _patch("ext", pr_origin="external")]
    with (
        patch("sase.ace.patch.find_all_patches", return_value=patches) as find_all,
        patch("sase.axe.check_cycles.is_edit_locked", return_value=False),
    ):
        assert [p.name for p in runtime.all_patches] == ["alpha"]
        assert [p.name for p in runtime.filtered_patches] == ["alpha"]
    assert find_all.call_count == 1
