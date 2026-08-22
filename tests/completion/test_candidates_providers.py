"""Tests for kind -> provider dispatch and catalog-backed candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.completion.candidates.protocol import Candidate
from sase.completion.candidates.providers import candidates_for


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    monkeypatch.delenv("SASE_SDD_BEADS_DIR", raising=False)
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)


def test_artifact_relation_candidates_include_cli_slugs() -> None:
    values = {
        candidate.value
        for candidate in candidates_for(
            "artifact_relation", "", project=None, limit=200
        )
    }
    assert {"related", "implements", "supersedes", "derives-from"} <= values


def test_directive_candidates_use_shared_contract_and_expose_final() -> None:
    result = candidates_for("directive", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"model", "effort", "id", "wait", "auto", "final"} <= values
    model = next(candidate for candidate in result if candidate.value == "model")
    assert "Override the LLM model" in model.description
    assert "alias %m" in model.description


def test_candidates_for_unknown_kind_returns_empty_list() -> None:
    assert candidates_for("bogus", "", project=None, limit=200) == []


def test_candidates_for_kind_without_shipped_provider_returns_empty_list() -> None:
    # path/dir are declared ValueKinds but stay shell-native, with no provider.
    assert candidates_for("path", "", project=None, limit=200) == []
    assert candidates_for("dir", "", project=None, limit=200) == []


def test_flag_candidates_come_from_the_in_process_registry() -> None:
    result = candidates_for("flag", "", project=None, limit=200)

    keys = {candidate.value for candidate in result}
    assert "ref_sync_gesture" in keys
    assert "coder_inherits_planner_chat" not in keys
    assert "completion_refresh_on_update" not in keys
    ref_sync = next(
        candidate for candidate in result if candidate.value == "ref_sync_gesture"
    )
    assert ref_sync.description.startswith("sunset:")


def test_model_candidates_are_the_builtin_size_aliases() -> None:
    result = candidates_for("model", "", project=None, limit=200)

    assert [candidate.value for candidate in result] == [
        "xsmall",
        "small",
        "medium",
        "large",
        "xlarge",
    ]


def test_snippet_candidates_use_rust_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase").mkdir()
    calls: list[tuple[str | None, str]] = []

    def fake_loader(project: str | None, root_dir: str) -> dict[str, object]:
        calls.append((project, root_dir))
        return {
            "entries": [
                {
                    "trigger": "todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {
                    "trigger": "Todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {"trigger": "fixit", "source": "xprompt", "xprompt_name": "fix"},
                {"trigger": "", "source": "ignored"},
            ]
        }

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            fake_loader
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    result = candidates_for("snippet", "", project="demo", limit=200)

    assert result == [
        Candidate("todo", "user_config · ace.snippets"),
        Candidate("Todo", "user_config · ace.snippets"),
        Candidate("fixit", "xprompt · fix"),
    ]
    assert calls == [("demo", str(tmp_path))]


@pytest.mark.parametrize("payload", [{"entries": "bad"}, ["bad"]])
def test_snippet_candidates_degrade_on_malformed_payload(
    payload: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            (lambda _project, _root_dir: payload)
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_snippet_candidates_degrade_on_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    def raise_native_error(_project: str | None, _root_dir: str) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            raise_native_error
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_tag_candidates_come_from_the_xprompt_tag_enum() -> None:
    result = candidates_for("tag", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"vcs", "commit", "land_epic"} <= values


def test_xprompt_and_skill_candidates_include_packaged_names() -> None:
    xprompts = candidates_for("xprompt", "", project=None, limit=200)
    skills = candidates_for("skill", "", project=None, limit=200)

    assert any(candidate.value == "coder" for candidate in xprompts)
    assert any(candidate.value == "sase_repo" for candidate in skills)


def test_provider_errors_return_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.feature_flags.registry as flag_registry

    monkeypatch.setattr(
        flag_registry,
        "feature_flag_definitions",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert candidates_for("flag", "", project=None, limit=200) == []
