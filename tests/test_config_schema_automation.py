"""Config schema coverage for Axe chops and Telegram commands."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema


def _validate(config: dict[str, Any]) -> None:
    Draft7Validator(schema()).validate(config)


def test_config_schema_accepts_script_chops_and_compound_durations() -> None:
    _validate(
        {
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "description": "Run automated schema checks",
                        "interval": 1,
                        "chop_timeout": "1d2h30m",
                        "wait_runners": 0,
                        "chops": [
                            {
                                "name": "custom_check",
                                "description": "Run a custom schema check",
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


def test_config_schema_rejects_negative_lumberjack_wait_runners() -> None:
    with pytest.raises(ValidationError):
        _validate(
            {
                "axe": {
                    "lumberjacks": {
                        "checks": {
                            "description": "Run automated schema checks",
                            "wait_runners": -1,
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
                        "description": "Run policy schema checks",
                        "interval": 60,
                        "chops": [
                            {
                                "name": "audit",
                                "description": "Audit configured changes",
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
                        "description": "Refresh project documentation",
                        "interval": 60,
                        "env": {
                            "TOKEN": {"env": "DOCS_TOKEN"},
                            "CHAT_ID": {"file": "~/.secrets/chat-id"},
                            "PASSWORD": {"pass": "services/docs"},
                        },
                        "chops": {
                            "refresh_docs": {
                                "description": "Refresh project documentation",
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
                            "old": {
                                "description": "Retain a disabled documentation check",
                                "enabled": False,
                            },
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
                            "description": "Run secret reference checks",
                            "chops": {
                                "audit": {
                                    "description": "Audit secret references",
                                    "env": {
                                        "TOKEN": {
                                            "env": "TOKEN",
                                            "file": "/tmp/token",
                                        }
                                    },
                                }
                            },
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
                            "description": "Run invalid-field checks",
                            "interval": 1,
                            "chops": [
                                {
                                    "name": "custom_check",
                                    "description": "Run a custom schema check",
                                    field: value,
                                }
                            ],
                        }
                    }
                }
            }
        )


def test_config_schema_requires_nonblank_axe_descriptions() -> None:
    config_schema = schema()
    chop_schema = config_schema["definitions"]["axeChop"]
    lumberjack_schema = config_schema["properties"]["axe"]["properties"]["lumberjacks"][
        "additionalProperties"
    ]
    list_chop_schema = lumberjack_schema["properties"]["chops"]["items"]["oneOf"][1]

    assert chop_schema["required"] == ["description"]
    assert chop_schema["properties"]["description"]["minLength"] == 1
    assert chop_schema["properties"]["description"]["maxLength"] == 2000
    assert lumberjack_schema["required"] == ["description"]
    assert lumberjack_schema["properties"]["description"]["minLength"] == 1
    assert lumberjack_schema["properties"]["description"]["maxLength"] == 2000
    assert list_chop_schema["required"] == ["name", "description"]
    assert list_chop_schema["properties"]["description"]["minLength"] == 1
    assert list_chop_schema["properties"]["description"]["maxLength"] == 2000


@pytest.mark.parametrize(
    "config",
    [
        {
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "chops": {
                            "audit": {
                                "description": "Audit configured changes",
                            }
                        }
                    }
                }
            }
        },
        {
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "description": "Run audit checks",
                        "chops": {"audit": {}},
                    }
                }
            }
        },
    ],
)
def test_config_schema_rejects_missing_axe_descriptions(
    config: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _validate(config)


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
