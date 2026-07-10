"""Provider-level coverage for the bundled fakey CLI integration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from sase.ace.tui.provider_styles import provider_emoji_badge
from sase.doctor.checks_providers import setup_hint
from sase.llm_provider.fakey import FakeyProvider, _extract_usage
from sase.llm_provider.registry import (
    _build_llm_pm,
    _llm_metadata_payload,
    get_llm_metadata_payload,
    model_short_alias_map,
    model_to_provider_map,
    provider_cli_status_color_map,
    provider_short_name_map,
    resolve_model_provider,
)
from sase.llm_provider.retry_config import (
    _built_in_defaults,
    find_retry_config_for_error,
    get_retry_config,
    is_retryable_error,
)
from sase.llm_provider.types import LLMInvocationOptions
from sase.main.init_skills_handler import get_skill_target_providers


_CONTROL_ENV = (
    "FAKEY_SCENARIO",
    "FAKEY_REPLY",
    "FAKEY_FAIL_MESSAGE",
    "FAKEY_EXIT_CODE",
    "FAKEY_DELAY",
    "FAKEY_FAIL_TIMES",
    "SASE_FAKEY_PATH",
    "SASE_FAKEY_LARGE_ARGS",
    "SASE_FAKEY_SMALL_ARGS",
    "SASE_LLM_LARGE_ARGS",
    "SASE_LLM_SMALL_ARGS",
    "SASE_ARTIFACTS_DIR",
)


@pytest.fixture(autouse=True)
def _clean_fakey_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CONTROL_ENV:
        monkeypatch.delenv(name, raising=False)
    bundled_binary = Path(sys.executable).with_name("fakey")
    assert bundled_binary.is_file()
    monkeypatch.setenv("SASE_FAKEY_PATH", str(bundled_binary))


def _records(state_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(state_dir.glob("invocation-*.json"))
    ]


def _write_scenario(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_extract_usage_requires_a_valid_final_protocol_line() -> None:
    assert _extract_usage('answer\nFAKEY-USAGE: {"input_tokens": 7}\n') == (
        "answer\n",
        {"input_tokens": 7},
    )
    malformed = "answer\nFAKEY-USAGE: not-json\n"
    assert _extract_usage(malformed) == (malformed, None)
    embedded = 'FAKEY-USAGE: {"input_tokens": 7}\nanswer\n'
    assert _extract_usage(embedded) == (embedded, None)


def test_provider_invokes_real_binary_over_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("FAKEY_STATE_DIR", str(state_dir))
    monkeypatch.setenv("FAKEY_REPLY", "provider success")

    result = FakeyProvider().invoke(
        "prompt over stdin", model_tier="large", suppress_output=True
    )

    assert result.content == "provider success"
    assert result.usage is None
    record = _records(state_dir)[0]
    assert record["prompt"] == "prompt over stdin"
    assert record["model"] == "fakey-large"


@pytest.mark.parametrize(
    ("scenario", "marker"),
    [("@flaky", "FAKEY-RETRYABLE"), ("@crash", "FAKEY-FAIL")],
)
def test_provider_surfaces_real_cli_failure_markers(
    scenario: str,
    marker: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKEY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FAKEY_SCENARIO", scenario)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        FakeyProvider().invoke("fail", model_tier="large", suppress_output=True)

    assert exc_info.value.returncode != 0
    assert marker in exc_info.value.stderr


def test_provider_parses_usage_tail_and_writes_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    scenario = _write_scenario(
        tmp_path / "usage.yml",
        "reply: measured\nusage: {input_tokens: 7, output_tokens: 3}\n",
    )
    monkeypatch.setenv("FAKEY_SCENARIO", str(scenario))
    monkeypatch.setenv("FAKEY_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    result = FakeyProvider().invoke("measure", model_tier="small", suppress_output=True)

    assert result.content == "measured"
    assert result.usage == {"input_tokens": 7, "output_tokens": 3}
    assert json.loads((artifacts / "usage.json").read_text()) == result.usage


def test_provider_passes_full_effort_map_and_extra_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    monkeypatch.setenv("FAKEY_STATE_DIR", str(state_dir))
    monkeypatch.setenv("SASE_FAKEY_SMALL_ARGS", "--provider-extra value")

    FakeyProvider().invoke(
        "effort",
        model_tier="small",
        suppress_output=True,
        options=LLMInvocationOptions(reasoning_effort="max", explicit=True),
    )

    record = _records(state_dir)[0]
    assert record["effort"] == "max"
    assert record["extra_args"] == ["--provider-extra", "value"]
    assert record["model"] == "fakey-small"


def test_provider_honors_sase_fakey_path_with_real_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = shutil.which("fakey") or str(Path(sys.executable).with_name("fakey"))
    alternate = tmp_path / "alternate-fakey"
    alternate.symlink_to(Path(installed).resolve())
    monkeypatch.setenv("SASE_FAKEY_PATH", str(alternate))
    monkeypatch.setenv("FAKEY_STATE_DIR", str(tmp_path / "state"))

    result = FakeyProvider().invoke(
        "path override", model_tier="large", suppress_output=True
    )

    assert result.content == "Fakey completed successfully."


def test_provider_interrupt_restarts_with_accumulated_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "state"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    started = tmp_path / "started"
    release = tmp_path / "never-release"
    scenario = _write_scenario(
        tmp_path / "interrupt.yml",
        "attempts:\n"
        "  - steps:\n"
        f"      - signal: {started}\n"
        f"      - wait_for: {{path: {release}, timeout: 10}}\n"
        "    succeed: {reply: interrupted attempt}\n"
        "  - succeed: {reply: resumed successfully}\n",
    )
    monkeypatch.setenv("FAKEY_SCENARIO", str(scenario))
    monkeypatch.setenv("FAKEY_STATE_DIR", str(state_dir))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    def request_interrupt() -> None:
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        (artifacts / "interrupt_request.json").write_text(
            json.dumps({"message": "also test interrupts"}), encoding="utf-8"
        )

    helper = threading.Thread(target=request_interrupt)
    helper.start()
    try:
        result = FakeyProvider().invoke(
            "original task", model_tier="large", suppress_output=True
        )
    finally:
        helper.join(timeout=5)

    assert not helper.is_alive()
    assert result.content == "resumed successfully"
    records = _records(state_dir)
    assert len(records) == 2
    retry_prompt = str(records[1]["prompt"])
    assert "original task" in retry_prompt
    assert "--- User Message ---\nalso test interrupts" in retry_prompt


def test_registry_metadata_and_autodetect_floor() -> None:
    # Registry metadata is process-cached; clear both documented caches before
    # asserting newly installed entry-point data.
    _build_llm_pm.cache_clear()
    _llm_metadata_payload.cache_clear()

    payload = get_llm_metadata_payload()
    candidates = payload["autodetect_candidates"]
    fakey = next(item for item in candidates if item["provider"] == "fakey")

    assert model_to_provider_map()["fakey-large"] == "fakey"
    assert model_to_provider_map()["fakey-small"] == "fakey"
    assert provider_short_name_map()["fakey"] == "fky"
    assert model_short_alias_map()["fakey-large"] == "fakeyl"
    assert provider_cli_status_color_map()["fakey"] == "#FF5FAF"
    assert resolve_model_provider("fakey/fakey-small") == ("fakey", "fakey-small")
    assert fakey == {"priority": 1000, "provider": "fakey", "cli_name": "fakey"}
    assert candidates[-1] == fakey
    assert all(item["priority"] < 1000 for item in candidates[:-1])
    assert provider_emoji_badge("fakey") == "🧪"
    assert setup_hint("fakey") == {
        "tool": "Fakey",
        "install": "bundled with SASE — nothing to install",
        "auth": "no authentication required",
    }


def test_fakey_opts_out_of_provider_skill_deployment() -> None:
    assert FakeyProvider().llm_skill_deploy_subpath() is None
    assert "fakey" not in get_skill_target_providers(True)


def test_fakey_retry_defaults_and_user_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_llm_pm.cache_clear()
    _llm_metadata_payload.cache_clear()
    monkeypatch.setattr(
        "sase.llm_provider.retry_config.load_merged_config",
        lambda: {
            "llm_provider": {
                "retry": {
                    "fakey": {
                        "max_retries": 1,
                        "error_patterns": ["CUSTOM-FAKEY"],
                        "wait_times": [2],
                    }
                }
            }
        },
    )

    config = get_retry_config("fakey")

    assert config is not None
    assert config.max_retries == 1
    assert config.error_patterns == ["FAKEY-RETRYABLE", "CUSTOM-FAKEY"]
    assert config.wait_times == [2]
    assert config.preserve_workspace is True
    assert config.continuation_prompt is not None


def test_fakey_retry_markers_do_not_collide_with_real_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build_llm_pm.cache_clear()
    _llm_metadata_payload.cache_clear()
    defaults = _built_in_defaults()
    fakey_config = defaults["fakey"]
    real_configs = {
        provider: config for provider, config in defaults.items() if provider != "fakey"
    }
    retryable_marker = "FAKEY-RETRYABLE: simulated failure"
    non_retryable_marker = "FAKEY-FAIL: simulated failure"

    for config in real_configs.values():
        assert not is_retryable_error(retryable_marker, config)
        assert not is_retryable_error(non_retryable_marker, config)

    assert is_retryable_error(retryable_marker, fakey_config)
    assert not is_retryable_error(non_retryable_marker, fakey_config)
    for config in real_configs.values():
        for pattern in config.error_patterns:
            assert not is_retryable_error(pattern, fakey_config)

    monkeypatch.setattr("sase.llm_provider.retry_config.load_merged_config", lambda: {})
    matched_config = find_retry_config_for_error(retryable_marker)

    assert matched_config is not None
    assert "FAKEY-RETRYABLE" in matched_config.error_patterns
