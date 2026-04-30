"""Tests for extract_directives_and_write_meta auto-dismiss behavior."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def _mock_provider() -> MagicMock:
    p = MagicMock()
    p.resolve_model_name.return_value = "test-model"
    return p


def _run_extract(
    tmp_path: Path,
    *,
    env_auto_dismiss: bool = False,
    prompt: str = "do stuff",
    raw_resolved_prompt: str | None = None,
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
        info = extract_directives_and_write_meta(
            prompt,
            workspace,
            artifacts,
            raw_resolved_prompt=raw_resolved_prompt,
        )

    meta_path = os.path.join(artifacts, "agent_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {}
    return {"info": info, "meta": meta}


class TestExtractDirectivesAutoDismiss:
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
        """A raw top-level #resume picks the first available .r slot."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="expanded prompt",
                raw_resolved_prompt="#resume:foo do stuff",
            )
        assert result["info"].name == "foo.r1"
        assert result["meta"].get("name") == "foo.r1"

    def test_explicit_name_wins_over_resume(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name:bar expanded prompt",
                raw_resolved_prompt="%name:bar #resume:foo do stuff",
            )
        assert result["info"].name == "bar"
        assert result["meta"].get("name") == "bar"

    def test_bare_name_uses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=False,
                prompt="%name expanded prompt",
                raw_resolved_prompt="%name #resume:foo do stuff",
            )
        assert result["info"].name == "foo.r1"
        assert result["meta"].get("name") == "foo.r1"

    def test_auto_dismiss_suppresses_resume_derived_name(self, tmp_path: Path) -> None:
        with patch.object(Path, "home", return_value=tmp_path):
            result = _run_extract(
                tmp_path,
                env_auto_dismiss=True,
                raw_resolved_prompt="#resume:foo do stuff",
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
