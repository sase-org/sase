"""Tests for parsing axe lumberjack and chop config."""

from unittest.mock import patch

import pytest

from sase.axe.config import (
    AxeConfigError,
    ChopConfig,
    _parse_duration,
    _parse_lumberjacks,
)


def test_parse_lumberjacks_skips_non_dict_entries() -> None:
    """Test that non-dict entries are skipped."""
    raw = {
        "hooks": {
            "description": "Run hook checks",
            "interval": 1,
            "chops": [],
        },
        "bad": "not a dict",
    }
    result = _parse_lumberjacks(raw)
    assert len(result) == 1
    assert "hooks" in result


def test_parse_lumberjacks_round_trips_description() -> None:
    raw = {
        "checks": {
            "description": "Poll slower checks every five minutes",
            "interval": 300,
            "chops": [],
        }
    }

    result = _parse_lumberjacks(raw)

    assert result["checks"].description == "Poll slower checks every five minutes"


def test_parse_lumberjacks_caches_normalized_description_parts() -> None:
    raw = {
        "checks": {
            "description": "  Poll slower checks  \r\n\r\n  Every five minutes.  ",
            "interval": 300,
            "chops": {
                "audit": {"description": "Audit releases\n\nCheck tags and artifacts."}
            },
        }
    }

    lumberjack = _parse_lumberjacks(raw)["checks"]

    assert lumberjack.description_summary == "Poll slower checks"
    assert lumberjack.description_body == "  Every five minutes."
    assert lumberjack.chops[0].description_summary == "Audit releases"
    assert lumberjack.chops[0].description_body == "Check tags and artifacts."


def test_chop_config_run_every_defaults_to_none() -> None:
    """Test that run_every defaults to None (run every tick)."""
    chop = ChopConfig(name="test", description="")
    assert chop.run_every is None


def test_parse_duration_seconds() -> None:
    """Test parsing duration with seconds unit."""
    assert _parse_duration("30s") == 30


def test_parse_duration_minutes() -> None:
    """Test parsing duration with minutes unit."""
    assert _parse_duration("60m") == 3600


def test_parse_duration_hours() -> None:
    """Test parsing duration with hours unit."""
    assert _parse_duration("2h") == 7200


def test_parse_duration_days_and_compound_values() -> None:
    assert _parse_duration("1d2h30m") == 95_400


def test_parse_duration_invalid() -> None:
    """Test that invalid duration values return None."""
    assert _parse_duration("bad") is None
    assert _parse_duration(60) is None
    assert _parse_duration("") is None
    assert _parse_duration("10x") is None


