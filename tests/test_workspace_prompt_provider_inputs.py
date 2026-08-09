"""Provider-input boundaries for workspace-bearing review xprompts."""

from __future__ import annotations

import pytest

from sase.xprompt import process_xprompt_references
from sase.xprompt.models import UNSET
from sase.xprompt.tags import XPromptTag, get_by_tag_strict


@pytest.mark.parametrize(
    "tag",
    [
        XPromptTag.mentor,
        XPromptTag.make_mentor_changes,
        XPromptTag.fix_hook,
    ],
)
def test_workspace_review_xprompts_have_no_provider_default(tag: XPromptTag) -> None:
    workflow = get_by_tag_strict(tag)
    assert workflow is not None

    vcs_input = workflow.get_input_by_name("vcs_type")
    assert vcs_input is not None
    assert vcs_input.default is UNSET


def test_fix_hook_ref_free_invocation_remains_ref_free() -> None:
    expanded = process_xprompt_references(
        '#fix_hook(hook_command="just test", output_file="/tmp/hook-output")'
    )

    assert expanded.startswith("The command `just test` is failing.")


def test_fix_hook_patch_requires_provider() -> None:
    with pytest.raises(SystemExit):
        process_xprompt_references(
            '#fix_hook(hook_command="just test", output_file="/tmp/hook-output", '
            'cl_name="feature")'
        )
