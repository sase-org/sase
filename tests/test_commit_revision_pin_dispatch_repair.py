"""Pin follow after the repair-remaining handoff."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerObligationWire,
)
from sase.finalizers import commit_dispatch as dispatch_mod
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.declaration_store import (
    HostRepositoryRecord,
    repository_state_digest,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

# A conflict-repaired pinned sibling lands before main. The host pin write
# must happen after the repair handoff validates the main obligation, so the
# host's own write never trips "repository obligation changed after submit".

_PIN_REL = "sase-core-revision.txt"
_OLD_SHA = "b" * 40
_NEW_SHA = "a" * 40


def _pin_repair_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Build the two-checkout world for pin-plus-repair dispatch tests."""
    import sase.finalizers.commit_revision_pin as pin_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    pin_path = primary / _PIN_REL
    pin_path.write_text(_OLD_SHA + "\n", encoding="utf-8")

    monkeypatch.setattr(
        dispatch_mod,
        "_revision_pins_for_project",
        lambda _project_dir: {"sase-core": _PIN_REL},
    )
    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)

    main = DirtyRepo(
        name="main", path=str(primary), changed_files=("app.py",), kind="main"
    )
    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    return {
        "primary": primary,
        "sibling_dir": sibling_dir,
        "artifacts": artifacts,
        "pin_path": pin_path,
        "main": main,
        "sibling": sibling,
        "main_id": repository_decision_id(main),
    }


def _append_marker(artifacts: Path, repo: DirtyRepo, sha: str) -> None:
    path = artifacts / "commit_results.json"
    try:
        markers = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        markers = []
    markers.append(
        {"cwd": repo.path, "result": "ok", "commit_sha": sha, "commit_tree": "d" * 40}
    )
    path.write_text(json.dumps(markers), encoding="utf-8")


def _install_repair_declaration(
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_id: str,
    main_path: str,
    submitted_files: Sequence[str],
    defer_main: bool = False,
) -> None:
    """Install the repair turn's fresh declaration for the remaining main repo."""
    submitted = DirtyRepo(
        name="main", path=main_path, changed_files=tuple(submitted_files), kind="main"
    )
    envelope = {
        "payloads": [
            {
                "instance_id": "commit",
                "payload": {
                    "repositories": [
                        {
                            "repo_id": main_id,
                            "action": "commit",
                            "message": "fix: main after repair",
                        }
                    ]
                },
            }
        ]
    }
    accepted_context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest="0" * 64,
        obligations=[
            FinalizerObligationWire(
                obligation_id=main_id,
                kind="repository",
                display_name="main",
                paths=list(submitted_files),
                digest=repository_state_digest(
                    main_id, submitted, list(submitted_files)
                ),
            )
        ],
    )
    host_records = (
        HostRepositoryRecord(
            obligation_id=main_id,
            kind="main",
            name="main",
            path=main_path,
        ),
    )
    deferrals: tuple[Any, ...] = ()
    if defer_main:
        deferrals = (
            {
                "instance_id": "commit",
                "repo_id": main_id,
                "reason": "foreign_work",
                "paths": ["app.py"],
            },
        )
    monkeypatch.setattr(
        dispatch_mod,
        "load_accepted_commit_declaration",
        lambda _artifacts_dir: (envelope, accepted_context, host_records, deferrals),
    )


