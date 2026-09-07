"""Regression coverage for builtin@commit conflict-repair prompt wording."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import os
import pytest

from sase.finalizers.commit_repair import _run_conflict_repair_turn
from sase.finalizers.owned_turn import SASE_FINALIZER_OWNED_TURN_ENV
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def test_conflict_repair_prompt_scopes_commit_restrictions(
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    repo = DirtyRepo(
        name="sase-core",
        path=str(tmp_path),
        changed_files=("crates/sase_core/src/lib.rs",),
        kind="sibling",
    )

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

    prompt = provider.invoke.call_args.args[0]
    assert "second commit" not in prompt
    assert "another commit" not in prompt
    assert "automated host instruction, not a message from the user" in prompt
    assert "paused operation in sase-core" in prompt
    assert "fresh commit in sase-core" in prompt
    assert "Before continuing the paused VCS operation" in prompt
    assert "run the project's verification gate" in prompt
    assert "same list, dict, tuple, or enum" in prompt
    assert "only lint or tests will catch" in prompt
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
