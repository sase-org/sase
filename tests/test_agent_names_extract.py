"""Tests for extract_directives_and_write_meta auto-dismiss behavior."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

from sase.agent.names import NameCollisionError
from tests._agent_names_fixtures import make_agent


def _mock_provider() -> MagicMock:
    p = MagicMock()
    p.resolve_model_name.return_value = "test-model"
    return p


def _run_extract(
    tmp_path: Path,
    *,
    env_auto_dismiss: bool = False,
    planned_name: str | None = None,
    generated_name: bool = False,
    prompt: str = "do stuff",
    raw_resolved_prompt: str | None = None,
    cl_name: str | None = None,
) -> dict:
    """Call extract_directives_and_write_meta with standard mocks.

    Returns the written agent_meta.json as a dict.
    """
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace = str(tmp_path / "workspace")
    artifacts = str(tmp_path / "artifacts")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)

    env_patch: dict[str, str] = {}
    if env_auto_dismiss:
        env_patch["SASE_AGENT_AUTO_DISMISS"] = "1"
    if planned_name is not None:
        env_patch["SASE_AGENT_PLANNED_NAME"] = planned_name
    if generated_name:
        env_patch["SASE_AGENT_GENERATED_NAME"] = "1"

    with (
        patch.dict(os.environ, env_patch, clear=False),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name", return_value="test"
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=_mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        # Remove the env var if not auto_dismiss (in case it leaked)
        if not env_auto_dismiss:
            os.environ.pop("SASE_AGENT_AUTO_DISMISS", None)
        if planned_name is None:
            os.environ.pop("SASE_AGENT_PLANNED_NAME", None)
        if not generated_name:
            os.environ.pop("SASE_AGENT_GENERATED_NAME", None)
        info = extract_directives_and_write_meta(
            prompt,
            workspace,
            artifacts,
            cl_name=cl_name,
            raw_resolved_prompt=raw_resolved_prompt,
        )

    meta_path = os.path.join(artifacts, "agent_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {}
    return {"info": info, "meta": meta, "artifacts": artifacts}


class TestExtractDirectivesAutoDismiss:
    def test_persists_wait_runners_metadata(self, tmp_path: Path) -> None:
        result = _run_extract(
            tmp_path,
            env_auto_dismiss=True,
            prompt="%wait(runners=0)\ndo stuff",
        )

        assert result["info"].wait_runners == 0
        assert result["meta"]["wait_runners"] == 0

    def test_skips_auto_name_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should not get an auto-assigned name."""
        result = _run_extract(tmp_path, env_auto_dismiss=True)
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_writes_hidden_when_auto_dismiss(self, tmp_path: Path) -> None:
        """Auto-dismiss agents should be marked hidden in agent_meta.json."""
        result = _run_extract(tmp_path, env_auto_dismiss=True)
        assert result["meta"].get("hidden") is True
        assert result["info"].hidden is True

    def test_normal_agent_gets_name(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents get an auto-assigned name."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, env_auto_dismiss=False)
        assert result["info"].name is not None
        assert result["meta"].get("name") is not None

    def test_normal_agent_not_hidden(self, tmp_path: Path) -> None:
        """Without auto-dismiss, agents are not hidden."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, env_auto_dismiss=False)
        assert result["meta"].get("hidden") is not True
        assert result["info"].hidden is False

    def test_resume_prompt_gets_resume_derived_name(self, tmp_path: Path) -> None:
        """A raw top-level #fork picks the first available .f slot."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_planned_name_wins_for_non_explicit_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="planned",
                prompt="expanded prompt",
            )
        assert result["info"].name == "planned"
        assert result["meta"].get("name") == "planned"

    def test_explicit_name_wins_over_resume(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:bar expanded prompt",
                raw_resolved_prompt="%name:bar #fork:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_bare_name_uses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name expanded prompt",
                raw_resolved_prompt="%name #fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_matching_planned_resume_descendant_name_wins(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f0.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0.cld"
        assert result["meta"].get("name") == "foo.f0.cld"

    def test_matching_letter_planned_resume_descendant_name_wins(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-a.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f-a.cld"
        assert result["meta"].get("name") == "foo.f-a.cld"

    def test_noncanonical_planned_resume_descendant_name_is_rejected(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.f-1.cld",
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_auto_dismiss_suppresses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=True,
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_wait_prompt_gets_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name == "foo.w0"
        assert result["meta"].get("name") == "foo.w0"

    def test_time_shaped_wait_name_reaches_launch_metadata(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, prompt="%w:4h\nDo work")

        assert result["info"].wait_names == ["4h"]
        assert result["meta"]["wait_for"] == ["4h"]

    def test_explicit_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_resume_name_wins_over_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:bar\n%wait:foo do stuff",
            )
        assert result["info"].name == "bar.f0"
        assert result["meta"].get("name") == "bar.f0"

    def test_resume_name_wins_over_wait_planned_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                planned_name="foo.w0",
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="%wait:foo\n#fork:foo do stuff",
            )
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_multiple_waits_fall_back_to_auto_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo\n%wait:bar\ndo stuff",
            )
        assert result["info"].name == "0"
        assert result["meta"].get("name") == "0"

    def test_auto_dismiss_suppresses_wait_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=True,
                prompt="%wait:foo do stuff",
            )
        assert result["info"].name is None
        assert "name" not in result["meta"]

    def test_metadata_records_workspace_dir_without_vcs_provider(
        self, tmp_path: Path
    ) -> None:
        result = _run_extract(tmp_path, env_auto_dismiss=True)
        expected = str(tmp_path / "workspace")
        assert result["meta"]["workspace_dir"] == expected
        assert "vcs_provider" not in result["meta"]

    def test_named_agent_writes_agent_metadata(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                prompt="%name:alpha do stuff",
                cl_name="feature-branch",
            )

        meta = result["meta"]
        assert meta["name"] == "alpha"
        assert meta["changespec_name"] == "feature-branch"
        assert meta["cl_name"] == "feature-branch"

    def test_indexed_name_template_allocates_concrete_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-0")

        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, prompt="%name:build-@\nDo work")

        assert result["info"].name == "build-1"
        assert result["meta"]["name"] == "build-1"
        assert result["meta"]["agent_name_template"] == "build-@"

    def test_indexed_name_template_uses_matching_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                planned_name="build-7",
                prompt="%name:build-@\nDo work",
            )

        assert result["info"].name == "build-7"
        assert result["meta"]["name"] == "build-7"
        assert result["meta"]["agent_name_template"] == "build-@"

    def test_indexed_name_template_ignores_unrelated_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                planned_name="other-1",
                prompt="%name:build-@\nDo work",
            )

        assert result["info"].name == "build-0"
        assert result["meta"]["name"] == "build-0"

    def test_agent_name_template_suffix_shape_uses_matching_planned_name(
        self, tmp_path: Path
    ) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                planned_name="7.cld",
                prompt="%name:@.cld\nDo work",
            )

        assert result["info"].name == "7.cld"
        assert result["meta"]["name"] == "7.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"

    def test_generated_template_name_uses_planned_name_without_explicit_claim(
        self, tmp_path: Path
    ) -> None:
        with (
            patch.object(Path, "home", return_value=tmp_path),
            patch("sase.agent.names.claim_agent_name") as claim,
        ):
            result = _run_extract(
                tmp_path,
                planned_name="7.cld",
                generated_name=True,
                prompt="%name:@.cld\nDo work",
            )

        assert result["info"].name == "7.cld"
        assert result["meta"]["name"] == "7.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"
        assert claim.call_args.kwargs["explicit"] is False

    def test_agent_name_template_suffix_shape_falls_back_without_planned_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "0.cld")

        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, prompt="%name:@.cld\nDo work")

        assert result["info"].name == "1.cld"
        assert result["meta"]["name"] == "1.cld"
        assert result["meta"]["agent_name_template"] == "@.cld"

    def test_indexed_wait_template_persists_concrete_latest_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-1")
        make_agent(tmp_path, "proj", "run2", "build-3")

        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, prompt="%wait:build-@\nDo work")

        assert result["info"].wait_names == ["build-3"]
        assert result["meta"]["wait_for"] == ["build-3"]
        assert result["meta"]["name"] == "build-3.w0"

    def test_wait_template_suffix_shape_persists_concrete_latest_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "0.cld")
        make_agent(tmp_path, "proj", "run2", "1.cld")

        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(tmp_path, prompt="%wait:@.cld\nDo work")

        assert result["info"].wait_names == ["1.cld"]
        assert result["meta"]["wait_for"] == ["1.cld"]
        assert result["meta"]["name"] == "1.cld.w0"

    def test_indexed_wait_resolves_before_same_segment_indexed_name(
        self, tmp_path: Path
    ) -> None:
        make_agent(tmp_path, "proj", "run1", "build-0")

        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                prompt="%wait:build-@\n%name:build-@\nDo work",
            )

        assert result["info"].wait_names == ["build-0"]
        assert result["meta"]["wait_for"] == ["build-0"]
        assert result["meta"]["name"] == "build-1"

    def test_unnamed_auto_dismiss_agent_writes_basic_metadata(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / "20260505120000"
        )
        workspace = tmp_path / "workspace"
        artifacts_dir.mkdir(parents=True)
        workspace.mkdir()

        from sase.axe.run_agent_phases import extract_directives_and_write_meta

        with (
            patch.dict(os.environ, {"SASE_AGENT_AUTO_DISMISS": "1"}, clear=False),
            patch(
                "sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p
            ),
            patch(
                "sase.llm_provider.registry.get_default_provider_name",
                return_value="test",
            ),
            patch(
                "sase.llm_provider.registry.get_provider", return_value=_mock_provider()
            ),
            patch(
                "sase.llm_provider.registry.resolve_model_provider",
                return_value=("test", "test-model"),
            ),
            patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ):
            info = extract_directives_and_write_meta(
                "do stuff",
                str(workspace),
                str(artifacts_dir),
                cl_name="feature-branch",
            )

        meta = json.loads((artifacts_dir / "agent_meta.json").read_text())
        assert info.name is None
        assert "name" not in meta
        assert meta["workspace_dir"] == str(workspace)
        assert meta["changespec_name"] == "feature-branch"


