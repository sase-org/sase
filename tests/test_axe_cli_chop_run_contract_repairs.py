"""Acceptance coverage for the routine/job identity and diagnostic repairs.

Proves the repaired contract end to end: a real ``%id``/``%clan`` launch's
on-disk state agrees across the runner wait fast path, the wait-check job's
cross-project scan, and the fork path (rather than each being unit-tested
against its own synthetic fixture), and the two canonical error messages that
had no existing regression coverage use job wording.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.axe.cli import handle_axe_chop_list, handle_axe_chop_run
from sase.axe.run_agent_phases import extract_directives_and_write_meta
from sase.axe.run_agent_wait_deps import initial_dependencies_resolved
from sase.config.core import ConfigLayer
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    dependency_resolution_status,
    read_json_dict,
)
from sase.feature_flags import override_flags
from sase.scripts._agent_chat_from_name_tribe import resolve_tribe_fork_source

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ("tests._axe_cli_fixtures",)


def _cross_project_index(projects_dir: Path) -> WaitDependencyIndex:
    """Mirror the wait-check job's own cross-project scan construction."""
    index = WaitDependencyIndex.empty()
    artifact_rows: list[tuple[Path, dict[str, object], str]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name, "ace-run", projects_root=projects_dir
        ):
            meta = read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                artifact_rows.append((artifact_dir, meta, project_dir.name))
    index.add_many(artifact_rows)
    return index


