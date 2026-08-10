"""Regression test for the confirmed xprompt VCS-tag cache leak (sase-j7.1).

``patch_spy_metadata``/``patch_no_workspace_metadata`` (tests/_workspace_
provider_helpers.py) fake workspace-provider metadata and used to reset the
derived VCS-tag pattern caches only at setup, never at teardown. A test using
one of them left ``_VCS_TAG_PATTERN`` compiled from the fake metadata for
every later test in the same worker process --
``tests/test_removed_hg_workspace_workflow.py`` deterministically reproduces
this against unrelated victim tests today. Running the poisoner then the
victim in one nested pytest subprocess pins the fix at the ordering level:
asserting on the pattern directly, in isolation, would not exercise the
teardown path that broke.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_ROOT = Path(__file__).resolve().parents[1]
_THIS_FILE = str(Path(__file__).resolve())


def test_spy_metadata_patch_poisons_pattern_within_its_own_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt._parsing_vcs_tags import extract_vcs_workflow_tag
    from tests._workspace_provider_helpers import patch_spy_metadata

    patch_spy_metadata(monkeypatch)
    assert extract_vcs_workflow_tag("#spy:x ") == "#spy:x "


def test_no_workspace_metadata_patch_clears_pattern_within_its_own_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.xprompt._parsing_vcs_tags import extract_vcs_workflow_tag
    from tests._workspace_provider_helpers import patch_no_workspace_metadata

    patch_no_workspace_metadata(monkeypatch)
    assert extract_vcs_workflow_tag("#git:x ") is None


def test_default_vcs_tag_pattern_resolves_after_metadata_patch_teardown() -> None:
    """Runs after the two poisoners above; must not see their fake metadata."""
    from sase.xprompt._parsing_vcs_tags import extract_vcs_workflow_tag

    assert extract_vcs_workflow_tag("#git:x ") == "#git:x "


def test_metadata_patch_teardown_does_not_poison_a_later_test(
    pytester: pytest.Pytester,
) -> None:
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_ROOT),
        f"{_THIS_FILE}::test_spy_metadata_patch_poisons_pattern_within_its_own_test",
        f"{_THIS_FILE}::test_no_workspace_metadata_patch_clears_pattern_within_its_own_test",
        f"{_THIS_FILE}::test_default_vcs_tag_pattern_resolves_after_metadata_patch_teardown",
        timeout=60,
    )
    result.assert_outcomes(passed=3)