class TestExtractDirectivesImplicitForkWait:
    """A top-level #fork:<name> implies %wait:<name> as runner metadata."""

    def test_bare_fork_target_implies_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert result["info"].wait_names == ["foo"]
        # Fork-derived naming still wins over the implicit wait.
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_fork_appends_after_explicit_waits(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:bar expanded prompt",
                raw_resolved_prompt="#fork:foo\n%wait:bar do stuff",
            )
        assert result["meta"].get("wait_for") == ["bar", "foo"]
        assert result["info"].wait_names == ["bar", "foo"]
        assert result["info"].name == "foo.f0"
        assert result["meta"].get("name") == "foo.f0"

    def test_explicit_duplicate_wait_is_not_repeated(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%wait:foo expanded prompt",
                raw_resolved_prompt="#fork:foo %wait:foo do stuff",
            )
        assert result["meta"].get("wait_for") == ["foo"]
        assert result["info"].wait_names == ["foo"]
        assert result["info"].name == "foo.f0"

    def test_bare_fork_without_name_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#fork do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []

    def test_legacy_resume_adds_no_implicit_wait(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#resume:foo do stuff",
            )
        assert "wait_for" not in result["meta"]
        assert result["info"].wait_names == []


def test_auto_epic_writes_plan_auto_action(tmp_path: Path) -> None:
    """%auto:epic is plan-specific and does not enable full auto-approve."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = _run_extract(tmp_path, prompt="%auto:epic\nDraft the epic")

    assert result["info"].plan is True
    assert result["info"].approve is False
    assert result["meta"]["plan"] is True
    assert result["meta"]["auto_approve_plan_action"] == "epic"
    assert "approve" not in result["meta"]


def test_auto_tale_writes_plan_auto_action(tmp_path: Path) -> None:
    """%auto:tale is plan-specific and does not enable full auto-approve."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = _run_extract(tmp_path, prompt="%auto:tale\nDraft the tale")

    assert result["info"].plan is True
    assert result["info"].approve is False
    assert result["meta"]["plan"] is True
    assert result["meta"]["auto_approve_plan_action"] == "tale"
    assert "approve" not in result["meta"]


