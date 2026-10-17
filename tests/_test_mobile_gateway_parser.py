"""Mobile command parser tests."""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser


def test_parser_accepts_mobile_gateway_pair() -> None:
    args = create_parser().parse_args(
        [
            "mobile",
            "gateway",
            "pair",
            "-b",
            "127.0.0.1",
            "-p",
            "7630",
            "-H",
            "/tmp/sase",
        ]
    )

    assert args.command == "mobile"
    assert args.mobile_subcommand == "gateway"
    assert args.mobile_gateway_subcommand == "pair"
    assert args.bind_address == "127.0.0.1"
    assert args.port == 7630
    assert args.state_dir == "/tmp/sase"


def test_parser_accepts_mobile_gateway_start() -> None:
    args = create_parser().parse_args(
        [
            "mobile",
            "gateway",
            "start",
            "-b",
            "127.0.0.1",
            "-p",
            "7630",
            "-H",
            "/tmp/sase",
            "-L",
            "-c",
            "sase_gateway",
            "-T",
            "1",
            "-A",
            "sase",
            "-J",
            "sase-helper",
            "-P",
            "fcm",
            "-F",
            "demo-project",
            "-S",
            "/tmp/fcm.json",
            "-E",
            "SASE_FCM_TOKEN",
            "-D",
            "-U",
            "2.5",
            "-R",
            "3",
        ]
    )

    assert args.command == "mobile"
    assert args.mobile_subcommand == "gateway"
    assert args.mobile_gateway_subcommand == "start"
    assert args.bind_address == "127.0.0.1"
    assert args.port == 7630
    assert args.state_dir == "/tmp/sase"
    assert args.allow_non_loopback is True
    assert args.gateway_command == "sase_gateway"
    assert args.startup_timeout == 1
    assert args.agent_bridge_command == "sase"
    assert args.helper_bridge_command == "sase-helper"
    assert args.push_provider == "fcm"
    assert args.fcm_project_id == "demo-project"
    assert args.fcm_service_account_json == "/tmp/fcm.json"
    assert args.fcm_credential_env == "SASE_FCM_TOKEN"
    assert args.fcm_dry_run is True
    assert args.push_timeout_seconds == 2.5
    assert args.push_retry_limit == 3


def test_parser_accepts_mobile_helper_bridge_patch_tags() -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", "changespec-tags"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == "changespec-tags"


def test_parser_accepts_mobile_helper_bridge_macro_catalog() -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", "macro-catalog"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == "macro-catalog"


def test_parser_accepts_legacy_mobile_helper_bridge_catalog() -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", "xprompt-catalog"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == "xprompt-catalog"


def test_parser_accepts_mobile_helper_bridge_update_start() -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", "update-start"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == "update-start"


def test_parser_accepts_mobile_helper_bridge_update_status() -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", "update-status"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == "update-status"


@pytest.mark.parametrize("operation", ["beads-list", "beads-show"])
def test_parser_accepts_mobile_helper_bridge_bead_operations(operation: str) -> None:
    args = create_parser().parse_args(["mobile", "helper-bridge", operation])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "helper-bridge"
    assert args.mobile_helper_bridge_subcommand == operation


def test_parser_accepts_mobile_agent_bridge_launch_text() -> None:
    args = create_parser().parse_args(["mobile", "agent-bridge", "launch-text"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "agent-bridge"
    assert args.mobile_agent_bridge_subcommand == "launch-text"


def test_parser_accepts_mobile_agent_bridge_launch_image() -> None:
    args = create_parser().parse_args(["mobile", "agent-bridge", "launch-image"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "agent-bridge"
    assert args.mobile_agent_bridge_subcommand == "launch-image"


def test_parser_accepts_mobile_agent_bridge_kill_agent() -> None:
    args = create_parser().parse_args(["mobile", "agent-bridge", "kill-agent"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "agent-bridge"
    assert args.mobile_agent_bridge_subcommand == "kill-agent"


def test_parser_accepts_mobile_agent_bridge_retry_agent() -> None:
    args = create_parser().parse_args(["mobile", "agent-bridge", "retry-agent"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "agent-bridge"
    assert args.mobile_agent_bridge_subcommand == "retry-agent"


def test_parser_accepts_mobile_agent_bridge_fork_agent() -> None:
    args = create_parser().parse_args(["mobile", "agent-bridge", "fork-agent"])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "agent-bridge"
    assert args.mobile_agent_bridge_subcommand == "fork-agent"


@pytest.mark.parametrize("operation", ["gate-action", "question-action"])
def test_parser_accepts_mobile_notification_bridge(operation: str) -> None:
    args = create_parser().parse_args(["mobile", "notification-bridge", operation])

    assert args.command == "mobile"
    assert args.mobile_subcommand == "notification-bridge"
    assert args.mobile_notification_bridge_subcommand == operation
