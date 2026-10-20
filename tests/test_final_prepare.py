"""Host-sealed conditional completion preparation."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from sase.config.tools import ToolCatalog, _ToolCatalogEntry
from sase.core.continuation_facade import bind_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    FinalizerDeclarationError,
    publish_final_context,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.prepare import (
    load_prepared_completion,
    persist_prepared_completion,
    prepare_conditional_completion,
    read_prepare_manifest,
)
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.macro.directives import PromptDirectives
from sase.main.parser import create_parser
from sase.monitor.continuation_delivery import DELIVERY_ARTIFACTS_ENV
from sase.monitor.delivery import HOST_COMPLETION_RECEIPT_FILENAME

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    valid_manifest,
)


def _catalog_entry(name: str, argv: list[str], stages: str) -> _ToolCatalogEntry:
    return _ToolCatalogEntry(
        name=name,
        definition={
            "name": name,
            "argv": list(argv),
            "description": f"test tool {name}",
            "stages": stages,
            "args": "deny",
        },
        digest="digest:" + name,
        diagnostics=(),
    )


def _stub_tool_catalog(
    monkeypatch: pytest.MonkeyPatch, entries: list[_ToolCatalogEntry]
) -> None:
    catalog = ToolCatalog(
        project="test-project", path=None, entries=tuple(entries), diagnostics=()
    )
    monkeypatch.setattr(
        "sase.config.tools.load_project_tool_catalog_at",
        lambda _start: catalog,
    )


@pytest.fixture(autouse=True)
def _run_silent_check_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror the sase checkout's stage-reporting check tools hermetically."""

    monkeypatch.delenv(DELIVERY_ARTIFACTS_ENV, raising=False)
    _stub_tool_catalog(
        monkeypatch,
        [
            _catalog_entry("check", ["just", "check"], "run_silent"),
            _catalog_entry("check-full", ["just", "check-full"], "run_silent"),
            _catalog_entry("install-venv", ["just", "install-venv"], "none"),
        ],
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


def _check_wrapper(publication: Any, command: list[str]) -> dict[str, Any]:
    return {
        "success_message": "Required checks passed.",
        "verification": {"command": list(command)},
        "declaration": valid_manifest(publication),
    }


def _capture_seal_request(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import sase.finalizers._prepare_completion as prepare_module

    captured: dict[str, Any] = {}
    original = prepare_module.seal_conditional_completion

    def spy(request: Any) -> Any:
        captured["request"] = dict(request)
        return original(request)

    monkeypatch.setattr(prepare_module, "seal_conditional_completion", spy)
    return captured


def _prepare_check_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: list[str],
) -> Any:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    return publication, prepare_conditional_completion(
        _check_wrapper(publication, command)
    )


def test_prepare_refuses_check_without_stage_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_tool_catalog(monkeypatch, [])
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    with pytest.raises(FinalizerDeclarationError, match="no stage evidence"):
        prepare_conditional_completion(_check_wrapper(publication, ["just", "check"]))
    try:
        prepare_conditional_completion(_check_wrapper(publication, ["just", "check"]))
    except FinalizerDeclarationError as exc:
        assert "Fallback" in str(exc)
    else:  # pragma: no cover - the match above already requires the refusal.
        raise AssertionError("expected prepare to refuse a stageless check")


def test_sase_check_tools_declare_run_silent_stages() -> None:
    from sase.config.tools import load_project_tool_catalog_at

    root = Path(__file__).resolve().parents[1]
    catalog = load_project_tool_catalog_at(root)
    by_argv = {
        tuple(str(part) for part in (entry.definition.get("argv") or ())): entry
        for entry in catalog.entries
    }
    for argv in (("just", "check"), ("just", "check-full")):
        entry = by_argv.get(argv)
        assert entry is not None, f"sase catalog has no tool for {list(argv)!r}"
        assert str(entry.definition.get("stages") or "none") == "run_silent", (
            f"sase tool {entry.name!r} must declare stages: run_silent"
        )


def test_prepare_seals_run_silent_stage_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_seal_request(monkeypatch)
    _prepare_check_intent(monkeypatch, tmp_path, ["just", "check-full"])

    request = captured["request"]
    assert request["stage_source"] == "run_silent"
    assert request["prior_refusals"] == []


def test_prepare_seals_unnamed_check_as_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_tool_catalog(monkeypatch, [])
    captured = _capture_seal_request(monkeypatch)
    prepare_dirty_declaration(monkeypatch, tmp_path)
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [_observation(repo_id)],
    )
    with pytest.raises(FinalizerDeclarationError, match="no stage evidence"):
        prepare_conditional_completion(_check_wrapper(publication, ["just", "check"]))

    assert captured["request"]["stage_source"] == "none"
    assert captured["request"]["prior_refusals"] == []


