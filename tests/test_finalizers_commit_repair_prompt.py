"""Regression coverage for builtin@commit conflict-repair prompt wording."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit_repair import _artifact_label, _run_conflict_repair_turn
from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def _capture_conflict_repair_prompt(
    tmp_path: Path,
    repo: DirtyRepo,
) -> str:
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    artifacts_dir = tmp_path / "artifacts"

    _run_conflict_repair_turn(
        provider=provider,
        invoke_result=InvokeResult(content="initial"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
        options=None,
        repo=repo,
    )

    prompt = provider.invoke.call_args.args[0]
    artifact_dir = artifacts_dir / "finalizers" / "commit"
    saved_prompt = (
        artifact_dir / f"conflict_repair_prompt.{_artifact_label(repo.name)}.md"
    ).read_text(encoding="utf-8")
    assert saved_prompt == prompt
    assert not (artifact_dir / "conflict_repair_prompt.md").exists()
    return prompt


@pytest.mark.parametrize(
    ("name", "kind", "repo_relpath"),
    [
        ("sase", "main", "sase-main"),
        ("sase-github", "sibling", "linked/sase-github"),
        ("gh:sase-org/sase-core", "external", "external/gh/sase-org/sase-core"),
        (
            "research",
            "sdd",
            "sase checkout with spaces/repos/research reports",
        ),
    ],
)
def test_conflict_repair_prompt_scopes_verification_to_target_repository(
    tmp_path: Path,
    name: str,
    kind: str,
    repo_relpath: str,
) -> None:
    repo_path = tmp_path / repo_relpath
    repo = DirtyRepo(
        name=name,
        path=str(repo_path),
        changed_files=("stale/pre-repair-snapshot.json",),
        kind=kind,  # type: ignore[arg-type]
    )

    prompt = _capture_conflict_repair_prompt(tmp_path, repo)

    assert f"committing repository {name}" in prompt
    assert f"Target repository: {name}" in prompt
    assert f"Target checkout path: {repo_path}" in prompt
    assert f"paused operation in {name}" in prompt
    assert f"fresh commit in {name}" in prompt
    assert "automated host instruction, not a message from the user" in prompt
    assert "single conflict-repair turn for this repository during this run" in prompt

    assert "old dirty file snapshot" in prompt
    assert "target repository's applicable instructions" in prompt
    assert "mandatory all-changes gate remains mandatory" in prompt
    assert "JSON or Markdown repairs" in prompt
    assert "failing or unavailable required gate is a verification failure" in prompt
    assert (
        "Do not substitute a parent, launch-workspace, or sibling repository's gate"
        in prompt
    )
    assert "task runners discovering ancestor configuration" in prompt
    assert (
        "If there is no applicable gate, validate the resolved files directly" in prompt
    )
    assert "parsing plus relevant schema or invariants" in prompt
    assert "JSON artifact-link indexes" in prompt
    assert "preserve distinct records and counts" in prompt
    assert "detect duplicate identities" in prompt
    assert "Parse success alone is insufficient" in prompt
    assert "checks that actually cover the merged content" in prompt
    assert (
        "Briefly report the repository, the checks performed and their results"
        in prompt
    )
    assert "sase stitch create --resume" in prompt

    assert "run the project's verification gate" not in prompt
    assert "only lint or tests will catch" not in prompt


def test_conflict_repair_prompt_preserves_commit_scope_and_final_declaration(
    tmp_path: Path,
) -> None:
    repo = DirtyRepo(
        name="sase-core",
        path=str(tmp_path / "sase-core"),
        changed_files=("crates/sase_core/src/lib.rs",),
        kind="sibling",
    )

    prompt = _capture_conflict_repair_prompt(tmp_path, repo)

    assert "second commit" not in prompt
    assert "another commit" not in prompt
    assert "Do not start a new stitch, skip, abort, or stash it" in prompt
    assert "repair and resume the paused one instead" in prompt
    assert "every repository you changed this turn" in prompt
    assert "/sase_final" in prompt
    assert "single follow-up commit" in prompt
    assert "message you declare there is the message that lands" in prompt


def test_conflict_repair_marks_finalizer_owned_turn_and_restores_on_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    provider = MagicMock()
    repo = DirtyRepo(
        name="sase-core",
        path=str(tmp_path),
        changed_files=("crates/sase_core/src/lib.rs",),
        kind="sibling",
    )

    def _fail(_prompt: str, **_kwargs: object) -> InvokeResult:
        assert os.environ[SASE_FINALIZER_OWNED_TURN_ENV] == "1"
        raise RuntimeError("provider failed")

    provider.invoke.side_effect = _fail

    with pytest.raises(RuntimeError, match="provider failed"):
        _run_conflict_repair_turn(
            provider=provider,
            invoke_result=InvokeResult(content="initial"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(tmp_path),
            options=None,
            repo=repo,
        )

    assert SASE_FINALIZER_OWNED_TURN_ENV not in os.environ
