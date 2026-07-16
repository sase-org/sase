"""Structural tests for the bundled ``#sase/fix_just`` xprompt workflow."""

from pathlib import Path

from sase.xprompt.workflow_loader import _load_workflow_from_file


def test_fix_just_bootstraps_workspace_before_other_just_commands() -> None:
    here = Path(__file__).resolve().parent.parent
    workflow_path = here / "sase" / "xprompts" / "fix_just.yml"

    wf = _load_workflow_from_file(workflow_path)
    assert wf is not None

    install_step = wf.steps[0]
    assert install_step.name == "_just_install"
    assert install_step.hidden is True
    assert install_step.is_bash_step()
    assert install_step.bash is not None
    assert install_step.bash.strip() == "just install"

    install_index = next(
        index for index, step in enumerate(wf.steps) if step.name == "_just_install"
    )
    assert all("just " not in (step.bash or "") for step in wf.steps[:install_index])
