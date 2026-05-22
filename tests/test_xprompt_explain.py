from __future__ import annotations

from rich.console import Console

from sase.xprompt.explain import explain_workflow
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def test_explain_workflow_renders_descriptions() -> None:
    console = Console(record=True, width=100)
    workflow = Workflow(
        name="review",
        description="Review a selected diff.",
        inputs=[
            InputArg(
                name="diff",
                type=InputType.PATH,
                description="Diff file to inspect.",
            )
        ],
        steps=[WorkflowStep(name="prompt", prompt_part="Review {{ diff }}")],
    )

    explain_workflow(workflow, console=console)

    output = console.export_text()
    assert "Review a selected diff." in output
    assert "Description" in output
    assert "Diff file to inspect." in output
