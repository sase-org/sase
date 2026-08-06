"""Tests for build_pr_body's agent metadata footer."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.workflows.commit.pr_operations import build_pr_body


class TestBuildPrBody:
    """Verify build_pr_body reads agent_meta.json and sets _pr_body."""

    def test_sets_pr_body_with_full_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4", "llm_provider": "anthropic"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "add feature"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == (
                "add feature\n\n---\n"
                "**Model:** `anthropic/opus-4`\n"
                "**Agent:** `my-agent`"
            )

    def test_model_only_when_name_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"model": "opus-4", "llm_provider": "anthropic"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == ("msg\n\n---\n**Model:** `anthropic/opus-4`")

    def test_name_only_when_provider_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = {"name": "my-agent", "model": "opus-4"}
            (Path(tmpdir) / "agent_meta.json").write_text(json.dumps(meta))

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert payload["_pr_body"] == "msg\n\n---\n**Agent:** `my-agent`"

    def test_no_pr_body_when_meta_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "agent_meta.json").write_text("{}")

            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert "_pr_body" not in payload

    def test_no_pr_body_when_no_artifacts_dir(self) -> None:
        payload = {"message": "msg"}
        with patch.dict("os.environ", {}, clear=True):
            build_pr_body(payload)

        assert "_pr_body" not in payload

    def test_no_pr_body_when_meta_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {"message": "msg"}
            with patch.dict("os.environ", {"SASE_ARTIFACTS_DIR": tmpdir}):
                build_pr_body(payload)

            assert "_pr_body" not in payload
