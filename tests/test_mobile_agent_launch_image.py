"""Tests for launching mobile image agents."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pytest

from sase.agent.launcher import AgentLaunchResult
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _launch_mobile_image_agents,
    handle_mobile_agent_bridge,
)
from tests._mobile_agents_fixtures import _PNG_BYTES, _image_request


def test_launch_mobile_image_agents_stores_upload_and_launches(
    monkeypatch, tmp_path: Path
) -> None:
    captured: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp="260506_143000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)

    payload = _launch_mobile_image_agents(_image_request(request_id="req-image-1"))

    assert payload["primary"]["status"] == "launched"
    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == _PNG_BYTES
    assert "The image has been saved to:" in captured[0]
    assert str(stored_files[0]) in captured[0]
    assert "%name:mobile.image" in captured[0]
    contexts = (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"request_id": "req-image-1"' in contexts


def test_launch_mobile_image_rejects_invalid_base64_without_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(json.dumps(_image_request(base64_image="not base64!!!"))),
        stderr=stderr,
    )

    assert code == 3
    assert "invalid base64 image data" in stderr.getvalue()
    assert not (tmp_path / "mobile_gateway" / "uploads").exists()


def test_launch_mobile_image_rejects_extension_content_type_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(
            json.dumps(
                _image_request(
                    original_filename="screen.jpg",
                    content_type="image/png",
                )
            )
        ),
        stderr=stderr,
    )

    assert code == 3
    assert "image extension does not match content type" in stderr.getvalue()


def test_launch_mobile_image_rejects_oversize_before_write(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(json.dumps(_image_request(byte_length=10 * 1024 * 1024 + 1))),
        stderr=stderr,
    )

    assert code == 3
    assert "image upload exceeds maximum size" in stderr.getvalue()
    assert not (tmp_path / "mobile_gateway" / "uploads").exists()


def test_launch_mobile_image_path_traversal_filename_is_not_used(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(
        mobile_agents,
        "launch_agents_from_cwd",
        lambda _prompt: [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp="260506_143000",
            )
        ],
    )

    _launch_mobile_image_agents(
        _image_request(original_filename="../../caller-name.png")
    )

    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1
    assert stored_files[0].name != "caller-name.png"
    assert not (tmp_path / "caller-name.png").exists()


def test_launch_mobile_image_keeps_stored_file_when_launch_fails(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def fail_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise RuntimeError("launch boom")

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fail_launch)

    with pytest.raises(Exception, match="launch boom"):
        _launch_mobile_image_agents(_image_request())

    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1
