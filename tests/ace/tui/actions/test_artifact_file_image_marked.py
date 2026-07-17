from __future__ import annotations

from types import SimpleNamespace

from ._artifact_file_image_helpers import _ImageActionApp


def _marked_agent(
    *,
    name: str,
    artifacts: list[object],
    agent_name: str | None = None,
) -> SimpleNamespace:
    identity = ("RUNNING", name, None)
    return SimpleNamespace(
        status="DONE",
        identity=identity,
        display_name=name,
        agent_name=agent_name,
        _artifacts=artifacts,
    )


def test_agents_open_artifact_files_action_aggregates_marked_agents() -> None:
    foo = _marked_agent(
        name="foo",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/proposal.md", kind="plan", label="Plan"),
            SimpleNamespace(path="/tmp/foo/diff.patch", kind="diff", label="Diff"),
        ],
    )
    bar = _marked_agent(
        name="bar",
        artifacts=[
            SimpleNamespace(path="/tmp/bar/proposal.md", kind="plan", label="Plan"),
            SimpleNamespace(path="/tmp/bar/diff.patch", kind="diff", label="Diff"),
        ],
    )
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo, bar]
    app._marked_agents = {foo.identity, bar.identity}
    app._artifacts_by_agent = {
        id(foo): foo._artifacts,
        id(bar): bar._artifacts,
    }

    app.action_open_artifact_files()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert len(modal._artifact_files) == 4
    assert modal._artifact_files[0] is foo._artifacts[0]
    assert modal._artifact_files[1] is foo._artifacts[1]
    assert modal._artifact_files[2] is bar._artifacts[0]
    assert modal._artifact_files[3] is bar._artifacts[1]
    assert modal._agent_labels == ["foo", "foo", "bar", "bar"]
    assert modal._agent_count == 2
    assert modal._title_text() == "Artifact Files  [4 from 2 agents]"
    app.notify.assert_not_called()


def test_agents_open_artifact_files_action_marked_path_skips_stale_marks() -> None:
    foo = _marked_agent(
        name="foo",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/diff.patch", kind="diff", label="Diff"),
        ],
    )
    stale_identity = ("RUNNING", "ghost", None)
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo]
    app._marked_agents = {foo.identity, stale_identity}
    app._artifacts_by_agent = {id(foo): foo._artifacts}

    app.action_open_artifact_files()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert len(modal._artifact_files) == 1
    assert modal._agent_count == 1
    assert modal._title_text() == "Artifact Files  [1]"


def test_agents_open_artifact_files_action_warns_when_marked_files_empty() -> None:
    foo = _marked_agent(name="foo", artifacts=[])
    bar = _marked_agent(name="bar", artifacts=[])
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo, bar]
    app._marked_agents = {foo.identity, bar.identity}
    app._artifacts_by_agent = {id(foo): [], id(bar): []}

    app.action_open_artifact_files()

    assert app.pushed == []
    app.notify.assert_called_once_with(
        "No artifact files found in marked agents",
        severity="warning",
    )


def test_agents_open_artifact_files_action_warns_when_all_marks_stale() -> None:
    stale_a = ("RUNNING", "ghost-a", None)
    stale_b = ("RUNNING", "ghost-b", None)
    app = _ImageActionApp(None)
    app._agents_with_children = []
    app._marked_agents = {stale_a, stale_b}

    app.action_open_artifact_files()

    assert app.pushed == []
    app.notify.assert_called_once_with(
        "No marked agents remain",
        severity="warning",
    )


def test_agents_open_artifact_files_action_uses_agent_name_suffix_when_distinct() -> (
    None
):
    foo = _marked_agent(
        name="cl-name-foo",
        agent_name="planner",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/plan.md", kind="plan", label="Plan"),
        ],
    )
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo]
    app._marked_agents = {foo.identity}
    app._artifacts_by_agent = {id(foo): foo._artifacts}

    app.action_open_artifact_files()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert modal._agent_labels == ["cl-name-foo @planner"]
