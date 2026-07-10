"""Scenario loading, layering, and validation for the ``fakey`` CLI."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_REPLY = "Fakey completed successfully."
DEFAULT_BARRIER_TIMEOUT = 30.0

_PROMPT_BLOCK_RE = re.compile(
    r"```fakey[ \t]*\r?\n(?P<body>.*?)\r?\n```", re.IGNORECASE | re.DOTALL
)
_ROOT_KEYS = {
    "attempts",
    "barrier_timeout",
    "delay",
    "reply",
    "steps",
    "stream",
    "usage",
    "version",
}
_ATTEMPT_KEYS = {"delay", "fail", "steps", "stream", "succeed", "usage"}
_FAIL_KEYS = {"channel", "exit_code", "message", "retryable"}
_SUCCEED_KEYS = {"reply"}
_STREAM_KEYS = {"chunk_delay"}
_USAGE_KEYS = {"input_tokens", "output_tokens"}


class ScenarioError(ValueError):
    """Raised when a fakey scenario cannot be loaded or validated."""


@dataclass(frozen=True)
class ResolvedScenario:
    """A validated scenario and the persistence context associated with it."""

    data: dict[str, Any]
    source: str
    state_dir: Path
    state_key: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _load_yaml(text: str, source: str) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0]
        raise ScenarioError(f"invalid YAML in {source}: {detail}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ScenarioError(f"{source} must contain a YAML mapping at the top level")
    return loaded


def bundled_scenarios() -> dict[str, Path]:
    """Return bundled scenario names mapped to their package paths."""

    directory = Path(str(files("sase.fakey").joinpath("scenarios")))
    return {path.stem: path for path in sorted(directory.glob("*.yml"))}


def _load_selector(selector: str) -> tuple[dict[str, Any], str, Path | None]:
    if selector.startswith("@"):
        name = selector[1:]
        scenarios = bundled_scenarios()
        if name not in scenarios:
            choices = ", ".join(f"@{item}" for item in scenarios)
            raise ScenarioError(
                f"unknown bundled scenario {selector!r}; available scenarios: {choices}"
            )
        path = scenarios[name]
        return _load_yaml(path.read_text(), selector), selector, None

    path = Path(selector).expanduser()
    try:
        text = path.read_text()
    except OSError as exc:
        raise ScenarioError(
            f"cannot read scenario file {path}: {exc.strerror}"
        ) from exc
    resolved = path.resolve()
    return _load_yaml(text, str(resolved)), str(resolved), resolved


def _number(value: Any, location: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioError(f"{location} must be a number")
    result = float(value)
    if result < minimum:
        raise ScenarioError(f"{location} must be at least {minimum:g}")
    return result


def _integer(value: Any, location: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioError(f"{location} must be an integer")
    if value < minimum:
        raise ScenarioError(f"{location} must be at least {minimum}")
    return value


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{location} must be a mapping")
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ScenarioError(f"unknown {location} field(s): {names}")


def _validate_steps(value: Any, location: str) -> None:
    if not isinstance(value, list):
        raise ScenarioError(f"{location} must be a list")
    for index, raw_step in enumerate(value, 1):
        step = _mapping(raw_step, f"{location}[{index}]")
        if len(step) != 1:
            raise ScenarioError(
                f"{location}[{index}] must contain exactly one of signal, sleep, wait_for"
            )
        action, action_value = next(iter(step.items()))
        if action == "sleep":
            _number(action_value, f"{location}[{index}].sleep")
        elif action == "signal":
            if not isinstance(action_value, str) or not action_value:
                raise ScenarioError(f"{location}[{index}].signal must be a path")
        elif action == "wait_for":
            if isinstance(action_value, str):
                if not action_value:
                    raise ScenarioError(f"{location}[{index}].wait_for must be a path")
            elif isinstance(action_value, dict):
                _reject_unknown(
                    action_value, {"path", "timeout"}, f"{location}[{index}].wait_for"
                )
                if (
                    not isinstance(action_value.get("path"), str)
                    or not action_value["path"]
                ):
                    raise ScenarioError(
                        f"{location}[{index}].wait_for.path must be a path"
                    )
                if "timeout" in action_value:
                    _number(
                        action_value["timeout"],
                        f"{location}[{index}].wait_for.timeout",
                        minimum=0.001,
                    )
            else:
                raise ScenarioError(
                    f"{location}[{index}].wait_for must be a path or mapping"
                )
        else:
            raise ScenarioError(
                f"unknown step {action!r} at {location}[{index}]; "
                "expected signal, sleep, or wait_for"
            )


def _validate_stream(value: Any, location: str) -> None:
    stream = _mapping(value, location)
    _reject_unknown(stream, _STREAM_KEYS, location)
    if "chunk_delay" in stream:
        _number(stream["chunk_delay"], f"{location}.chunk_delay")


def _validate_usage(value: Any, location: str) -> None:
    usage = _mapping(value, location)
    _reject_unknown(usage, _USAGE_KEYS, location)
    for key in _USAGE_KEYS:
        if key in usage:
            _integer(usage[key], f"{location}.{key}")


def _validate_attempt(value: Any, location: str) -> None:
    attempt = _mapping(value, location)
    _reject_unknown(attempt, _ATTEMPT_KEYS, location)
    if "fail" in attempt and "succeed" in attempt:
        raise ScenarioError(f"{location} cannot contain both fail and succeed")
    if "fail" in attempt:
        failure = _mapping(attempt["fail"], f"{location}.fail")
        _reject_unknown(failure, _FAIL_KEYS, f"{location}.fail")
        if "message" in failure and not isinstance(failure["message"], str):
            raise ScenarioError(f"{location}.fail.message must be a string")
        if "retryable" in failure and not isinstance(failure["retryable"], bool):
            raise ScenarioError(f"{location}.fail.retryable must be true or false")
        if "exit_code" in failure:
            _integer(failure["exit_code"], f"{location}.fail.exit_code", minimum=1)
        if failure.get("channel", "stderr") not in {"stdout", "stderr"}:
            raise ScenarioError(f"{location}.fail.channel must be stdout or stderr")
    if "succeed" in attempt:
        succeed = attempt["succeed"]
        if succeed not in (None, True):
            success = _mapping(succeed, f"{location}.succeed")
            _reject_unknown(success, _SUCCEED_KEYS, f"{location}.succeed")
            if "reply" in success and not isinstance(success["reply"], str):
                raise ScenarioError(f"{location}.succeed.reply must be a string")
    if "delay" in attempt:
        _number(attempt["delay"], f"{location}.delay")
    if "steps" in attempt:
        _validate_steps(attempt["steps"], f"{location}.steps")
    if "stream" in attempt:
        _validate_stream(attempt["stream"], f"{location}.stream")
    if "usage" in attempt:
        _validate_usage(attempt["usage"], f"{location}.usage")


def _validate_scenario(data: Mapping[str, Any], source: str = "scenario") -> None:
    """Validate a resolved scenario, raising an actionable ``ScenarioError``."""

    _reject_unknown(data, _ROOT_KEYS, source)
    if data.get("version", 1) != 1:
        raise ScenarioError(f"{source}.version must be 1")
    if "reply" in data and not isinstance(data["reply"], str):
        raise ScenarioError(f"{source}.reply must be a string")
    if "delay" in data:
        _number(data["delay"], f"{source}.delay")
    if "barrier_timeout" in data:
        _number(data["barrier_timeout"], f"{source}.barrier_timeout", minimum=0.001)
    if "steps" in data:
        _validate_steps(data["steps"], f"{source}.steps")
    if "stream" in data:
        _validate_stream(data["stream"], f"{source}.stream")
    if "usage" in data:
        _validate_usage(data["usage"], f"{source}.usage")
    if "attempts" in data:
        attempts = data["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise ScenarioError(f"{source}.attempts must be a non-empty list")
        for index, attempt in enumerate(attempts, 1):
            _validate_attempt(attempt, f"{source}.attempts[{index}]")


def _env_layer(env: Mapping[str, str]) -> dict[str, Any]:
    layer: dict[str, Any] = {}
    if "FAKEY_REPLY" in env:
        layer["reply"] = env["FAKEY_REPLY"]
    if "FAKEY_DELAY" in env:
        try:
            layer["delay"] = float(env["FAKEY_DELAY"])
        except ValueError as exc:
            raise ScenarioError("FAKEY_DELAY must be a non-negative number") from exc

    fail_message = env.get("FAKEY_FAIL_MESSAGE")
    exit_text = env.get("FAKEY_EXIT_CODE")
    fail_times_text = env.get("FAKEY_FAIL_TIMES")
    if fail_message is not None or exit_text is not None or fail_times_text is not None:
        try:
            exit_code = int(exit_text) if exit_text is not None else 1
        except ValueError as exc:
            raise ScenarioError("FAKEY_EXIT_CODE must be a positive integer") from exc
        if exit_code < 1:
            raise ScenarioError("FAKEY_EXIT_CODE must be a positive integer")
        failure = {
            "fail": {
                "channel": "stderr",
                "exit_code": exit_code,
                "message": fail_message or "simulated failure",
                "retryable": True,
            }
        }
        if fail_times_text is None:
            layer["attempts"] = [failure]
        else:
            try:
                fail_times = int(fail_times_text)
            except ValueError as exc:
                raise ScenarioError(
                    "FAKEY_FAIL_TIMES must be a non-negative integer"
                ) from exc
            if fail_times < 0:
                raise ScenarioError("FAKEY_FAIL_TIMES must be a non-negative integer")
            layer["attempts"] = [deepcopy(failure) for _ in range(fail_times)] + [
                {"succeed": True}
            ]
    return layer


def _state_dir(env: Mapping[str, str], scenario_path: Path | None, source: str) -> Path:
    explicit = env.get("FAKEY_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if scenario_path is not None:
        return scenario_path.parent
    artifacts = env.get("SASE_ARTIFACTS_DIR")
    if artifacts:
        return Path(artifacts).expanduser().resolve()
    return (
        Path(tempfile.gettempdir())
        / f"fakey-{os.getuid()}"
        / _hash(f"{Path.cwd()}:{source}")
    )


def resolve_scenario(
    prompt: str,
    *,
    selector: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedScenario:
    """Resolve the layered scenario for one CLI invocation."""

    environ = os.environ if env is None else env
    data: dict[str, Any] = {
        "barrier_timeout": DEFAULT_BARRIER_TIMEOUT,
        "delay": 0.0,
        "reply": DEFAULT_REPLY,
        "version": 1,
    }
    data = _deep_merge(data, _env_layer(environ))

    scenario_path: Path | None = None
    selected = selector or environ.get("FAKEY_SCENARIO")
    source = "built-in default"
    if selected:
        selected_data, source, scenario_path = _load_selector(selected)
        data = _deep_merge(data, selected_data)

    blocks = list(_PROMPT_BLOCK_RE.finditer(prompt))
    if len(blocks) > 1:
        raise ScenarioError("prompt contains more than one ```fakey scenario block")
    if blocks:
        body = blocks[0].group("body")
        data = _deep_merge(data, _load_yaml(body, "prompt fakey block"))
        source = f"prompt:{_hash(body)}"
        scenario_path = None

    _validate_scenario(data, source)
    return ResolvedScenario(
        data=data,
        source=source,
        state_dir=_state_dir(environ, scenario_path, source),
        state_key=_hash(source),
    )


def select_attempt(data: Mapping[str, Any], attempt_index: int) -> dict[str, Any]:
    """Overlay the selected attempt on the scenario's common behavior."""

    common = {key: deepcopy(value) for key, value in data.items() if key != "attempts"}
    attempts = data.get("attempts")
    if not attempts:
        return common
    selected = attempts[min(attempt_index, len(attempts) - 1)]
    result = _deep_merge(common, selected)
    success = result.pop("succeed", None)
    if isinstance(success, Mapping) and "reply" in success:
        result["reply"] = success["reply"]
    return result