def _refused_predecessor_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reason: str,
) -> Any:
    """Prepare once, then point the delivery env at a recovered monitor."""

    _prepare_check_intent(monkeypatch, tmp_path, ["just", "check-full"])
    intent = load_prepared_completion(_latest_intent_ref(tmp_path))
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir()
    (monitor_dir / "agent_meta.json").write_text(
        json.dumps({"monitor_state": "completed", "monitor_exit_code": 0}),
        encoding="utf-8",
    )
    stored = persist_prepared_completion(intent, artifacts_dir=str(monitor_dir))
    (monitor_dir / HOST_COMPLETION_RECEIPT_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "recovery",
                "reason": reason,
                "intent_ref": stored.intent_ref,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(monitor_dir))
    return intent


def _latest_intent_ref(tmp_path: Path) -> str:
    index = json.loads(
        (tmp_path / "continuation" / "completion_intents" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    intents = index["intents"]
    assert len(intents) == 1
    return next(iter(intents))


def test_prepare_refuses_identical_tree_after_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = "missing_required_stage:formatting"
    _refused_predecessor_env(monkeypatch, tmp_path, reason)
    publication = publish_final_context()
    with pytest.raises(FinalizerDeclarationError, match="already refused"):
        prepare_conditional_completion(
            _check_wrapper(publication, ["just", "check-full"])
        )
    try:
        prepare_conditional_completion(
            _check_wrapper(publish_final_context(), ["just", "check-full"])
        )
    except FinalizerDeclarationError as exc:
        assert reason in str(exc)
        assert "Fallback" in str(exc)
    else:  # pragma: no cover - the match above already requires the refusal.
        raise AssertionError("expected re-prepare of a refused tree to fail")


def test_prepare_allows_changed_tree_after_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _refused_predecessor_env(monkeypatch, tmp_path, "missing_required_stage:formatting")
    publication = publish_final_context()
    repo_id = publication.context.obligations[0].obligation_id
    changed = dict(_observation(repo_id))
    changed["head"] = _digest("other-head")
    changed["head_tree"] = _digest("other-head-tree")
    changed["index_tree"] = _digest("other-index-tree")
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: [changed],
    )
    prepared = prepare_conditional_completion(
        _check_wrapper(publication, ["just", "check-full"])
    )

    assert prepared.intent["status"] == "prepared"


def test_prepare_ignores_non_recovery_predecessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_check_intent(monkeypatch, tmp_path, ["just", "check-full"])
    intent = load_prepared_completion(_latest_intent_ref(tmp_path))
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir()
    (monitor_dir / "agent_meta.json").write_text(
        json.dumps({"monitor_state": "completed", "monitor_exit_code": 0}),
        encoding="utf-8",
    )
    stored = persist_prepared_completion(intent, artifacts_dir=str(monitor_dir))
    (monitor_dir / HOST_COMPLETION_RECEIPT_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "intent_ref": stored.intent_ref,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(monitor_dir))

    prepared = prepare_conditional_completion(
        _check_wrapper(publish_final_context(), ["just", "check-full"])
    )

    assert prepared.intent["status"] == "prepared"


def test_prepare_seals_agent_project_from_project_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SASE_AGENT_PROJECT_FILE", "/projects/bob-cli/.sase-project.json"
    )
    _prepare_check_intent(monkeypatch, tmp_path, ["just", "check-full"])

    intent = load_prepared_completion(_latest_intent_ref(tmp_path))

    assert intent["seal"]["creator"]["project"] == "bob-cli"


def test_prepare_falls_back_to_sase_project_without_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("SASE_AGENT_PROJECT_FILE", "SASE_PROJECT", "SASE_PROJECT_NAME"):
        monkeypatch.delenv(key, raising=False)
    _prepare_check_intent(monkeypatch, tmp_path, ["just", "check-full"])

    intent = load_prepared_completion(_latest_intent_ref(tmp_path))

    assert intent["seal"]["creator"]["project"] == "sase"
