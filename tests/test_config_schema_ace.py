"""Schema coverage for ACE prompt, project, and artifact settings."""

from __future__ import annotations

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import REPO_ROOT, schema


pytestmark = pytest.mark.contract


def test_prompt_completion_history_word_count_default_contract() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    prompt_completion_schema = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]

    assert default_config["ace"]["prompt_completion"]["history_word_count"] == 10000
    assert (
        prompt_completion_schema["properties"]["history_word_count"]["default"] == 10000
    )


def test_prompt_completion_artifact_menu_default_contract() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    prompt_completion_schema = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]

    assert default_config["ace"]["prompt_completion"]["auto_artifact_menu"] is True
    assert (
        prompt_completion_schema["properties"]["auto_artifact_menu"]["default"] is True
    )


def test_prompt_completion_placeholder_ranking_schema_contract() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    prompt_completion = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]
    ranking = prompt_completion["properties"]["placeholder_ranking"]
    signals = prompt_completion["properties"]["placeholder_ranking_signals"]

    assert default_config["ace"]["prompt_completion"]["placeholder_ranking"] == "smart"
    assert (
        default_config["ace"]["prompt_completion"]["placeholder_ranking_signals"]
        is True
    )
    assert ranking["enum"] == ["smart", "recent"]
    assert ranking["default"] == "smart"
    assert signals["default"] is True
    Draft7Validator(public_schema).validate(
        {"ace": {"prompt_completion": {"placeholder_ranking": "recent"}}}
    )
    with pytest.raises(ValidationError):
        Draft7Validator(public_schema).validate(
            {"ace": {"prompt_completion": {"placeholder_ranking": "popular"}}}
        )


def test_prompt_completion_word_min_length_schema_contract() -> None:
    public_schema = schema()
    prompt_completion = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]
    word_min_length = prompt_completion["properties"]["word_min_length"]

    assert word_min_length["minimum"] == 1
    assert word_min_length["default"] == 5
    Draft7Validator(public_schema).validate(
        {"ace": {"prompt_completion": {"word_min_length": 3}}}
    )
    with pytest.raises(ValidationError):
        Draft7Validator(public_schema).validate(
            {"ace": {"prompt_completion": {"history_word_min_length": 3}}}
        )


def test_config_schema_validates_ace_prompt_spellcheck_settings() -> None:
    validator = Draft7Validator(schema())
    validator.validate(
        {
            "ace": {
                "prompt_spellcheck": {
                    "highlight": False,
                    "max_remembered_words": 1000,
                }
            }
        }
    )
    for invalid in (
        {"highlight": "yes"},
        {"max_remembered_words": -1},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"prompt_spellcheck": invalid}})


def test_config_schema_validates_ace_current_project_settings() -> None:
    validator = Draft7Validator(schema())
    documented = {
        "indicator": True,
        "seed_filters": True,
        "seed_agents_query": False,
    }
    validator.validate({"ace": {"current_project": documented}})
    validator.validate(
        {
            "ace": {
                "current_project": {
                    "indicator": False,
                    "seed_filters": False,
                    "seed_agents_query": True,
                }
            }
        }
    )
    public_schema = schema()
    current_project = public_schema["properties"]["ace"]["properties"][
        "current_project"
    ]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )

    assert default_config["ace"]["current_project"] == documented
    assert current_project["additionalProperties"] is False
    assert current_project["properties"]["indicator"]["default"] is True
    assert current_project["properties"]["seed_filters"]["default"] is True
    assert current_project["properties"]["seed_agents_query"]["default"] is False
    for invalid in (
        {"indicator": "yes"},
        {"seed_filters": 1},
        {"seed_agents_query": "false"},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"current_project": invalid}})


def test_config_schema_validates_ace_agents_sync_settings() -> None:
    validator = Draft7Validator(schema())
    validator.validate(
        {
            "ace": {
                "agents_sync": {
                    "check_interval_minutes": 5,
                    "recompute_interval_minutes": 30,
                    "indicator": False,
                }
            }
        }
    )
    for invalid in (
        {"check_interval_minutes": 0},
        {"recompute_interval_minutes": -1},
        {"indicator": "yes"},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"agents_sync": invalid}})


def test_config_schema_validates_ace_artifacts_relations_expanded() -> None:
    validator = Draft7Validator(schema())
    validator.validate({"ace": {"artifacts": {"relations_expanded": True}}})
    validator.validate({"ace": {"artifacts": {"relations_expanded": False}}})
    with pytest.raises(ValidationError):
        validator.validate({"ace": {"artifacts": {"relations_expanded": "yes"}}})