def test_id_tribe_job_alias_agrees_across_wait_fast_path_wait_check_and_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``%id(tribe=job)`` launch with no independent ``job`` identity
    persists ``chop``, and a later ``@job`` reference must still bind to the
    real ``chop`` agent through every consumer of the shared stored-tribe
    evidence: the runner's single-project fast path, the wait-check job's
    cross-project scan, and the fork path."""
    sase_home = tmp_path / "home" / ".sase"
    projects_dir = sase_home / "projects"
    project_dir = projects_dir / "proj"
    workspace_dir = tmp_path / "workspace"
    waiter_timestamp = "20260917110000"
    launch_timestamp = "20260917120000"
    waiter_dir = project_dir / "artifacts" / "ace-run" / waiter_timestamp
    artifacts_dir = project_dir / "artifacts" / "ace-run" / launch_timestamp
    workspace_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)

    with (
        patch(
            "sase.llm_provider.temporary_override."
            "resolve_effective_default_provider_model",
            return_value=("codex", "gpt-5"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        patch("sase.config.inventory.discover_layer_inputs", return_value=[]),
        patch("sase.agent.names.claim_agent_name"),
    ):
        info = extract_directives_and_write_meta(
            "%id(taggy, tribe=job)\nDo work",
            str(workspace_dir),
            str(artifacts_dir),
            cl_name="taggy",
        )

    assert info.tribe == "chop"
    meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
    assert meta["tribe"] == "chop"
    assert meta["name"] == "taggy"

    response_path = tmp_path / "taggy-response.md"
    response_path.write_text("done", encoding="utf-8")
    (artifacts_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "response_path": str(response_path)}),
        encoding="utf-8",
    )

    assert initial_dependencies_resolved(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )

    cross_project_index = _cross_project_index(projects_dir)
    assert "job" not in cross_project_index.stored_tribe_names()
    status = dependency_resolution_status(
        cross_project_index,
        ["@job"],
        self_artifact_dir=waiter_dir,
    )
    assert status.resolved

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(waiter_dir))
    fork_source = resolve_tribe_fork_source("@job")
    assert fork_source.kind == "agent"
    assert fork_source.name == "taggy"


def test_clan_only_job_alias_agrees_across_wait_fast_path_and_fork(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clan whose only tribe evidence is ``clan_tribe: job`` must be
    recognized as an independent identity by both the runner's fast path and
    the fork path, using the one shared evidence source."""
    sase_home = tmp_path / "home" / ".sase"
    projects_dir = sase_home / "projects"
    project_dir = projects_dir / "proj"
    waiter_timestamp = "20260917100000"
    generation = "20260917100100"
    waiter_dir = project_dir / "artifacts" / "ace-run" / waiter_timestamp
    clan_member_dir = project_dir / "artifacts" / "ace-run" / generation
    waiter_dir.mkdir(parents=True)
    clan_member_dir.mkdir(parents=True)
    (clan_member_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "review.one",
                "agent_clan": "review",
                "agent_clan_generation": generation,
                "clan_tribe": "job",
            }
        ),
        encoding="utf-8",
    )
    response_path = tmp_path / "review-one-response.md"
    response_path.write_text("done", encoding="utf-8")
    (clan_member_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "response_path": str(response_path)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    assert initial_dependencies_resolved(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(waiter_dir))
    fork_source = resolve_tribe_fork_source("@job")
    assert fork_source.kind == "clan"
    assert fork_source.name == "review"


def test_job_result_validation_error_uses_canonical_wording(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A job that writes an invalid result document fails closed with the
    job-worded Rust validation message, not the retired ``chop`` wording."""
    scripts_dir = tmp_path / "scripts"
    make_script(
        tmp_path,
        "broken_result",
        "printf '%s' '{not-json' > \"$SASE_CHOP_RESULT_FILE\"\n",
    )
    user_config = tmp_path / "sase.yml"
    user_config.write_text(
        "axe:\n"
        "  job_script_dirs:\n"
        f"    - {scripts_dir}\n"
        "  routines:\n"
        "    checks:\n"
        "      description: Holds the broken job\n"
        "      interval: 5\n"
        "      jobs:\n"
        "        broken:\n"
        "          description: Writes invalid JSON to its result file\n"
        "          script: broken_result\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="user",
            path=str(user_config),
            exists=True,
            list_strategy="replace",
            data=yaml.safe_load(user_config.read_text(encoding="utf-8")),
        ),
    ]
    monkeypatch.setattr("sase.axe.config.load_merged_config", lambda: {})
    monkeypatch.setattr("sase.axe.config.load_config_layers", lambda: layers)

    with (
        override_flags(axe_routine_job_contract=True),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(
            argparse.Namespace(
                chop_name="broken",
                routine=None,
                lumberjack=None,
                dry_run=False,
                chop_verbose=False,
                force=False,
            )
        )

    assert exc_info.value.code == 1
    error_output = capsys.readouterr().err
    assert "job result is not valid JSON" in error_output


def test_bracketed_target_job_name_config_error_uses_canonical_wording(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A job name containing target-instance brackets fails config loading
    with the job-worded Rust validation message, surfacing on every
    ``sase axe job``/``routine`` command."""
    scripts_dir = tmp_path / "scripts"
    make_script(tmp_path, "fixture_success", "true\n")
    user_config = tmp_path / "sase.yml"
    user_config.write_text(
        "axe:\n"
        "  job_script_dirs:\n"
        f"    - {scripts_dir}\n"
        "  routines:\n"
        "    bad-routine:\n"
        "      description: Has an invalid bracketed job name\n"
        "      interval: 5\n"
        "      jobs:\n"
        '        "bad[name]":\n'
        "          description: Invalid bracketed job name\n"
        "          script: fixture_success\n"
        "          for_each:\n"
        "            - name: sase\n"
        "              workspace: gh:sase-org/sase\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="user",
            path=str(user_config),
            exists=True,
            list_strategy="replace",
            data=yaml.safe_load(user_config.read_text(encoding="utf-8")),
        ),
    ]
    monkeypatch.setattr("sase.axe.config.load_merged_config", lambda: {})
    monkeypatch.setattr("sase.axe.config.load_config_layers", lambda: layers)

    with (
        override_flags(axe_routine_job_contract=True),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_list(
            argparse.Namespace(
                axe_subcommand="job",
                json=True,
                available=False,
                verbose=False,
            )
        )

    assert exc_info.value.code == 2
    error_output = capsys.readouterr().err
    assert "job name must not contain target-instance brackets" in error_output
