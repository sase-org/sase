"""Layered declarations for AXE routine origins.

Binding-backed composition tests: the real Rust composition reports the
first declaring layer of every inventory entry, so user overrides keep the
builtin/plugin origin, overlay and project-local declarations read as
user, and fresh layer data recomposes (never reuses stale maps).
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import patch

from sase.axe.config import AxeConfig, load_axe_config
from sase.config.core import ConfigLayer

pytest_plugins = ("tests._axe_routine_origin_helpers",)


def _config_layer(
    name: str, routine: str, body: dict[str, Any], *, path: str | None = None
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=True,
        list_strategy="concatenate",
        data={"axe": {"lumberjacks": {routine: body}}},
    )


def _routine_body(
    description: str = "Do things",
    interval: int = 60,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "description": description,
        "interval": interval,
        "chops": [{"name": "fast", "description": "Fast job"}],
    }
    if extra:
        body.update(extra)
    return body


def _load_with_layers(layers: list[ConfigLayer]) -> AxeConfig:
    with patch("sase.axe.config.load_config_layers", return_value=layers):
        return load_axe_config()


def test_user_override_keeps_builtin_origin(
    reset_axe_config_cache: Any,
) -> None:
    """A builtin routine with a user interval override stays builtin."""
    config = _load_with_layers(
        [
            _config_layer("default", "checks", _routine_body()),
            _config_layer(
                "user",
                "checks",
                {"interval": 5},
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["checks"]
    assert routine.interval == 5
    assert routine.source == "builtin"
    assert routine.declared_by == "default"
    assert routine.chops[0].source == "builtin"


def test_plugin_declaration_overridden_by_user_stays_plugin(
    reset_axe_config_cache: Any,
) -> None:
    """A plugin routine with user overrides remains plugin."""
    config = _load_with_layers(
        [
            _config_layer("plugin:acme", "hooks", _routine_body()),
            _config_layer(
                "user",
                "hooks",
                {"interval": 5},
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["hooks"]
    assert routine.source == "plugin"
    assert routine.declared_by == "plugin:acme"
    assert routine.chops[0].source == "plugin"
    assert routine.chops[0].declared_by == "plugin:acme"


def test_overlay_and_local_declarations_are_user(
    reset_axe_config_cache: Any,
) -> None:
    """Overlay and project-local declarations read as user origin."""
    config = _load_with_layers(
        [
            _config_layer(
                "overlay:work.yml",
                "overtime",
                _routine_body(),
                path="/conf/work.yml",
            ),
            _config_layer(
                "local",
                "oncall",
                _routine_body(),
                path="/proj/sase/sase.yml",
            ),
        ]
    )
    assert config.lumberjacks["overtime"].source == "user"
    assert (
        config.lumberjacks["overtime"].declared_by == "overlay:work.yml:/conf/work.yml"
    )
    assert config.lumberjacks["oncall"].source == "user"
    assert config.lumberjacks["oncall"].declared_by == "local:/proj/sase/sase.yml"


def test_job_added_under_builtin_routine_has_own_origin(
    reset_axe_config_cache: Any,
) -> None:
    """A user job under a builtin routine is user; the routine is builtin."""
    config = _load_with_layers(
        [
            _config_layer("default", "checks", _routine_body()),
            _config_layer(
                "user",
                "checks",
                {
                    "chops": {
                        "mine": {
                            "description": "My extra job",
                            "script": "mine-script",
                        }
                    }
                },
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["checks"]
    assert routine.source == "builtin"
    by_name = {chop.name: chop for chop in routine.chops}
    assert by_name["fast"].source == "builtin"
    assert by_name["mine"].source == "user"
    assert by_name["mine"].declared_by == "user:/conf/sase.yml"


def test_project_local_routine_matches_scheduler_effective_config(
    reset_axe_config_cache: Any,
) -> None:
    """Project-local routines are visible to the scheduler as user.

    The scheduler loads through the same ``load_axe_config`` path, so a
    local declaration the scheduler runs also labels user here.
    """
    from sase.main.axe_handler import load_axe_config_with_overrides

    layers = [
        _config_layer("default", "checks", _routine_body()),
        _config_layer(
            "local",
            "oncall",
            _routine_body(),
            path="/proj/sase/sase.yml",
        ),
    ]
    with patch("sase.axe.config.load_config_layers", return_value=layers):
        config = load_axe_config()
    assert config.lumberjacks["oncall"].source == "user"

    with patch("sase.axe.config.load_config_layers", return_value=layers):
        scheduled = load_axe_config_with_overrides(argparse.Namespace())
    assert set(scheduled.lumberjacks) == set(config.lumberjacks)
    assert scheduled.lumberjacks["oncall"].source == "user"


def test_config_token_change_invalidates_origin_map(
    reset_axe_config_cache: Any,
) -> None:
    """New layer data recomposes origins; stale maps never linger."""
    first = _load_with_layers(
        [_config_layer("user", "hooks", _routine_body(), path="/conf/sase.yml")]
    )
    assert first.lumberjacks["hooks"].source == "user"

    second = _load_with_layers(
        [
            _config_layer("default", "hooks", _routine_body()),
            _config_layer("user", "hooks", {"interval": 5}, path="/conf/sase.yml"),
        ]
    )
    assert second.lumberjacks["hooks"].source == "builtin"
    assert second.lumberjacks["hooks"].interval == 5
