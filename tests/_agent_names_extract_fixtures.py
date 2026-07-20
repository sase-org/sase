"""Shared helpers for agent-name directive extraction tests."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


def mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.resolve_model_name.return_value = "test-model"
    return provider


def run_extract(
    tmp_path: Path,
    *,
    env_auto_dismiss: bool = False,
    planned_name: str | None = None,
    planned_name_owner: str | Path | None = None,
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
    if planned_name is not None:
        from sase.agent.names import reserve_registered_name

        reserve_registered_name(
            planned_name,
            artifacts if planned_name_owner is None else planned_name_owner,
        )

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
        patch("sase.llm_provider.registry.get_provider", return_value=mock_provider()),
        patch(
            "sase.llm_provider.registry.resolve_model_provider",
            return_value=("test", "test-model"),
        ),
        patch("sase.vcs_provider._registry.detect_vcs", return_value=None),
    ):
        # Remove variables that could have leaked from the outer environment.
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
        bead_env = os.environ.get("SASE_BEAD_ID")

    meta_path = os.path.join(artifacts, "agent_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {}
    return {
        "info": info,
        "meta": meta,
        "artifacts": artifacts,
        "bead_env": bead_env,
    }
