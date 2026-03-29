"""Tests for vcs_resolve_revision suffixed-branch fallback.

When a base-name ChangeSpec (no __N suffix) can't find its branch,
the resolver should fall back to a unique suffixed remote branch
(e.g. origin/feat-bar-1) if exactly one match exists.
"""

from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.bare_git import BareGitPlugin


def _make_run_side_effect(
    *,
    local_hits: dict[str, bool] | None = None,
    remote_hits: dict[str, bool] | None = None,
    for_each_ref_stdout: str = "",
) -> object:
    """Build a side-effect for CommandRunner._run that simulates git commands."""
    local_hits = local_hits or {}
    remote_hits = remote_hits or {}

    def side_effect(cmd: list[str], cwd: str, **kwargs: object) -> MagicMock:
        result = MagicMock()
        if cmd[:4] == ["git", "rev-parse", "--verify", "--quiet"]:
            ref = cmd[4]
            if ref in local_hits:
                result.success = local_hits[ref]
            elif ref in remote_hits:
                result.success = remote_hits[ref]
            else:
                result.success = False
            result.stdout = ""
            result.stderr = ""
            return result
        if cmd[:2] == ["git", "fetch"]:
            result.success = True
            result.stdout = ""
            result.stderr = ""
            return result
        if cmd[:2] == ["git", "for-each-ref"]:
            result.success = True
            result.stdout = for_each_ref_stdout
            result.stderr = ""
            return result
        result.success = False
        result.stdout = ""
        result.stderr = ""
        return result

    return side_effect


# The old changespec_name_to_branch* functions are still used inside
# vcs_resolve_revision as backward-compat candidates — patch them.
@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar",
)
@patch("sase.core.branch_map.read_branch_map", return_value={})
def test_resolve_falls_back_to_unique_suffixed_branch(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """Base name 'proj_feat_bar' resolves to 'origin/feat-bar-1' when unique."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            for_each_ref_stdout="origin/feat-bar-1\n",
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar", "proj", "/ws")
    assert result == "origin/feat-bar-1"


@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar",
)
@patch("sase.core.branch_map.read_branch_map", return_value={})
def test_resolve_no_fallback_when_multiple_suffixed(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """Ambiguous: multiple suffixed branches → falls through to default."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            for_each_ref_stdout="origin/feat-bar-1\norigin/feat-bar-2\n",
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar", "proj", "/ws")
    # derive_branch_name strips suffix → "proj_feat_bar" (identity for git)
    assert result == "proj_feat_bar"


@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar",
)
@patch("sase.core.branch_map.read_branch_map", return_value={})
def test_resolve_no_fallback_when_no_suffixed(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """No suffixed branches → normal fallback."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            for_each_ref_stdout="",
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar", "proj", "/ws")
    # derive_branch_name("proj_feat_bar", "proj") strips suffix → "proj_feat_bar"
    assert result == "proj_feat_bar"


@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar-1",
)
@patch("sase.core.branch_map.read_branch_map", return_value={})
def test_resolve_skips_fallback_when_name_already_suffixed(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """When branch_with_suffix differs from branch_without_suffix, skip fallback."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            for_each_ref_stdout="origin/feat-bar-1\n",
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar__1", "proj", "/ws")
    # Falls through to derived_without_suffix (strip_reverted_suffix → "proj_feat_bar")
    assert result == "proj_feat_bar"


@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar",
)
@patch("sase.core.branch_map.read_branch_map", return_value={})
def test_resolve_ignores_non_numeric_suffix_matches(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """Branches like 'origin/feat-bar-beta' should not match the fallback."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            for_each_ref_stdout="origin/feat-bar-beta\n",
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar", "proj", "/ws")
    # derive_branch_name strips suffix → "proj_feat_bar"
    assert result == "proj_feat_bar"


@patch("sase.core.changespec.changespec_name_to_branch", return_value="feat-bar")
@patch(
    "sase.core.changespec.changespec_name_to_branch_with_suffix",
    return_value="feat-bar",
)
@patch(
    "sase.core.branch_map.read_branch_map",
    return_value={"proj_feat_bar": "proj_feat_bar_1"},
)
def test_resolve_uses_branch_map_alias(
    mock_branch_map: MagicMock,
    mock_with_suffix: MagicMock,
    mock_branch: MagicMock,
) -> None:
    """Branch map alias is tried first and resolves successfully."""
    plugin = BareGitPlugin()
    plugin._run = MagicMock(  # type: ignore[assignment]
        side_effect=_make_run_side_effect(
            local_hits={"proj_feat_bar_1": True},
        )
    )

    result = plugin.vcs_resolve_revision("proj_feat_bar", "proj", "/ws")
    assert result == "proj_feat_bar_1"
