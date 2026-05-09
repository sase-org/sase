"""Tests for VCS cwd resolution used by xprompt workflow dispatch."""

from unittest.mock import MagicMock, patch


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_returns_vcs_ref(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    _mock_chdir: MagicMock,
    _mock_detect_project: MagicMock,
) -> None:
    """_resolve_vcs_cwd returns (project_name, vcs_ref) with the raw ref."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["hg"]
    resolved = MagicMock()
    resolved.primary_workspace_dir = "/some/workspace"
    resolved.project_name = "yserve"
    mock_resolve_ref.return_value = resolved

    result = _resolve_vcs_cwd("#hg:yserve_batch_create_update #split")

    assert result is not None
    project_name, vcs_ref = result
    assert project_name == "yserve"
    assert vcs_ref == "yserve_batch_create_update"


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_falls_back_to_ref_as_project_name(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    _mock_chdir: MagicMock,
    _mock_detect_project: MagicMock,
) -> None:
    """When project_name is None, _resolve_vcs_cwd uses ref as the first element."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["gh"]
    resolved = MagicMock()
    resolved.primary_workspace_dir = "/some/workspace"
    resolved.project_name = None  # resolution doesn't know the project name
    mock_resolve_ref.return_value = resolved

    result = _resolve_vcs_cwd("#gh:my_feature_branch")

    assert result is not None
    project_name, vcs_ref = result
    # Falls back to the ref itself as project name
    assert project_name == "my_feature_branch"
    # vcs_ref is always the raw ref
    assert vcs_ref == "my_feature_branch"


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_returns_ref_when_workflow_type_not_registered(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    mock_chdir: MagicMock,
    mock_detect_project: MagicMock,
) -> None:
    """Unregistered #type:ref still returns (ref, ref) without chdir."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["gh", "git"]

    result = _resolve_vcs_cwd("#hg:yserve_batch_create_update #split")

    assert result == ("yserve_batch_create_update", "yserve_batch_create_update")
    mock_resolve_ref.assert_not_called()
    mock_chdir.assert_not_called()
    mock_detect_project.cache_clear.assert_not_called()