def test_concurrent_auto_extract_assigns_unique_names(tmp_path: Path) -> None:
    from sase.agent.names import get_next_auto_name as real_get_next_auto_name
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    def slow_get_next_auto_name() -> str:
        name = real_get_next_auto_name()
        time.sleep(0.05)
        return name

    def run(index: int) -> str:
        workspace = tmp_path / f"workspace{index}"
        artifacts = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / f"run{index}"
        )
        workspace.mkdir(parents=True)
        artifacts.mkdir(parents=True)
        info = extract_directives_and_write_meta(
            "do stuff",
            str(workspace),
            str(artifacts),
            cl_name="feature-branch",
        )
        return str(info.name)

    for key in (
        "SASE_AGENT_AUTO_DISMISS",
        "SASE_AGENT_PLANNED_NAME",
        "SASE_REPEAT_NAME",
    ):
        os.environ.pop(key, None)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch(
            "sase.agent.names.get_next_auto_name",
            side_effect=slow_get_next_auto_name,
        ),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=_mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        names = list(pool.map(run, range(2)))

    assert sorted(names) == ["0", "1"]


def test_concurrent_explicit_extract_rejects_collision(tmp_path: Path) -> None:
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    def run(index: int) -> tuple[str, str]:
        workspace = tmp_path / f"workspace{index}"
        artifacts = (
            tmp_path
            / ".sase"
            / "projects"
            / "proj"
            / "artifacts"
            / "ace-run"
            / f"run{index}"
        )
        workspace.mkdir(parents=True)
        artifacts.mkdir(parents=True)
        try:
            info = extract_directives_and_write_meta(
                "%name:dupe do stuff",
                str(workspace),
                str(artifacts),
                cl_name="feature-branch",
            )
        except NameCollisionError as exc:
            return "error", str(exc)
        return "ok", str(info.name)

    for key in (
        "SASE_AGENT_AUTO_DISMISS",
        "SASE_AGENT_PLANNED_NAME",
        "SASE_REPEAT_NAME",
    ):
        os.environ.pop(key, None)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=_mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(run, range(2)))

    statuses = [status for status, _ in results]
    assert statuses.count("ok") == 1
    assert statuses.count("error") == 1
    assert any("dupe1" in detail for status, detail in results if status == "error")


def test_generated_name_marker_env_is_consumed(tmp_path: Path) -> None:
    """The generated-name marker applies to this launch only.

    If it lingers in the environment, nested launches spawned by this agent
    inherit it and treat their own explicit %name directives as generated,
    silently skipping name collision checks.
    """
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace = str(tmp_path / "workspace")
    artifacts = str(tmp_path / "artifacts")
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(artifacts, exist_ok=True)

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("sase.agent.names.claim_agent_name"),
        patch.dict(os.environ, {"SASE_AGENT_GENERATED_NAME": "1"}, clear=False),
        patch("sase.xprompt.process_xprompt_references", side_effect=lambda p, **kw: p),
        patch(
            "sase.llm_provider.registry.get_default_provider_name",
            return_value="test",
        ),
        patch("sase.llm_provider.registry.get_provider", return_value=_mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        extract_directives_and_write_meta(
            "%name:genx\nDo work",
            workspace,
            artifacts,
            cl_name="test_cl",
            raw_resolved_prompt="%name:genx\nDo work",
        )

        assert "SASE_AGENT_GENERATED_NAME" not in os.environ