def test_parse_lumberjacks_run_every_from_dict() -> None:
    """Test that run_every is parsed from duration string in dict chop entries."""
    raw = {
        "checks": {
            "description": "Run slower checks",
            "interval": 60,
            "chops": [
                {
                    "name": "slow_check",
                    "description": "Run a throttled check",
                    "run_every": "5m",
                }
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["checks"].chops[0].run_every == 300


def test_parse_lumberjacks_normalizes_declarative_chop_policy() -> None:
    raw = {
        "checks": {
            "description": "Run declarative policy checks",
            "interval": 60,
            "chops": [
                {
                    "name": "audit",
                    "description": "Audit configured changes",
                    "inhibit_if": {
                        "changespec": {"name_prefix": "audit_"},
                        "agent_hood": [{"hood": "audit"}],
                        "agent_clan": {"name_prefix": "toobig-"},
                    },
                    "trigger": {
                        "git.commits_since": {
                            "project": "sase",
                            "threshold": 5,
                            "checkpoint": "on_action_success",
                        }
                    },
                    "once_per": {"key": "audit:{proposal.id}", "capacity": 50},
                }
            ],
        }
    }

    chop = _parse_lumberjacks(raw)["checks"].chops[0]

    assert chop.inhibit_if == [
        {"provider": "changespec", "name_prefix": "audit_"},
        {"provider": "agent_hood", "hood": "audit"},
        {"provider": "agent_clan", "name_prefix": "toobig-"},
    ]
    assert chop.trigger == {
        "provider": "git.commits_since",
        "project": "sase",
        "threshold": 5,
        "checkpoint_policy": "on_action_success",
    }
    assert chop.once_per == {"key": "audit:{proposal.id}", "capacity": 50}


def test_parse_lumberjacks_map_form_merges_env_and_expands_literal_targets() -> None:
    raw = {
        "docs": {
            "description": "Refresh project documentation",
            "interval": 60,
            "env": {
                "SHARED": "lumberjack",
                "TOKEN": {"env": "DOCS_TOKEN"},
            },
            "chops": {
                "refresh_docs": {
                    "description": "Refresh project documentation",
                    "script": "sase_chop_refresh_docs",
                    "env": {"SHARED": "chop"},
                    "vars": {"prompt": "Update docs"},
                    "for_each": [
                        {
                            "name": "sase-core",
                            "workspace": "gh:sase-org/sase-core",
                            "overrides": {"run_every": "1h30m"},
                        },
                        {"name": "sase"},
                    ],
                },
                "retired": {
                    "description": "Retain a disabled documentation check",
                    "enabled": False,
                },
            },
        }
    }

    docs = _parse_lumberjacks(raw)["docs"]

    assert [chop.name for chop in docs.chops] == [
        "refresh_docs[sase-core]",
        "refresh_docs[sase]",
        "retired",
    ]
    core = docs.chops[0]
    assert core.parent_name == "refresh_docs"
    assert core.script_name == "sase_chop_refresh_docs"
    assert core.target_key == "sase-core"
    assert core.target["workspace"] == "gh:sase-org/sase-core"
    assert core.run_every == 5400
    assert core.env == {"SHARED": "chop", "TOKEN": {"env": "DOCS_TOKEN"}}
    assert core.vars == {"prompt": "Update docs"}
    assert docs.chops[-1].enabled is False
    assert docs.chop_names == ["refresh_docs[sase-core]", "refresh_docs[sase]"]


def test_parse_lumberjacks_project_source_uses_target_templates() -> None:
    raw = {
        "docs": {
            "description": "Refresh project documentation",
            "interval": 60,
            "chops": {
                "refresh_docs": {
                    "description": "Refresh project documentation",
                    "trigger": {
                        "git.commits_since": {
                            "project": "{target.name}",
                            "threshold": 5,
                        }
                    },
                    "for_each": {"source": "projects", "names": ["sase"]},
                }
            },
        }
    }
    rows = [
        {
            "name": "sase",
            "project": "gh_sase-org__sase",
            "vcs": "gh",
            "workspace": "gh:sase-org/sase",
            "enabled": True,
        },
        {"name": "other", "vcs": "git", "enabled": True},
    ]

    with patch("sase.axe.config._project_target_rows", return_value=rows):
        chop = _parse_lumberjacks(raw)["docs"].chops[0]

    assert chop.name == "refresh_docs[sase]"
    assert chop.trigger["project"] == "sase"
    assert chop.target["workspace"] == "gh:sase-org/sase"


def test_parse_lumberjacks_revalidates_rendered_target_templates() -> None:
    raw = {
        "docs": {
            "description": "Refresh project documentation",
            "interval": 60,
            "chops": {
                "refresh_docs": {
                    "description": "Refresh project documentation",
                    "trigger": {
                        "git.commits_since": {
                            "project": "{target.project}",
                            "threshold": 5,
                        }
                    },
                    "for_each": [{"name": "missing-project", "project": ""}],
                }
            },
        }
    }

    with pytest.raises(AxeConfigError, match="must be a non-blank string"):
        _parse_lumberjacks(raw)


def test_parse_lumberjacks_wraps_target_expansion_errors() -> None:
    raw = {
        "docs": {
            "description": "Refresh project documentation",
            "interval": 60,
            "chops": {
                "refresh_docs": {
                    "description": "Refresh project documentation",
                    "for_each": [{"name": "sase"}, {"name": "sase"}],
                }
            },
        }
    }

    with pytest.raises(AxeConfigError, match="target_expansion_failed"):
        _parse_lumberjacks(raw)


def test_parse_lumberjacks_run_every_invalid_becomes_none() -> None:
    """Test that invalid run_every values become None (run every tick)."""
    raw = {
        "checks": {
            "description": "Run cadence parsing checks",
            "interval": 60,
            "chops": [
                {
                    "name": "bare_int",
                    "description": "Check integer cadence parsing",
                    "run_every": 60,
                },
                {
                    "name": "bad_string",
                    "description": "Check invalid cadence parsing",
                    "run_every": "bad",
                },
                {
                    "name": "missing",
                    "description": "Check missing cadence parsing",
                },
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    for chop in result["checks"].chops:
        assert chop.run_every is None


def test_parse_lumberjacks_map_chops_get_default_run_every() -> None:
    """Test that map-form chops get default run_every=None."""
    raw = {
        "hooks": {
            "description": "Run hook checks",
            "interval": 1,
            "chops": {
                "hook_checks": {
                    "description": "Check hooks",
                }
            },
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chops[0].run_every is None


def test_parse_lumberjacks_chop_timeout() -> None:
    """Test that chop_timeout is parsed from the lumberjack config."""
    raw = {
        "hooks": {
            "description": "Run hook checks",
            "interval": 5,
            "chop_timeout": "30s",
            "chops": [
                {
                    "name": "hook_checks",
                    "description": "Check hooks",
                }
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chop_timeout == 30


def test_parse_lumberjacks_chop_timeout_defaults_to_none() -> None:
    """Test that missing chop_timeout defaults to None."""
    raw = {
        "hooks": {
            "description": "Run hook checks",
            "interval": 5,
            "chops": [],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chop_timeout is None


def test_parse_lumberjacks_wait_runners() -> None:
    raw = {
        "checks": {
            "description": "Run checks when the machine is quiet",
            "interval": 60,
            "wait_runners": 0,
            "chops": [],
        },
    }

    result = _parse_lumberjacks(raw)

    assert result["checks"].wait_runners == 0


def test_parse_lumberjacks_wait_runners_defaults_to_none() -> None:
    raw = {
        "checks": {
            "description": "Run checks at the global runner limit",
            "interval": 60,
            "chops": [],
        },
    }

    result = _parse_lumberjacks(raw)

    assert result["checks"].wait_runners is None


def test_parse_lumberjacks_per_chop_timeout() -> None:
    """Test that per-chop timeout is parsed from dict chop entries."""
    raw = {
        "hooks": {
            "description": "Run hook checks",
            "interval": 5,
            "chops": [
                {
                    "name": "slow_chop",
                    "description": "Run a slow check",
                    "timeout": "10s",
                },
                {
                    "name": "fast_chop",
                    "description": "Run a fast check",
                },
            ],
        },
    }
    result = _parse_lumberjacks(raw)
    assert result["hooks"].chops[0].timeout == 10
    assert result["hooks"].chops[1].timeout is None
