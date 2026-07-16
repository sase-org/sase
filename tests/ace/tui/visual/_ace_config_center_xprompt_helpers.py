"""XPrompt tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import pytest

from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _xprompts() -> dict[str, Workflow]:
    return {
        "review": Workflow(
            name="review",
            description="Review a selected diff for correctness.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="Review {{ diff }}.")],
            source_path="/home/visual/sase/xprompts/review.md",
        ),
        "ship": Workflow(
            name="ship",
            description="Ship the current change end-to-end.",
            steps=[WorkflowStep(name="run", agent="ship the change")],
            source_path="/home/visual/sase/xprompts/ship.yml",
        ),
    }


def _patch_xprompt_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _xprompts()
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: dict(prompts),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.classify_source",
        lambda source_path: (
            "Home ~/sase/xprompts/",
            source_path.replace("/home/visual", "~"),
            True,
        ),
    )
