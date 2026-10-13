"""Host-sealed conditional completion preparation."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess

import pytest

from sase.core.continuation_facade import bind_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    publish_final_context,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.prepare import (
    prepare_conditional_completion,
    read_prepare_manifest,
)
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.macro.directives import PromptDirectives
from sase.main.parser import create_parser

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _observation(
    repo_id: str,
    *,
    name: str = "main",
    kind: str = "main",
    path: str = "src/app.py",
    protected: bool = False,
) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "kind": kind,
        "name": name,
        "head": _digest("head"),
        "head_tree": _digest("head-tree"),
        "index_tree": _digest("index-tree"),
        "complete": True,
        "paths": [
            {
                "path": path,
                "xy": "M",
                "content_hash": _digest("app"),
                "mode": "100644",
                "kind": "untracked" if protected else "file",
                "protected": protected,
                "foreign": False,
            }
        ],
    }


def test_final_parser_registers_prepare() -> None:
    parser = create_parser(only="final")
    args = parser.parse_args(["final", "prepare", "completion.json", "-j"])

    assert args.final_subcommand == "prepare"
    assert args.manifest == "completion.json"
    assert args.json is True


def test_prepare_seals_an_intent_without_submitting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    wrapper = {
        "success_message": "Required checks passed.",
        "verification": {"command": ["just", "check-full"]},
        "declaration": valid_manifest(publication),
    }

    prepared = prepare_conditional_completion(wrapper)

    assert prepared.intent["status"] == "prepared"
    assert prepared.intent_ref
    assert prepared.preview["success_action"] == "complete"
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_prepared_completion_observes_absorbed_raw_commit_and_binds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prepared completion observes the absorbed HEAD/index and keeps obligations."""

    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "SASE Test")
    git("config", "user.email", "sase-test@example.invalid")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")
    baseline_head = git("rev-parse", "HEAD")

    from .finalizers_protocol_harness_test_helpers import prepare_agent_env
    from sase.llm_provider import commit_finalizer_git as finalizer_git

    prepare_agent_env(monkeypatch, artifacts, repo)

    def build_commit_details(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed = finalizer_git.git_changed_files(project_dir)
        if not changed:
            return False, [], "", ""
        return (
            True,
            changed,
            "commit",
            "Uncommitted changes detected:\n" + "\n".join(changed),
        )

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build_commit_details,
    )
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    capture_dirty_baseline(str(repo), str(artifacts))
    (repo / "raw.txt").write_text("raw work\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "agent raw commit")

    publication = publish_final_context(artifacts_dir=str(artifacts))
    assert len(publication.context.obligations) == 1
    repo_id = publication.context.obligations[0].obligation_id
    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed.",
            "verification": {"command": ["just", "check"]},
            "declaration": valid_manifest(publication),
        },
        artifacts_dir=str(artifacts),
    )

    observed = next(
        item for item in prepared.intent["observations"] if item["repo_id"] == repo_id
    )
    assert observed["head"] == baseline_head
    assert observed["head_tree"] == git("rev-parse", f"{baseline_head}^{{tree}}")
    assert observed["index_tree"] != observed["head_tree"]
    assert [path["path"] for path in observed["paths"]] == ["raw.txt"]
    declaration_repos = prepared.intent["declaration"]["payloads"][0]["payload"][
        "repositories"
    ]
    assert [item["repo_id"] for item in declaration_repos] == [repo_id]

    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared.intent,
            "monitor_id": "monitor-1",
            "command": ["just", "check"],
            "request_fingerprint": "sha256:prepared-absorption",
        }
    )
    assert bound["status"] == "bound"
    assert [
        item["repo_id"]
        for item in bound["declaration"]["payloads"][0]["payload"]["repositories"]
    ] == [repo_id]


def test_prepare_rejects_missing_repository_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.declaration import FinalizerDeclarationError

    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    manifest = valid_manifest(publication)
    manifest["payloads"][0]["payload"]["repositories"] = []  # type: ignore[index]

    with pytest.raises(FinalizerDeclarationError, match="missing repository decisions"):
        prepare_conditional_completion(
            {
                "success_message": "Required checks passed.",
                "verification": {"command": ["just", "check-full"]},
                "declaration": manifest,
            }
        )
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_prepare_ignores_protected_prompt_archive_sidecar_without_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [
            _observation(repo_id),
            _observation(
                "repo-agents",
                name="agents",
                kind="sibling",
                path="files/objects/sha256/40/40de62",
                protected=True,
            ),
        ],
    )

    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed.",
            "verification": {"command": ["just", "check-full"]},
            "declaration": valid_manifest(publication),
        }
    )

    assert [item["repo_id"] for item in prepared.intent["observations"]] == [
        repo_id,
        "repo-agents",
    ]


def test_prepare_rejects_protected_decided_repository_with_its_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.declaration import FinalizerDeclarationError

    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id, protected=True)],
    )

    with pytest.raises(FinalizerDeclarationError, match="main"):
        prepare_conditional_completion(
            {
                "success_message": "Required checks passed.",
                "verification": {"command": ["just", "check-full"]},
                "declaration": valid_manifest(publication),
            }
        )


def test_read_prepare_manifest_from_file(tmp_path: Path) -> None:
    path = tmp_path / "completion.json"
    path.write_text(
        '{"success_message": "ok", "verification": {"command": ["just", "check"]}, '
        '"declaration": {"payloads": []}}',
        encoding="utf-8",
    )

    payload = read_prepare_manifest(str(path))

    assert payload["success_message"] == "ok"
