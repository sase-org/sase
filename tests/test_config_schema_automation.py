"""Config schema coverage for Axe chops and Telegram commands."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema, with_machine_name


def _validate(config: dict[str, Any]) -> None:
    Draft7Validator(schema()).validate(with_machine_name(config))


def test_config_schema_accepts_script_chops_and_compound_durations() -> None:
    _validate(
        {
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "interval": 1,
                        "chop_timeout": "1d2h30m",
                        "chops": [
                            {
                                "name": "custom_check",
                                "script": "custom-check",
                                "run_every": "1h30m",
                                "timeout": "45s",
                            }
                        ],
                    }
                }
            }
        }
    )


def test_config_schema_accepts_declarative_chop_policies() -> None:
    _validate(
        {
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "interval": 60,
                        "chops": [
                            {
                                "name": "audit",
                                "inhibit_if": {
                                    "changespec": {
                                        "name_prefix": "audit_",
                                        "statuses": ["WIP", "Ready"],
                                    },
                                    "agent_hood": {"hood": "audit"},
                                    "agent_clan": {"name_prefix": "toobig-"},
                                },
                                "trigger": {
                                    "git.commits_since": {
                                        "project": "sase",
                                        "threshold": 20,
                                        "checkpoint_policy": "on_action_success",
                                    }
                                },
                                "once_per": {
                                    "key": "audit:{proposal.id}",
                                    "capacity": 100,
                                },
                            }
                        ],
                    }
                }
            }
        }
    )


def test_config_schema_accepts_keyed_chops_secret_refs_and_targets() -> None:
    _validate(
        {
            "axe": {
                "lumberjacks": {
                    "docs": {
                        "interval": 60,
                        "env": {
                            "TOKEN": {"env": "DOCS_TOKEN"},
                            "CHAT_ID": {"file": "~/.secrets/chat-id"},
                            "PASSWORD": {"pass": "services/docs"},
                        },
                        "chops": {
                            "refresh_docs": {
                                "script": "sase_chop_refresh_docs",
                                "enabled": True,
                                "vars": {"prompt": "Update docs"},
                                "for_each": {
                                    "source": "projects",
                                    "filters": {
                                        "names": ["sase"],
                                        "vcs": "gh",
                                    },
                                },
                            },
                            "old": {"enabled": False},
                        },
                    }
                }
            }
        }
    )


def test_config_schema_rejects_invalid_chop_secret_reference() -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "axe": {
                    "lumberjacks": {
                        "checks": {
                            "chops": {
                                "audit": {
                                    "env": {
                                        "TOKEN": {
                                            "env": "TOKEN",
                                            "file": "/tmp/token",
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent", "do work"),
        ("xprompt", "#!workflow"),
        ("run_every", "0s"),
        ("timeout", "1.5m"),
    ],
)
def test_config_schema_rejects_removed_or_invalid_chop_fields(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "axe": {
                    "lumberjacks": {
                        "checks": {
                            "interval": 1,
                            "chops": [{"name": "custom_check", field: value}],
                        }
                    }
                }
            }
        )


def test_config_schema_accepts_telegram_commands() -> None:
    _validate(
        {
            "telegram": {
                "commands": {
                    "tasks": {
                        "description": "Obsidian tasks dashboard as a PDF",
                        "run": "~/bin/tg_cmd_tasks --note dash.md",
                        "output": "pdf",
                        "timeout": "90s",
                    }
                }
            }
        }
    )


@pytest.mark.parametrize(
    "name",
    ["Tasks", "tasks-report", "", "a" * 33],
)
def test_config_schema_rejects_invalid_telegram_command_names(name: str) -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "telegram": {
                    "commands": {
                        name: {
                            "description": "Tasks dashboard",
                            "run": "tg_cmd_tasks",
                        }
                    }
                }
            }
        )


@pytest.mark.parametrize("missing", ["description", "run"])
def test_config_schema_requires_telegram_command_fields(missing: str) -> None:
    command = {
        "description": "Tasks dashboard",
        "run": "tg_cmd_tasks",
    }
    del command[missing]

    with pytest.raises(ValidationError):
        _validate({"telegram": {"commands": {"tasks": command}}})


def test_config_schema_rejects_invalid_telegram_command_output() -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "telegram": {
                    "commands": {
                        "tasks": {
                            "description": "Tasks dashboard",
                            "run": "tg_cmd_tasks",
                            "output": "document",
                        }
                    }
                }
            }
        )


@pytest.mark.parametrize("timeout", ["90", "1d", "1.5m", "soon"])
def test_config_schema_rejects_invalid_telegram_command_timeout(
    timeout: str,
) -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "telegram": {
                    "commands": {
                        "tasks": {
                            "description": "Tasks dashboard",
                            "run": "tg_cmd_tasks",
                            "timeout": timeout,
                        }
                    }
                }
            }
        )
