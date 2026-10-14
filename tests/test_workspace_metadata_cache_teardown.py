"""Regression test for the confirmed macro VCS-tag cache leak (sase-j7.1).

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
    from sase.macro._parsing_vcs_tags import extract_vcs_workflow_tag
    from tests._workspace_provider_helpers import patch_spy_metadata

    patch_spy_metadata(monkeypatch)
    assert extract_vcs_workflow_tag("#spy:x ") == "#spy:x "


def test_no_workspace_metadata_patch_clears_pattern_within_its_own_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.macro._parsing_vcs_tags import extract_vcs_workflow_tag
    from tests._workspace_provider_helpers import patch_no_workspace_metadata

    patch_no_workspace_metadata(monkeypatch)
    assert extract_vcs_workflow_tag("#git:x ") is None


def test_default_vcs_tag_pattern_resolves_after_metadata_patch_teardown() -> None:
    """Runs after the two poisoners above; must not see their fake metadata."""
    from sase.macro._parsing_vcs_tags import extract_vcs_workflow_tag

    assert extract_vcs_workflow_tag("#git:x ") == "#git:x "


@pytest.mark.parametrize(
    "patcher_name",
    (
        "patch_git_metadata",
        "patch_spy_metadata",
        "patch_no_workspace_metadata",
    ),
)
def test_metadata_helper_restores_real_lazy_export_after_unresolved_package_global(
    monkeypatch: pytest.MonkeyPatch,
    patcher_name: str,
) -> None:
    """Teardown must restore the real registry function, not cache the fake.

    Deleting the package global first forces lazy ``__getattr__`` on the
    helper's monkeypatch read. Patching the facade before ``_registry`` is
    what keeps that read on the real function.
    """
    import sase.workspace_provider as workspace_provider
    import sase.workspace_provider._registry as registry
    from tests import _workspace_provider_helpers as helpers

    vars(workspace_provider).pop("get_all_workflow_metadata", None)
    with monkeypatch.context() as nested:
        getattr(helpers, patcher_name)(nested)
    assert (
        vars(workspace_provider)["get_all_workflow_metadata"]
        is registry.get_all_workflow_metadata
    )


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
