"""Regression coverage for builtin@commit conflict-repair prompt wording."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sase.finalizers.commit_repair import _run_conflict_repair_turn
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
    assert "every repository you changed this turn" in prompt
    assert "/sase_final" in prompt
