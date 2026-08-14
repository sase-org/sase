"""Phase 3: the commit finalizer preserves the resolved reasoning effort.

A commit/fix follow-up turn must run at the same effort as the original turn,
so ``run_commit_finalizer`` forwards the ``options`` it was given to every
``provider.invoke`` call it makes.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    commit_all,
    init_git_repo,
    mark_opened_sibling,
    set_agent_env,
    set_clean_main,
)


def test_finalizer_follow_up_preserves_reasoning_effort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    dirty_file = sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", sibling)

    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:  # noqa: ARG001
        commit_all(sibling)
        return InvokeResult(content="finalized")

    provider.invoke.side_effect = invoke
    options = LLMInvocationOptions(reasoning_effort="xhigh", explicit=True)

    run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
        options=options,
    )

    assert provider.invoke.call_count == 1
    assert provider.invoke.call_args.kwargs["options"] == options
