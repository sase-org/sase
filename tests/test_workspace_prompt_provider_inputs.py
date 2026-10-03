"""Provider-input boundaries for workspace-bearing review macros."""

from __future__ import annotations

import pytest

from sase.macro import process_macro_references
from sase.macro.models import UNSET
from sase.macro.tags import MacroTag, get_by_tag_strict


@pytest.mark.parametrize(
    "tag",
    [
        MacroTag.mentor,
        MacroTag.make_mentor_changes,
        MacroTag.fix_hook,
    ],
)
def test_workspace_review_macros_have_no_provider_default(tag: MacroTag) -> None:
    workflow = get_by_tag_strict(tag)
    assert workflow is not None

    vcs_input = workflow.get_input_by_name("vcs_type")
    assert vcs_input is not None
    assert vcs_input.default is UNSET


def test_fix_hook_ref_free_invocation_remains_ref_free() -> None:
    expanded = process_macro_references(
        '#fix_hook(hook_command="just test", output_file="/tmp/hook-output")'
    )

    assert expanded.startswith("The command `just test` is failing.")


def test_fix_hook_patch_requires_provider() -> None:
    with pytest.raises(SystemExit):
        process_macro_references(
            '#fix_hook(hook_command="just test", output_file="/tmp/hook-output", '
            'cl_name="feature")'
        )
