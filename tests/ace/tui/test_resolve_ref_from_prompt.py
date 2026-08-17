"""Direct unit tests for ``resolve_ref_from_prompt()``.

``sase.agent.launch_cwd_agents`` and ``sase.agent.multi_prompt_vcs`` still
call this helper; these tests do not import the retired in-process launch
body harness.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests._workspace_provider_helpers import git_metadata


@pytest.fixture(autouse=True)
def _reset_vcs_tag_pattern_cache() -> object:
    """Rebuild the lazily-cached VCS tag pattern from the real providers."""
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_tags as vcs_tags

    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None
    yield
    parsing._VCS_TAG_PATTERN = None
    vcs_tags._VCS_TAG_PATTERN = None


def test_resolve_ref_from_prompt_propagates_provider_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-mismatched ``#git:`` ref must surface, not vanish as None.

    Regression test for bare_git_project_clobber: swallowing this alongside
    ordinary unresolved refs would silently drop the launch's VCS
    resolution instead of telling the user why it failed.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )
    from sase.workspace_provider.utils import ProjectProviderMismatchError

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", git_metadata)
    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt",
        lambda prompt: prompt,
    )

    def _raise_mismatch(ref: str, workflow_type: str):  # type: ignore[no-untyped-def]
        raise ProjectProviderMismatchError(
            "'sase' is not a bare-git project — #git:sase would convert it into one."
        )

    with patch("sase.workspace_provider.resolve_ref", side_effect=_raise_mismatch):
        with pytest.raises(ProjectProviderMismatchError):
            resolve_ref_from_prompt("#git:sase do work", "git")
