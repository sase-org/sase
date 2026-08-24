"""Shared helpers for live finalizer acceptance tests.

These helpers drive real git repositories, local bare remotes, and stitch
dispatch without going through the full CommitWorkflow.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.providers import FinalizerProviderRecord
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from tests.llm_provider._commit_finalizer_sibling_helpers import (
    add_origin,
    init_bare_remote,
)

PLUGIN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "finalizer_plugin"
PLUGIN_REF = "example-finalizers@audit"


def run_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def init_live_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    run_git(path, "init", "-b", "main", "-q")
    run_git(path, "config", "user.name", "SASE Live Test")
    run_git(path, "config", "user.email", "sase-live@example.invalid")
    (path / ".gitignore").write_text(".sase/\n", encoding="utf-8")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    run_git(path, "add", ".gitignore", "README.md")
    run_git(path, "commit", "-q", "-m", "initial")
    return path


def attach_bare_remote(repo: Path, remote: Path) -> None:
    init_bare_remote(remote)
    add_origin(repo, remote)
    run_git(repo, "push", "-q", "-u", "origin", "HEAD")


def isolate_host_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "empty-config"
    config_dir.mkdir()
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core._include_local_config", False)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))


def prepare_live_env(
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


def use_config(monkeypatch: pytest.MonkeyPatch, config: FinalizerConfig) -> None:
    def loader() -> FinalizerConfig:
        return config

    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.controller.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.executor.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", loader)


def commit_instance() -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def command_instance(
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


def audit_instance() -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id="audit",
        provider_ref=PLUGIN_REF,
        after=("local-check",),
        config={"env": ["PYTHONPATH"]},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )


def config_for(
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


def real_git_stitch(
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
    sha = run_git(Path(repo.path), "rev-parse", "HEAD").stdout.strip()
    tree = run_git(Path(repo.path), "rev-parse", "HEAD^{tree}").stdout.strip()
    artifacts_dir = getattr(context, "artifacts_dir", None)
    _append_commit_result(artifacts_dir, repo.path, sha, tree)
    return StitchCommandResult(returncode=0, stdout=f"{sha}\n")


def use_real_git_stitch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", real_git_stitch)
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_resume",
        lambda repo, context: real_git_stitch(
            repo,
            "fix(final): resume conflicted stitch",
            (),
            context,
        ),
    )


def submit_from_context(artifacts: Path, *, action: str = "commit") -> None:
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


def submit_deferral_from_context(
    artifacts: Path,
    *,
    reason: str,
    paths: list[str],
) -> dict[str, Any]:
    """Submit a commit with one typed deferral for the sole repository obligation."""
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = next(
        obligation.obligation_id
        for obligation in publication.context.obligations
        if obligation.kind == "repository"
    )
    manifest = deepcopy(publication.payload["manifest_template"])
    for item in manifest.get("payloads", []):
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            decision["action"] = "commit"
            decision["message"] = "chore(final): defer pending review"
        payload["deferrals"].append(
            {"repo_id": repo_id, "reason": reason, "paths": paths}
        )
    return submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def run_controller(artifacts: Path, provider: MagicMock | None = None) -> InvokeResult:
    return run_finalizers(
        provider=provider or MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def write_plugin_site(site: Path) -> None:
    site.mkdir(parents=True)
    (site / "example_finalizers.py").write_text(
        (PLUGIN_FIXTURE / "example_finalizers.py").read_text(encoding="utf-8"),
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


def advertise_plugin(
    monkeypatch: pytest.MonkeyPatch,
    site: Path,
) -> None:
    from sase.finalizers.providers import collect_finalizer_providers as original

    monkeypatch.syspath_prepend(str(site))
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = str(site) if not existing else str(site) + os.pathsep + existing
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    plugin = FinalizerProviderRecord(
        provider_ref=PLUGIN_REF,
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


def load_result(artifacts: Path) -> dict[str, Any]:
    return json.loads((artifacts / "finalizer_result.json").read_text(encoding="utf-8"))
