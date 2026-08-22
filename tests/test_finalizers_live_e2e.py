"""Live finalizer acceptance against disposable Git repositories.

These tests drive the generic controller through real dirty-state discovery,
real git commits, and local bare remotes. Stitch dispatch uses a real-git
runner rather than the full CommitWorkflow so the suite stays hermetic.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import (
    MONITOR_PENDING_MARKER,
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
)
from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    FinalizerDeclarationError,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.providers import FinalizerProviderRecord
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives
from tests.llm_provider._commit_finalizer_sibling_helpers import (
    add_origin,
    init_bare_remote,
    mark_opened_external,
)

_PLUGIN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "finalizer_plugin"
_PLUGIN_REF = "example-finalizers@audit"


def _run_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _init_live_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _run_git(path, "init", "-b", "main", "-q")
    _run_git(path, "config", "user.name", "SASE Live Test")
    _run_git(path, "config", "user.email", "sase-live@example.invalid")
    (path / ".gitignore").write_text(".sase/\n", encoding="utf-8")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    _run_git(path, "add", ".gitignore", "README.md")
    _run_git(path, "commit", "-q", "-m", "initial")
    return path


def _attach_bare_remote(repo: Path, remote: Path) -> None:
    init_bare_remote(remote)
    add_origin(repo, remote)
    _run_git(repo, "push", "-q", "-u", "origin", "HEAD")


def _isolate_host_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "empty-config"
    config_dir.mkdir()
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core._include_local_config", False)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))


def _prepare_live_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    repo: Path,
) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))
    monkeypatch.chdir(repo)


def _use_config(monkeypatch: pytest.MonkeyPatch, config: FinalizerConfig) -> None:
    def loader() -> FinalizerConfig:
        return config

    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.controller.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.executor.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", loader)


def _commit_instance() -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def _command_instance(
    instance_id: str,
    command: list[str],
    *,
    after: tuple[str, ...] = (),
) -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id=instance_id,
        provider_ref="builtin@command",
        after=after,
        config={
            "command": command,
            "cwd": "primary",
            "timeout": "5s",
            "submission": "none",
        },
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def _audit_instance() -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id="audit",
        provider_ref=_PLUGIN_REF,
        after=("local-check",),
        config={"env": ["PYTHONPATH"]},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def _config_for(
    instances: dict[str, ConfiguredFinalizerInstance],
    defaults: tuple[str, ...],
) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=defaults,
        required=(),
        instances=instances,
        provenance={},
    )


def _append_commit_result(
    artifacts_dir: str | None,
    repo_path: str,
    sha: str,
    tree: str,
) -> None:
    if not artifacts_dir:
        return
    path = Path(artifacts_dir) / "commit_results.json"
    payload: list[dict[str, Any]] = []
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload.append(
        {
            "cwd": repo_path,
            "result": sha,
            "commit_sha": sha,
            "commit_tree": tree,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _real_git_stitch(
    repo: DirtyRepo,
    message: str,
    excludes: tuple[str, ...],
    context: object,
) -> StitchCommandResult:
    excluded = set(excludes)
    to_commit = [path for path in git_changed_files(repo.path) if path not in excluded]
    if not to_commit:
        return StitchCommandResult(returncode=1, stderr="nothing to commit\n")
    added = subprocess.run(
        ["git", "add", "--", *to_commit],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        return StitchCommandResult(
            returncode=added.returncode,
            stdout=added.stdout,
            stderr=added.stderr,
        )
    committed = subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if committed.returncode != 0:
        return StitchCommandResult(
            returncode=committed.returncode,
            stdout=committed.stdout,
            stderr=committed.stderr,
        )
    pushed = subprocess.run(
        ["git", "push", "-q", "origin", "HEAD"],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if pushed.returncode != 0:
        return StitchCommandResult(
            returncode=pushed.returncode,
            stdout=pushed.stdout,
            stderr=pushed.stderr,
        )
    sha = _run_git(Path(repo.path), "rev-parse", "HEAD").stdout.strip()
    tree = _run_git(Path(repo.path), "rev-parse", "HEAD^{tree}").stdout.strip()
    artifacts_dir = getattr(context, "artifacts_dir", None)
    _append_commit_result(artifacts_dir, repo.path, sha, tree)
    return StitchCommandResult(returncode=0, stdout=f"{sha}\n")


def _use_real_git_stitch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", _real_git_stitch)
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_resume",
        lambda repo, context: _real_git_stitch(
            repo,
            "fix(final): resume conflicted stitch",
            (),
            context,
        ),
    )


def _submit_from_context(artifacts: Path, *, action: str = "commit") -> None:
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for item in manifest.get("payloads", []):
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            if item.get("instance_id") == "audit" and payload == {}:
                item["payload"] = {"note": "live-audit"}
            continue
        for decision in repositories:
            decision["action"] = action
            if action == "commit":
                decision["message"] = "fix(final): live acceptance commit"
            else:
                decision.pop("message", None)
                decision["reason"] = "not mine"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def _run_controller(artifacts: Path, provider: MagicMock | None = None) -> InvokeResult:
    return run_finalizers(
        provider=provider or MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def _write_plugin_site(site: Path) -> None:
    site.mkdir(parents=True)
    (site / "example_finalizers.py").write_text(
        (_PLUGIN_FIXTURE / "example_finalizers.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    dist = site / "example_finalizers-1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-finalizers\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        "[sase_finalizers]\naudit = example_finalizers:provider\n",
        encoding="utf-8",
    )


def _advertise_plugin(
    monkeypatch: pytest.MonkeyPatch,
    site: Path,
) -> None:
    from sase.finalizers.providers import collect_finalizer_providers as original

    monkeypatch.syspath_prepend(str(site))
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = str(site) if not existing else str(site) + os.pathsep + existing
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    plugin = FinalizerProviderRecord(
        provider_ref=_PLUGIN_REF,
        provider_id="audit",
        package="example-finalizers",
        version="1.0.0",
        entry_point="example_finalizers:provider",
        builtin=False,
        capabilities=("describe", "validate", "execute", "verify"),
        load_status="ok",
    )
    builtins = tuple(item for item in original() if item.builtin)

    def providers() -> tuple[FinalizerProviderRecord, ...]:
        return (*builtins, plugin)

    monkeypatch.setattr(
        "sase.finalizers.providers.collect_finalizer_providers", providers
    )
    monkeypatch.setattr(
        "sase.finalizers.executor.collect_finalizer_providers", providers
    )
    monkeypatch.setattr(
        "sase.finalizers.plan.diagnose_finalizer_providers",
        lambda *_args, **_kwargs: (),
    )


def _load_result(artifacts: Path) -> dict[str, Any]:
    return json.loads((artifacts / "finalizer_result.json").read_text(encoding="utf-8"))


def test_live_clean_completion_has_no_recovery_or_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="done")
    provider.resolve_model_name.return_value = "model"
    monkeypatch.setattr(
        "sase.llm_provider._invoke.get_provider",
        lambda *_args, **_kwargs: provider,
    )

    result = invoke_agent(
        "do work",
        agent_type="test",
        suppress_output=True,
        artifacts_dir=str(artifacts),
        skip_preprocessing=True,
        directives=PromptDirectives(),
    )

    assert result.content == "done"
    provider.invoke.assert_called_once()
    payload = _load_result(artifacts)
    assert payload["status"] == "success"
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    assert not (artifacts / "commit_results.json").exists()
    assert _run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_live_dirty_commit_excludes_protected_baseline_and_pushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "starter.txt").write_text("pre-existing\n", encoding="utf-8")
    capture_dirty_baseline(str(repo), str(artifacts))
    (repo / "agent.py").write_text("print('agent')\n", encoding="utf-8")
    _use_real_git_stitch(monkeypatch)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _submit_from_context(artifacts)
    result = _run_controller(artifacts)

    assert result.content == "done"
    payload = _load_result(artifacts)
    assert payload["status"] == "success"
    assert git_changed_files(str(repo)) == ["starter.txt"]
    assert (repo / "agent.py").read_text(encoding="utf-8") == "print('agent')\n"
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert len(markers) == 1
    remote_sha = _run_git(
        tmp_path / "remote.git", "rev-parse", "refs/heads/main"
    ).stdout.strip()
    assert markers[0]["commit_sha"] == remote_sha
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()


def test_live_manual_stitch_before_submit_rejects_stale_context_then_finishes_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('manual')\n", encoding="utf-8")
    _use_real_git_stitch(monkeypatch)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for item in manifest["payloads"]:
        payload = item["payload"]
        for decision in payload.get("repositories", []):
            decision["message"] = "fix(final): live acceptance commit"

    context = type("Context", (), {"artifacts_dir": str(artifacts)})()
    stitch_result = _real_git_stitch(
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
    result = _run_controller(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    payload = _load_result(artifacts)
    assert payload["status"] == "success"
    assert "dirty_work_discarded" not in json.dumps(payload)
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    assert _run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_live_final_none_skips_commit_on_dirty_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('skip')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    _, directives = extract_prompt_directives("%final:none\nDo work")

    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    result = _run_controller(artifacts)

    assert result.content == "done"
    payload = _load_result(artifacts)
    assert payload["status"] == "success"
    assert payload["instances"] == []
    runner.assert_not_called()
    assert git_changed_files(str(repo)) == ["agent.py"]


def test_live_command_and_fixture_plugin_run_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    site = tmp_path / "plugin-site"
    _write_plugin_site(site)
    _advertise_plugin(monkeypatch, site)
    config = _config_for(
        {
            "commit": _commit_instance(),
            "local-check": _command_instance(
                "local-check",
                [sys.executable, "-c", "print('checked')"],
                after=("commit",),
            ),
            "audit": _audit_instance(),
        },
        ("commit", "local-check", "audit"),
    )
    _use_config(monkeypatch, config)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    plan = json.loads((artifacts / "finalizer_plan.json").read_text(encoding="utf-8"))
    assert [entry["instance_id"] for entry in plan["plan"]["entries"]] == [
        "commit",
        "local-check",
        "audit",
    ]
    _submit_from_context(artifacts)
    result = _run_controller(artifacts)

    assert result.content == "done"
    payload = _load_result(artifacts)
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


def test_live_refusal_preserves_dirty_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.commit import BuiltinCommitFinalizerError

    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('keep')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _submit_from_context(artifacts, action="refuse")
    with pytest.raises(BuiltinCommitFinalizerError, match="not mine"):
        _run_controller(artifacts)

    runner.assert_not_called()
    payload = _load_result(artifacts)
    assert payload["status"] == "refused"
    assert payload["instances"][0]["refusal_reason"] == "not mine"
    assert git_changed_files(str(repo)) == ["agent.py"]
    assert _run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_live_stale_post_submit_edit_recovers_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('first')\n", encoding="utf-8")
    _use_real_git_stitch(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _submit_from_context(artifacts)
    (repo / "agent.py").write_text("print('edited-after-submit')\n", encoding="utf-8")

    provider = MagicMock()

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        _submit_from_context(artifacts)
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    result = _run_controller(artifacts, provider)

    assert "recovered" in result.content
    provider.invoke.assert_called_once()
    payload = _load_result(artifacts)
    assert payload["status"] == "success"
    assert git_changed_files(str(repo)) == []
    assert "edited-after-submit" in (repo / "agent.py").read_text(encoding="utf-8")
    assert (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).is_file()


def test_live_later_finalizer_dirt_reactivates_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    _use_real_git_stitch(monkeypatch)
    config = _config_for(
        {
            "commit": _commit_instance(),
            "mutate": _command_instance(
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
    _use_config(monkeypatch, config)
    provider = MagicMock()

    def recover(*_args: object, **_kwargs: object) -> InvokeResult:
        _submit_from_context(artifacts)
        return InvokeResult(content="recovered")

    provider.invoke.side_effect = recover
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    result = _run_controller(artifacts, provider)

    assert "recovered" in result.content
    payload = _load_result(artifacts)
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
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    other = _init_live_repo(tmp_path / "other")
    _attach_bare_remote(repo, tmp_path / "repo.git")
    _attach_bare_remote(other, tmp_path / "other.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
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
        return _real_git_stitch(repo_arg, message, excludes, context)

    def resume(repo_arg: DirtyRepo, context: object) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        return _real_git_stitch(
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
    _submit_from_context(artifacts)
    result = _run_controller(artifacts, provider)

    assert "repaired" in result.content
    assert seen[0] == "create:main"
    assert "resume:main" in seen
    assert seen[-1] == "create:research"
    assert git_changed_files(str(repo)) == []
    assert git_changed_files(str(other)) == []
    payload = _load_result(artifacts)
    assert payload["status"] == "success"


def test_live_intentional_handoffs_skip_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate_host_config(monkeypatch, tmp_path)
    repo = _init_live_repo(tmp_path / "repo")
    _attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    _prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('handoff')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    provider = MagicMock()

    for marker in (
        PLAN_PENDING_MARKER,
        MONITOR_PENDING_MARKER,
        QUESTIONS_PENDING_MARKER,
    ):
        (artifacts / marker).write_text("1\n", encoding="utf-8")
        result = _run_controller(artifacts, provider)
        assert result.content == "done"
        (artifacts / marker).unlink()

    provider.invoke.assert_not_called()
    runner.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert git_changed_files(str(repo)) == ["agent.py"]
