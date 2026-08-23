"""Live finalizer controller cycles against disposable Git repositories.

Covers stale-context rejection, declaration recovery, later-finalizer dirt,
plugin ordering, and multi-repo stitch resume.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from sase.xprompt.directives import PromptDirectives
from tests.llm_provider._commit_finalizer_sibling_helpers import mark_opened_external

from .finalizers_live_e2e_test_helpers import (
    advertise_plugin,
    attach_bare_remote,
    audit_instance,
    commit_instance,
    command_instance,
    config_for,
    init_live_repo,
    isolate_host_config,
    load_result,
    prepare_live_env,
    real_git_stitch,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
    use_real_git_stitch,
    write_plugin_site,
)


def test_live_manual_stitch_before_submit_rejects_stale_context_then_finishes_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('manual')\n", encoding="utf-8")
    use_real_git_stitch(monkeypatch)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for item in manifest["payloads"]:
        payload = item["payload"]
        for decision in payload.get("repositories", []):
            decision["message"] = "fix(final): live acceptance commit"

    context = type("Context", (), {"artifacts_dir": str(artifacts)})()
    stitch_result = real_git_stitch(
        DirtyRepo(
            name="main",
            path=str(repo),
            changed_files=("agent.py",),
            kind="main",
        ),
        "fix(final): manual pre-submit commit",
        (),
        context,
    )
    assert stitch_result.returncode == 0
    assert git_changed_files(str(repo)) == []

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_final_manifest(manifest, artifacts_dir=str(artifacts))

    assert exc_info.value.code == "stale_final_context"
    assert not (artifacts / FINAL_SUBMISSION_FILENAME).exists()
    attempts = [
        json.loads(line)
        for line in (artifacts / FINAL_SUBMISSION_ATTEMPTS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert attempts[-1]["accepted"] is False
    assert attempts[-1]["code"] == "stale_final_context"

    refreshed = publish_final_context(artifacts_dir=str(artifacts))
    assert refreshed.submission_required is False
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="should-not-recover")
    result = run_controller(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert "dirty_work_discarded" not in json.dumps(payload)
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_live_command_and_fixture_plugin_run_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    site = tmp_path / "plugin-site"
    write_plugin_site(site)
    advertise_plugin(monkeypatch, site)
    config = config_for(
        {
            "commit": commit_instance(),
            "local-check": command_instance(
                "local-check",
                [sys.executable, "-c", "print('checked')"],
                after=("commit",),
            ),
            "audit": audit_instance(),
        },
        ("commit", "local-check", "audit"),
    )
    use_config(monkeypatch, config)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    plan = json.loads((artifacts / "finalizer_plan.json").read_text(encoding="utf-8"))
    assert [entry["instance_id"] for entry in plan["plan"]["entries"]] == [
        "commit",
        "local-check",
        "audit",
    ]
    submit_from_context(artifacts)
    result = run_controller(artifacts)

    assert result.content == "done"
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert [item["instance_id"] for item in payload["instances"]] == [
        "commit",
        "local-check",
        "audit",
    ]
    stdout = artifacts / "finalizers" / "local-check" / "attempt-1.stdout"
    assert stdout.read_text(encoding="utf-8").strip() == "checked"
    audit_evidence = payload["instances"][2]["evidence"]
    kinds = {item["kind"]: item["value"] for item in audit_evidence}
    assert kinds["reference"] == "non-mutating"
    assert kinds["payload_note"] == "live-audit"
    assert not (artifacts / "commit_results.json").exists()


def test_live_stale_post_submit_edit_recovers_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('first')\n", encoding="utf-8")
    use_real_git_stitch(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    (repo / "agent.py").write_text("print('edited-after-submit')\n", encoding="utf-8")

    provider = MagicMock()

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        submit_from_context(artifacts)
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    result = run_controller(artifacts, provider)

    assert "recovered" in result.content
    provider.invoke.assert_called_once()
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert git_changed_files(str(repo)) == []
    assert "edited-after-submit" in (repo / "agent.py").read_text(encoding="utf-8")
    assert (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).is_file()


def test_live_later_finalizer_dirt_reactivates_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    use_real_git_stitch(monkeypatch)
    config = config_for(
        {
            "commit": commit_instance(),
            "mutate": command_instance(
                "mutate",
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('late.py').write_text('late\\n')",
                ],
                after=("commit",),
            ),
        },
        ("commit", "mutate"),
    )
    use_config(monkeypatch, config)
    provider = MagicMock()

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        submit_from_context(artifacts)
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    result = run_controller(artifacts, provider)

    assert "recovered" in result.content
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert payload["cycles"] >= 2
    assert git_changed_files(str(repo)) == []
    assert (repo / "late.py").read_text(encoding="utf-8") == "late\n"
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert len(markers) == 1


def test_live_first_repo_conflict_blocks_second_then_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    other = init_live_repo(tmp_path / "other")
    attach_bare_remote(repo, tmp_path / "repo.git")
    attach_bare_remote(other, tmp_path / "other.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    mark_opened_external(monkeypatch, artifacts, "research", other)
    (repo / "main.py").write_text("print('main')\n", encoding="utf-8")
    (other / "side.py").write_text("print('side')\n", encoding="utf-8")
    first_create = {"used": False}
    seen: list[str] = []

    def stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        seen.append(f"create:{repo_arg.name}")
        if repo_arg.name == "main" and not first_create["used"]:
            first_create["used"] = True
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        return real_git_stitch(repo_arg, message, excludes, context)

    def resume(repo_arg: DirtyRepo, context: object) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        return real_git_stitch(
            repo_arg,
            "fix(final): resume conflicted stitch",
            (),
            context,
        )

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired")

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    result = run_controller(artifacts, provider)

    assert "repaired" in result.content
    assert seen[0] == "create:main"
    assert "resume:main" in seen
    assert seen[-1] == "create:research"
    assert git_changed_files(str(repo)) == []
    assert git_changed_files(str(other)) == []
    payload = load_result(artifacts)
    assert payload["status"] == "success"
