import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_setup import (
    expand_deferred_launch_xprompts,
    enter_agent_workspace,
    preprocess_prompt_xprompts,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
)


def test_enter_agent_workspace_installs_runtime_ignore_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.chdir(tmp_path)
    with (
        patch("sase.sdd.env.set_sdd_dir_env"),
        patch(
            "sase.workspace_provider.git_exclude.ensure_git_info_exclude_entry",
            side_effect=lambda workspace, pattern: calls.append((workspace, pattern)),
        ),
    ):
        enter_agent_workspace(str(tmp_path), 10)

    assert calls == [
        (str(tmp_path), ".sase/"),
        (str(tmp_path), "/sase/repos/"),
    ]


def test_write_submitted_xprompt_artifact_preserves_exact_prompt(
    tmp_path: Path,
) -> None:
    prompt = "  #alias\n\nbody\n  "

    path = write_submitted_xprompt_artifact(str(tmp_path), prompt)

    assert Path(path).name == "submitted_xprompt.md"
    assert Path(path).read_text(encoding="utf-8") == prompt


def test_submitted_xprompt_artifact_does_not_change_raw_xprompt_behavior(
    tmp_path: Path,
) -> None:
    submitted = "#alias original"
    resolved = "#real original"

    write_submitted_xprompt_artifact(str(tmp_path), submitted)
    with (
        patch("sase.xprompt.resolve_xprompt_aliases", return_value=resolved),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references", return_value="expanded"
        ),
    ):
        preprocess_prompt_xprompts(submitted, str(tmp_path))

    assert (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8") == submitted
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == resolved


def test_preprocess_prompt_xprompts_captures_launch_boundary_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner writes xprompts.json (e.g. #plan) before expansion erases it."""
    import sase.xprompt.used_xprompts as used_xprompts
    from sase.xprompt.models import XPrompt

    # Isolate from an ambient launch-boundary swarm (e.g. this test process
    # itself running as a swarm-launched agent); the catalog patched below
    # only knows about "plan".
    monkeypatch.delenv(used_xprompts.SASE_LAUNCH_SWARM_XPROMPTS, raising=False)
    monkeypatch.setattr(
        used_xprompts,
        "get_all_xprompts",
        lambda: {"plan": XPrompt(name="plan", content="plan body")},
    )
    monkeypatch.setattr(used_xprompts, "get_all_workflows", lambda: {})
    monkeypatch.setattr(used_xprompts, "resolve_xprompt_aliases", lambda prompt: prompt)
    monkeypatch.setattr(
        used_xprompts, "normalize_vcs_underscore_refs", lambda prompt: prompt
    )

    with (
        patch(
            "sase.xprompt.resolve_xprompt_aliases", side_effect=lambda prompt: prompt
        ),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda prompt, **_kwargs: "expanded",
        ) as process,
    ):
        expanded, _, _ = preprocess_prompt_xprompts("Make a #plan now", str(tmp_path))

    # Expansion still runs and returns the expanded text.
    assert expanded == "expanded"
    # The pre-expansion #plan reference is captured into the shared file that
    # the root (non-step) agent row reads.
    data = json.loads((tmp_path / "xprompts.json").read_text(encoding="utf-8"))
    assert [(r["name"], r["kind"]) for r in data] == [("plan", "part")]
    assert set(data[0]) == {"name", "kind", "positional", "named", "tags"}
    # raw_xprompt.md and the captured metadata derive from the same text.
    assert (tmp_path / "raw_xprompt.md").read_text(
        encoding="utf-8"
    ) == "Make a #plan now"
    assert process.call_args.kwargs["defer_xprompt_names"] == frozenset({"fork"})


def test_preprocess_prompt_xprompts_captures_launch_swarm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swarm-launched child records its origin before prompt expansion."""
    import sase.xprompt.used_xprompts as used_xprompts
    from sase.xprompt.models import XPrompt
    from sase.xprompt.tags import XPromptTag

    monkeypatch.setenv(
        used_xprompts.SASE_LAUNCH_SWARM_XPROMPTS,
        '["research_swarm"]',
    )
    monkeypatch.setattr(
        used_xprompts,
        "get_all_xprompts",
        lambda: {
            "research": XPrompt(name="research", content="research body"),
            "research_swarm": XPrompt(
                name="research_swarm",
                content="swarm body",
                tags=frozenset({XPromptTag.crs}),
            ),
        },
    )
    monkeypatch.setattr(used_xprompts, "get_all_workflows", lambda: {})
    monkeypatch.setattr(used_xprompts, "resolve_xprompt_aliases", lambda prompt: prompt)
    monkeypatch.setattr(
        used_xprompts,
        "normalize_vcs_underscore_refs",
        lambda prompt: prompt,
    )

    with (
        patch(
            "sase.xprompt.resolve_xprompt_aliases",
            side_effect=lambda prompt: prompt,
        ),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            return_value="expanded",
        ),
    ):
        preprocess_prompt_xprompts("Run #research", str(tmp_path))

    data = json.loads((tmp_path / "xprompts.json").read_text(encoding="utf-8"))
    assert data == [
        {
            "name": "research_swarm",
            "kind": "swarm",
            "positional": [],
            "named": {},
            "tags": ["crs"],
        },
        {
            "name": "research",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]


def test_runner_setup_artifacts_keep_project_alias_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )
    prompt = "#gh:bob-cli do it"

    write_submitted_xprompt_artifact(str(tmp_path), prompt)
    with (
        patch("sase.config.load_merged_config", return_value={"xprompt_aliases": {}}),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda text, **_kwargs: text,
        ),
    ):
        preprocess_prompt_xprompts(prompt, str(tmp_path))

    submitted = (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8")
    raw = (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8")
    assert submitted == "#gh:bob-cli do it"
    assert raw == "#gh:bob-cli do it"
    assert "#gh:bob " not in submitted
    assert "#gh:bob " not in raw


def test_expand_deferred_launch_xprompts_limits_embedded_expansion(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda prompt, **_kwargs: prompt,
        ),
        patch(
            "sase.main.query_handler.expand_embedded_workflows_in_query",
            return_value=("injected history", []),
        ) as expand_embedded,
    ):
        result = expand_deferred_launch_xprompts(
            "#fork:review Continue",
            str(tmp_path),
        )

    assert result == "injected history"
    assert expand_embedded.call_args.kwargs["only_workflow_names"] == frozenset(
        {"fork"}
    )
    assert (
        expand_embedded.call_args.kwargs["preserve_existing_xprompt_metadata"] is True
    )


def test_deferred_fork_starts_disabled_marker_after_workspace_line(
    tmp_path: Path,
) -> None:
    from sase.xprompt.workflow_models import Workflow, WorkflowStep

    fork = Workflow(
        name="fork",
        steps=[
            WorkflowStep(
                name="inject",
                prompt_part=(
                    "%xprompts_enabled:false\n"
                    "# Previous Conversation\n"
                    "history\n"
                    "%xprompts_enabled:true\n"
                    "# New Query"
                ),
            )
        ],
    )

    with (
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=lambda prompt, **_kwargs: prompt,
        ),
        patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"fork": fork},
        ),
        patch("sase.xprompt.used_xprompts.write_used_xprompts"),
    ):
        expanded = expand_deferred_launch_xprompts(
            "#gh:sase #fork Continue the work",
            str(tmp_path),
        )

    assert expanded.startswith("#gh:sase \n%xprompts_enabled:false\n")
    assert "#gh:sase %xprompts_enabled:false" not in expanded


def test_deferred_launch_xprompts_preserve_original_usage_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.xprompt.used_xprompts as used_xprompts
    from sase.xprompt.models import XPrompt
    from sase.xprompt.workflow_models import Workflow, WorkflowStep

    parts = {
        "beau": XPrompt(name="beau", content="beau body"),
        "plan": XPrompt(name="plan", content="plan body"),
    }
    workflows = {
        "gh": Workflow(
            name="gh",
            steps=[WorkflowStep(name="main", prompt_part="gh body")],
        ),
        "fork": Workflow(
            name="fork",
            steps=[WorkflowStep(name="main", prompt_part="fork history")],
        ),
    }
    # Isolate from an ambient launch-boundary swarm (e.g. this test process
    # itself running as a swarm-launched agent); the catalogs patched here
    # only know about "gh", "fork", "beau", and "plan".
    monkeypatch.delenv(used_xprompts.SASE_LAUNCH_SWARM_XPROMPTS, raising=False)
    monkeypatch.setattr(used_xprompts, "get_all_xprompts", lambda: parts)
    monkeypatch.setattr(used_xprompts, "get_all_workflows", lambda: workflows)
    monkeypatch.setattr(used_xprompts, "resolve_xprompt_aliases", lambda prompt: prompt)
    monkeypatch.setattr(
        used_xprompts,
        "normalize_vcs_underscore_refs",
        lambda prompt: prompt,
    )
    monkeypatch.setattr("sase.xprompt.loader.get_all_workflows", lambda: workflows)

    launch_prompt = "#gh:sase #fork #beau #plan"
    partially_expanded = "#gh:sase #fork beau body plan body"

    def process(prompt: str, **kwargs: object) -> str:
        if kwargs.get("defer_xprompt_names"):
            assert prompt == launch_prompt
            return partially_expanded
        return prompt

    with (
        patch(
            "sase.project_aliases.canonicalize_project_aliases_in_prompt",
            side_effect=lambda prompt: prompt,
        ),
        patch(
            "sase.xprompt.resolve_xprompt_aliases",
            side_effect=lambda prompt: prompt,
        ),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references",
            side_effect=process,
        ),
    ):
        prompt, _, _ = preprocess_prompt_xprompts(launch_prompt, str(tmp_path))
        expanded = expand_deferred_launch_xprompts(prompt, str(tmp_path))

    assert prompt == partially_expanded
    assert "#gh:sase" in expanded
    assert "#fork" not in expanded
    assert "fork history" in expanded
    records = json.loads((tmp_path / "xprompts.json").read_text(encoding="utf-8"))
    assert [record["name"] for record in records] == [
        "gh",
        "fork",
        "beau",
        "plan",
    ]


def _load_fork_workflow():
    from sase.xprompt.loader import get_sase_package_xprompts_dir
    from sase.xprompt.workflow_loader import _load_workflow_from_file

    workflow = _load_workflow_from_file(get_sase_package_xprompts_dir() / "fork.yml")
    assert workflow is not None
    return workflow


def _write_named_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    response_path: Path | None = None,
) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": name}),
        encoding="utf-8",
    )
    if response_path is not None:
        (artifacts_dir / "done.json").write_text(
            json.dumps({"outcome": "completed", "response_path": str(response_path)}),
            encoding="utf-8",
        )
    return artifacts_dir


class TestBareForkSelfExclusion:
    """Regression tests for defect B: bare #fork must not resolve to itself.

    ``_resolve_default_agent_name()`` excludes the caller's own
    ``SASE_ARTIFACTS_DIR`` so a bare ``#fork`` cannot select the run being
    launched. That exclusion only works if ``expand_deferred_launch_xprompts``
    publishes the run's own artifacts dir before expansion runs.
    """

    def test_bare_fork_resolves_older_agent_not_the_launching_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

        chat_path = tmp_path / "older-chat.md"
        chat_path.write_text(
            "## Prompt\n\nOld question\n\n## Response\n\nOLDER AGENT REPLY\n",
            encoding="utf-8",
        )
        _write_named_agent(
            tmp_path, "20260504010101", "builder", response_path=chat_path
        )
        # The run being launched: a later timestamp (so it would win as
        # "most recent" if not excluded) with agent_meta.json already
        # written but no chat history yet.
        artifacts_dir = _write_named_agent(tmp_path, "20260504020202", "current_run")

        with patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"fork": _load_fork_workflow()},
        ):
            expanded = expand_deferred_launch_xprompts(
                "#fork\nContinue", str(artifacts_dir)
            )

        assert "OLDER AGENT REPLY" in expanded
        assert os.environ.get("SASE_ARTIFACTS_DIR") is None

    def test_restores_inherited_artifacts_dir_after_expansion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An inherited SASE_ARTIFACTS_DIR is restored, not left as this run's."""
        monkeypatch.setenv("HOME", str(tmp_path))
        unrelated_dir = str(tmp_path / "unrelated-parent-artifacts")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", unrelated_dir)

        chat_path = tmp_path / "older-chat.md"
        chat_path.write_text(
            "## Prompt\n\nOld question\n\n## Response\n\nOLDER AGENT REPLY\n",
            encoding="utf-8",
        )
        _write_named_agent(
            tmp_path, "20260504010101", "builder", response_path=chat_path
        )
        artifacts_dir = _write_named_agent(tmp_path, "20260504020202", "current_run")

        with patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"fork": _load_fork_workflow()},
        ):
            expanded = expand_deferred_launch_xprompts(
                "#fork\nContinue", str(artifacts_dir)
            )

        assert "OLDER AGENT REPLY" in expanded
        assert os.environ.get("SASE_ARTIFACTS_DIR") == unrelated_dir


def test_setup_artifacts_directory_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with (
        patch(
            "sase.axe.run_agent_runner_setup.create_artifacts_directory",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.axe.run_agent_runner_setup.convert_timestamp_to_artifacts_format",
            return_value="20260520220000",
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        setup_artifacts_directory(
            timestamp="260520_220000",
            project_file="/tmp/project/project.gp",
            cl_name="feature",
            is_home_mode=False,
        )

    assert calls == [str(tmp_path)]
    assert (tmp_path / "workflow_state.json").is_file()
