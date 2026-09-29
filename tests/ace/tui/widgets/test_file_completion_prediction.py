"""Tests for the non-blocking next-word prediction widget accessor."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.widgets import _file_completion_prediction as prediction_module
from sase.ace.tui.widgets._file_completion_prediction import (
    FileCompletionPredictionMixin,
)
from sase.core.prompt_prediction_wire import (
    PromptPredictionCandidate,
    PromptPredictionResult,
    PromptPredictionSourceShares,
)


class _FakeModel:
    """Stand-in prediction model recording requests and replaying a result."""

    def __init__(
        self,
        result: PromptPredictionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.requests: list[Any] = []

    def predict(self, request: Any) -> PromptPredictionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class _StubApp:
    def __init__(self) -> None:
        self.model: Any = None
        self.project: str | None = None
        self.disabled = False
        self.deletions = frozenset()
        self.warms = 0
        self.settings_gate = True

    def get_prompt_prediction_model(self) -> Any:
        return self.model

    def get_prompt_prediction_project(self, _text: str) -> str | None:
        return self.project

    def prompt_prediction_disabled(self) -> bool:
        return self.disabled

    def disable_prompt_prediction(self) -> None:
        self.disabled = True

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return self.deletions

    def warm_prompt_prediction(self) -> None:
        self.warms += 1

    def get_prompt_completion_settings(self) -> Any:
        return None


class _StubWidget(FileCompletionPredictionMixin):
    def __init__(self, app: _StubApp) -> None:
        self.app = app


@pytest.fixture
def app() -> _StubApp:
    return _StubApp()


@pytest.fixture
def widget(app: _StubApp, monkeypatch: pytest.MonkeyPatch) -> _StubWidget:
    monkeypatch.setattr(
        "sase.core.prompt_prediction_facade.PromptPredictionModel", _FakeModel
    )
    monkeypatch.setattr(prediction_module, "_prediction_error_logged", False)
    return _StubWidget(app)


def _result(ghost: list[str], candidates: list[str]) -> PromptPredictionResult:
    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=True,
        ghost=list(ghost),
        candidates=[
            PromptPredictionCandidate(
                word=word,
                key=word.lower(),
                score=0.9,
                probability=0.8,
                support=4,
                order=2,
                source_shares=PromptPredictionSourceShares(history=1.0),
                continuation=[],
            )
            for word in candidates
        ],
    )


def test_cold_without_model_degrades_to_silence(
    app: _StubApp, widget: _StubWidget
) -> None:
    assert widget._prompt_prediction_is_cold() is True
    assert widget._predict_next_words("help me") is None


def test_predict_passes_project_and_returns_result(
    app: _StubApp, widget: _StubWidget
) -> None:
    app.model = _FakeModel(result=_result(["implement"], ["implement"]))
    app.project = "sase"
    predicted = widget._predict_next_words("help me", limit=3, max_words=2)
    assert predicted is not None
    assert predicted.ghost == ["implement"]
    assert [candidate.word for candidate in predicted.candidates] == ["implement"]
    assert app.model.requests[0].project == "sase"
    assert app.model.requests[0].limit == 3
    assert app.model.requests[0].max_words == 2
    assert widget._prompt_prediction_is_cold() is False


def test_predict_truncates_ghost_before_deleted_word(
    app: _StubApp, widget: _StubWidget
) -> None:
    app.model = _FakeModel(
        result=_result(["implement", "obsolete", "plan"], ["implement", "obsolete"])
    )
    app.deletions = frozenset({"Obsolete"})
    predicted = widget._predict_next_words("help me")
    assert predicted is not None
    assert predicted.ghost == ["implement"]
    assert [candidate.word for candidate in predicted.candidates] == ["implement"]


def test_predict_failure_disables_session_and_logs_once(
    app: _StubApp, widget: _StubWidget, caplog: pytest.LogCaptureFixture
) -> None:
    app.model = _FakeModel(error=RuntimeError("core blew up"))
    with caplog.at_level("ERROR"):
        assert widget._predict_next_words("help me") is None
        assert widget._predict_next_words("help me") is None
    assert app.disabled is True
    assert (
        len([record for record in caplog.records if "disabled" in record.message]) == 1
    )


def test_predict_short_circuits_when_session_disabled(
    app: _StubApp, widget: _StubWidget
) -> None:
    app.model = _FakeModel(result=_result(["implement"], ["implement"]))
    app.disabled = True
    assert widget._predict_next_words("help me") is None
    assert app.model.requests == []


def test_schedule_load_warms_and_mount_warm_gates_on_harness(
    app: _StubApp, widget: _StubWidget
) -> None:
    widget._schedule_prompt_prediction_load()
    widget._warm_prompt_prediction_cache()
    assert app.warms == 2


def test_mount_warm_skips_harness_without_settings(
    widget: _StubWidget,
) -> None:
    widget.app = None  # type: ignore[assignment]
    widget._warm_prompt_prediction_cache()  # Must not raise.


def test_missing_app_provider_degrades_to_silence(
    widget: _StubWidget,
) -> None:
    widget.app = object()
    assert widget._prompt_prediction_is_cold() is True
    assert widget._predict_next_words("help me") is None
    assert widget._prompt_prediction_project("help me") is None
    widget._schedule_prompt_prediction_load()  # Must not raise.