def _run_pin_repair_dispatch(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    *,
    repair_extra_main_files: Sequence[str] = (),
    defer_main: bool = False,
) -> Any:
    """Dispatch sibling-conflict repair; return the result or raise."""
    artifacts: Path = world["artifacts"]
    pin_path: Path = world["pin_path"]
    main: DirtyRepo = world["main"]
    sibling: DirtyRepo = world["sibling"]
    live: dict[str, Any] = {"main_files": ["app.py"], "main_committed": False}

    def _live_main_files() -> list[str]:
        if live["main_committed"]:
            return []
        files = list(live["main_files"])
        try:
            current_pin = pin_path.read_text(encoding="utf-8")
        except OSError:
            current_pin = ""
        if current_pin != _OLD_SHA + "\n" and _PIN_REL not in files:
            files.append(_PIN_REL)
        return files

    def _prepare(_project_dir: str, _artifacts: Any) -> PreparedCommitDirtyState:
        files = _live_main_files()
        repos = (
            (
                DirtyRepo(
                    name="main",
                    path=str(world["primary"]),
                    changed_files=tuple(files),
                    kind="main",
                ),
            )
            if files
            else ()
        )
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(
                project_dir=str(world["primary"]),
                repos=repos,
                details="dirty" if repos else "clean",
            )
        )

    order: list[str] = []
    resume_calls: list[str] = []

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        order.append(repo.name)
        if repo.name == "sase-core" and order.count("sase-core") == 1:
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        _append_marker(artifacts, repo, _NEW_SHA if repo.name == "main" else "c" * 40)
        if repo.name == "main":
            live["main_committed"] = True
        return StitchCommandResult(returncode=0, stdout="ok\n", stderr="")

    def resume_runner(
        repo: DirtyRepo, _context: object, **kwargs: Any
    ) -> StitchCommandResult:
        resume_calls.append(repo.name)
        return StitchCommandResult(returncode=0, stdout="resumed\n", stderr="")

    provider = MagicMock()
    provider.is_sync_in_progress.return_value = False
    provider.get_conflicted_files.return_value = []

    def on_invoke(_prompt: str, **_kwargs: Any) -> InvokeResult:
        # The repair turn lands the sibling, then submits a fresh declaration
        # for main that does not include the host-owned pin path.
        _append_marker(artifacts, sibling, _NEW_SHA)
        live["main_files"] = ["app.py", *repair_extra_main_files]
        _install_repair_declaration(
            monkeypatch,
            main_id=world["main_id"],
            main_path=str(world["primary"]),
            submitted_files=["app.py"],
            defer_main=defer_main,
        )
        return InvokeResult(content="repaired sibling")

    provider.invoke.side_effect = on_invoke

    result = dispatch_commit_decisions(
        (main, sibling),
        {
            world["main_id"]: {"action": "commit", "message": "feat: x"},
            repository_decision_id(sibling): {
                "action": "commit",
                "message": "feat: core",
                "bead_action": "keep",
            },
        },
        state=_prepare(str(world["primary"]), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="0" * 64,
            run_id="run-1",
            agent_id="agent-1",
            turn_nonce="nonce-1",
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(world["primary"]),
        provider=provider,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,  # type: ignore[arg-type]
        resume_runner=resume_runner,  # type: ignore[arg-type]
        ledger=InstanceLedger(instance_id="commit", max_attempts=4),
        prepare_dirty_state=_prepare,  # type: ignore[arg-type]
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda path, _protected: (
            _live_main_files() if path == str(world["primary"]) else []
        ),
        baseline_record_resolver=lambda _artifacts, _path: None,
    )
    assert resume_calls == []
    assert order[0] == "sase-core"
    return result


def test_pin_follow_after_repair_handoff_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _pin_repair_world(tmp_path, monkeypatch)
    result = _run_pin_repair_dispatch(world, monkeypatch)

    assert (world["pin_path"]).read_text(encoding="utf-8") == _NEW_SHA + "\n"
    pin_evidence = [
        item.value for item in result.evidence if item.kind == "revision_pin"
    ]
    assert len(pin_evidence) == 1
    assert _NEW_SHA[:12] in pin_evidence[0]
    assert "->" in pin_evidence[0]
    assert not any(item.code == "revision_pin_skipped" for item in result.diagnostics)
    assert any(item.kind == "repair_handoff_declaration" for item in result.evidence)


def test_pin_follow_after_repair_handoff_keeps_stale_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _pin_repair_world(tmp_path, monkeypatch)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _run_pin_repair_dispatch(
            world, monkeypatch, repair_extra_main_files=("extra.txt",)
        )

    assert "changed after submit" in str(exc_info.value)
    # The host pin write never ran: the guard caught the repair turn's own edit.
    assert (world["pin_path"]).read_text(encoding="utf-8") == _OLD_SHA + "\n"


def test_pin_follow_after_repair_handoff_skips_deferred_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _pin_repair_world(tmp_path, monkeypatch)
    result = _run_pin_repair_dispatch(world, monkeypatch, defer_main=True)

    assert (world["pin_path"]).read_text(encoding="utf-8") == _OLD_SHA + "\n"
    pin_evidence = [
        item.value for item in result.evidence if item.kind == "revision_pin"
    ]
    assert len(pin_evidence) == 1
    assert "skipped:main-deferred-or-not-dirty" in pin_evidence[0]
    assert any(item.code == "revision_pin_skipped" for item in result.diagnostics)
    assert any(
        item.kind == "deferred_repo" and item.value.startswith("main:")
        for item in result.evidence
    )
