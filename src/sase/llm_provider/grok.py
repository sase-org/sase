"""xAI Grok Build (`grok`) LLM provider implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from sase.feature_flags import FeatureFlag, current_flags
from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import (
    ProviderTurnState,
    start_completion_watchdog,
    start_interrupt_monitor,
    stream_and_parse_messages_json_output,
)
from ._subprocess_artifacts import open_live_reply_file
from ._subprocess_reap import teardown_stall_for
from ._tool_calls import append_grok_tool_call_event
from .base import LLMProvider
from .instruction_delivery import (
    CHANNEL_GROK_ROOT,
    current_instruction_delivery,
    legacy_instruction_delivery,
)
from .model_manifest import provider_model_names, provider_tier_model
from .types import (
    InvokeResult,
    LLMInvocationError,
    LLMInvocationOptions,
    ModelTier,
)

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig

# (Model catalog and tier defaults live in the bundled ``models.yml``
# manifest; see ``model_manifest.py``.)

_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--effort", level] for level in ("low", "medium", "high", "xhigh")
}

_GROK_PATH_ENV = "SASE_GROK_PATH"
_GROK_CLI_NAME = "grok"


def _resolve_grok_executable() -> str:
    """Return the Grok Build executable SASE should launch."""
    explicit_path = os.environ.get(_GROK_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which(_GROK_CLI_NAME)
    if path_result:
        return path_result

    return _GROK_CLI_NAME


def _grok_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Grok diagnostic."""
    return FileNotFoundError(
        "Unable to launch Grok Build executable "
        f"{command!r}. Set SASE_GROK_PATH to the Grok Build binary, ensure "
        "'grok' is discoverable on PATH, or run `sase agent-cli install grok`. "
        "If PATH resolves to grok-dev or Homebrew's deprecated regex tool, "
        "point SASE_GROK_PATH at the @xai-official/grok binary."
    )


_GROK_SINGLE_TURN_DIRECTIVE = (
    "SASE single-turn instructions for Grok: this session is exactly one turn, "
    "and nothing can wake you after you end it. Notifications that arrive "
    '"in a new turn after your turn ends" — from background commands, '
    "background subagents, `monitor`, or `scheduler_create` — never reach "
    "you, and anything still running when you give your final response is "
    "lost. Run commands in the foreground: set `run_terminal_command`'s "
    "`block_until_ms` longer than the command takes, because the 30-second "
    "default moves slower commands to the background. If a command returns a "
    "task id instead of an exit code, it is still running, not done: call "
    "`get_command_or_subagent_output` with that task id and a `timeout_ms` "
    "until it reports an exit code. Call `spawn_subagent` with `background: "
    "false`, or wait on each `subagent_id` the same way. Handoff commands "
    "such as `sase monitor start`, `sase plan propose`, `sase pipe`, and "
    "`sase questions` can take up to a minute before they hand off; wait for "
    "the handoff command itself to exit. Never end your turn to wait."
)
# Linux rejects a single argv element above 128 KiB. Keep SASE's guard below
# that so `--rules` fails with an actionable error before exec.
_GROK_RULES_ARGV_BYTE_LIMIT = 120 * 1024


def _grok_rules_text(cwd: Path | str | None = None) -> str:
    """Return the `--rules` payload for a Grok run from *cwd*.

    In SASE-managed projects this is the single-turn directive, a blank line,
    and the project root's ``AGENTS.md`` text exactly once. Elsewhere it is
    the directive alone. The file is read on every call. The home layer and
    ``CLAUDE.md`` are never included.
    """
    from sase.content_layout import discover_project_root
    from sase.feature_flags.managed import project_is_sase_managed

    start = Path(cwd).expanduser() if cwd is not None else None
    agents_path: Path | None = None
    if project_is_sase_managed(start):
        root = discover_project_root(start)
        if root is not None:
            candidate = root / "AGENTS.md"
            if candidate.is_file():
                agents_path = candidate
    if agents_path is None:
        return _GROK_SINGLE_TURN_DIRECTIVE
    agents_text = agents_path.read_text(encoding="utf-8")
    rules = f"{_GROK_SINGLE_TURN_DIRECTIVE}\n\n{agents_text}"
    size = len(rules.encode("utf-8"))
    if size > _GROK_RULES_ARGV_BYTE_LIMIT:
        raise LLMInvocationError(
            "Grok (`grok`) --rules payload is too large for SASE's argv "
            f"transport: {size} UTF-8 bytes exceeds the "
            f"{_GROK_RULES_ARGV_BYTE_LIMIT}-byte guard. The project "
            f"instructions file {agents_path} is too large to pass as one "
            "argv element (Linux rejects a single argv element above 128 "
            "KiB). Shrink that file."
        )
    return rules


def _grok_home() -> Path:
    """Return Grok's home directory: ``$GROK_HOME`` if set, else ``~/.grok``."""
    raw = os.environ.get("GROK_HOME", "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".grok"


def _resolve_grok_session_dir(cwd: str, session_id: str) -> Path | None:
    """Return Grok's session directory for *cwd* and *session_id*, if present.

    The CLI stores sessions at
    ``<grok_home>/sessions/<quote(cwd, safe="")>/<session_id>/``. When that
    exact path is missing, fall back to globbing
    ``<grok_home>/sessions/*/<session_id>`` because session ids are fresh
    UUIDs.
    """
    home = _grok_home()
    exact = home / "sessions" / quote(cwd, safe="") / session_id
    if exact.is_dir():
        return exact
    matches = sorted(
        match for match in home.glob(f"sessions/*/{session_id}") if match.is_dir()
    )
    return matches[0] if matches else None


class _GrokTurnEndProbe:
    """Incremental ``events.jsonl`` reader for Grok's turn lifecycle."""

    def __init__(self, cwd: str, session_id: str) -> None:
        self._cwd = cwd
        self._session_id = session_id
        self._session_dir: Path | None = None
        self._offset = 0
        self._partial = b""
        self._state: ProviderTurnState | None = None

    def __call__(self) -> ProviderTurnState | None:
        try:
            return self._poll()
        except Exception:
            return None

    def _poll(self) -> ProviderTurnState | None:
        if self._session_dir is None:
            self._session_dir = _resolve_grok_session_dir(self._cwd, self._session_id)
        if self._session_dir is None:
            return None
        path = self._session_dir / "events.jsonl"
        try:
            with path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError:
            return None
        if not chunk and not self._partial:
            return self._state
        buf = self._partial + chunk
        lines = buf.split(b"\n")
        self._partial = lines[-1]
        for raw in lines[:-1]:
            self._ingest_line(raw)
        return self._state

    def _ingest_line(self, raw: bytes) -> None:
        stripped = raw.strip()
        if not stripped:
            return
        try:
            event = json.loads(stripped.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "turn_started":
            self._state = ProviderTurnState("started")
        elif event_type == "turn_ended":
            outcome = event.get("outcome")
            self._state = ProviderTurnState(
                "ended", outcome if isinstance(outcome, str) else None
            )


def _assistant_chat_text(content: object) -> str | None:
    """Return non-empty assistant text from a chat-history ``content`` field."""
    if isinstance(content, str):
        return content if content.strip() else None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    joined = "".join(parts)
    return joined if joined.strip() else None


def _final_assistant_from_chat_history(session_dir: Path) -> str | None:
    """Return the last assistant entry after the last ``tool_result`` entry."""
    path = session_dir / "chat_history.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    last_tool = -1
    last_assistant: str | None = None
    for index, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "tool_result":
            last_tool = index
            continue
        if event_type != "assistant" or index <= last_tool:
            continue
        extracted = _assistant_chat_text(event.get("content"))
        if extracted:
            last_assistant = extracted
    return last_assistant


def _append_recovered_live_reply(text: str) -> None:
    """Append recovered final-reply text to ``live_reply.md`` when present."""
    live_reply_file = open_live_reply_file()
    if live_reply_file is None:
        return
    try:
        if live_reply_file.tell() > 0:
            live_reply_file.write("\n\n")
        live_reply_file.write(text)
        live_reply_file.flush()
    except OSError:
        pass
    finally:
        live_reply_file.close()


def _recover_grok_final_reply(
    process: subprocess.Popen[str],
    content: str,
    cwd: str,
    session_id: str,
) -> str:
    """Append grok's final chat-history assistant after a turn-end reap.

    Best-effort: any read or parse failure leaves *content* unchanged.
    """
    try:
        stall = teardown_stall_for(process)
        if stall is None or stall.trigger != "provider_turn_end":
            return content
        session_dir = _resolve_grok_session_dir(cwd, session_id)
        if session_dir is None:
            return content
        recovered = _final_assistant_from_chat_history(session_dir)
        if recovered is None:
            return content
        if content.endswith(recovered) or content.rstrip().endswith(recovered.rstrip()):
            return content
        _append_recovered_live_reply(recovered)
        if not content:
            return recovered
        if content.endswith("\n\n"):
            return content + recovered
        if content.endswith("\n"):
            return content + "\n" + recovered
        return content + "\n\n" + recovered
    except Exception:
        return content


def _log_interrupt(message: str | None, cycle: int) -> None:
    """Append an interrupt entry to the artifacts directory."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "interrupt_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(
                {"message": message, "timestamp": time.time(), "cycle": cycle},
                f,
            )
            f.write("\n")
    except OSError:
        pass


class GrokProvider(LLMProvider):
    """LLM provider that invokes xAI's Grok Build CLI."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Grok model name for the given tier."""
        return provider_tier_model("grok", model_tier)

    @hookimpl
    def llm_provider_name(self) -> str:
        return "grok"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "grk"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return list(provider_model_names("grok"))

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Grok",
            "provider_tool_name": "Grok Build",
            "provider_native_ask_tool": "ask_user_question",
        }

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#00C8D7"

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return _GROK_CLI_NAME

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["~/.grok/auth.json"],
            "api_key_env_vars": ["XAI_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        # @xai-official/grok is an npm trampoline: `npm install -g` places a
        # shim on PATH, but the real Grok Build binary it downloads on first
        # run lives under ~/.grok/bin/, not node_modules.
        return {
            "manager": "npm",
            "package": "@xai-official/grok",
            "scope": "global",
            "display_name": "Grok Build",
            "vendor": "xAI",
            "docs_url": "https://docs.x.ai/build/overview",
            "self_update_argv": ["update"],
            "latest_version_package": "@xai-official/grok",
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        return {
            "menu_key": "g",
            "bypass_args": ["--always-approve"],
            "model_args": ["--model", "{model}"],
        }

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import (
            _RETRY_CONTINUATION_NUDGE,
            ProviderRetryConfig,
        )

        # "max_tokens_truncation" / "response truncated by max_tokens" are
        # captured live from a run that died mid-session (2026-09-04,
        # ace(run)-260904_135714, grok-4.6 xhigh, turn 55) when the CLI
        # aborted with exit code 1 and an internal-error JSON payload whose
        # error_kind was "max_tokens_truncation". Both anchors are kept: the
        # machine error_kind key and the prose message, in case a future CLI
        # build drops one but keeps the other.
        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=[
                "xAI API error",
                "xAI rate limit",
                "xAI server error",
                "xAI upstream request failed",
                "max_tokens_truncation",
                "response truncated by max_tokens",
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # Free-tier patterns verbatim from a captured live failure (epic
        # sase-n4 research); the source uses U+2019 in "You've", which
        # normalize_for_match handles. The next three patterns are the
        # paid credit/balance family, captured live 2026-08-18 from:
        #   API error (status 402 Payment Required): Grok Build usage
        #   balance exhausted
        # ("usage balance exhausted" and "status 402 payment required" are
        # both substrings of that message). The last two ("you've hit the
        # credit limit for your plan", "you hit your weekly limit") are
        # pager billing-panel strings pulled from the shipped grok binary,
        # not yet observed on stderr.
        #
        # Grok Build emits no reset instant in any limit message a full
        # literal scan of the binary can find (no "resets at/in", no
        # Retry-After on the sampling path) — see the plan's "Evidence:
        # Grok Build never reports a reset instant" section. honor_reset_hint
        # is therefore a no-op for grok and parse_reset_hint always returns
        # (None, None) here. disable_seconds below is now the last resort
        # behind the usage-window fallback (a corroborated reset read from
        # the Grok billing-usage collector): it stays load-bearing whenever
        # the collector has no fresh corroborating window (logged-out CLI,
        # API mode, or a stale snapshot).
        #
        # disable_seconds is 172800 (48h), double the global 24h default,
        # because since June 2026 paid Grok meters every product against one
        # shared weekly usage pool (docs.x.ai/grok/faq): an exhausted balance
        # is typically a multi-day condition, not a same-day reset, so 24h
        # would under-shoot it and burn a fresh agent workspace on every
        # re-probe.
        return ProviderUsageLimitConfig(
            patterns=[
                "reached your free grok build usage limit",
                "usage limit for now",
                "get supergrok for much higher limits",
                "usage balance exhausted",
                "status 402 payment required",
                "out of credits or over your spending limit",
                "you've hit the credit limit for your plan",
                "you hit your weekly limit",
                "usage limit reached",
            ],
            disable_seconds=172800,
        )

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        return {
            "probe": True,
            "passive_events": False,
            "min_probe_interval_seconds": 120,
        }

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, object] | None:
        from .usage.grok import collect_grok_usage

        return collect_grok_usage(
            context, executable=context.executable or _resolve_grok_executable()
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--effort`` args."""
        return effort_cli_args(
            options, provider_label="Grok Build", supported=_EFFORT_CLI_ARGS
        )

    def instruction_delivery(self) -> dict[str, object]:
        if not current_flags().enabled(FeatureFlag.grok_explicit_instructions):
            return legacy_instruction_delivery(reason="flag_disabled")
        return {
            "root": {
                "status": "explicit",
                "channel": CHANNEL_GROK_ROOT,
                "max_bytes": _GROK_RULES_ARGV_BYTE_LIMIT,
            },
            "subagent": {"status": "none"},
        }

    @hookimpl
    def llm_instruction_delivery(self) -> dict[str, object]:
        return self.instruction_delivery()

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
        options: LLMInvocationOptions | None,
    ) -> InvokeResult:
        return self.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
        options: LLMInvocationOptions | None = None,
    ) -> InvokeResult:
        """Invoke Grok Build with the given prompt."""
        model = (
            model_override if model_override else self.resolve_model_name(model_tier)
        )
        effort_args = self.invocation_option_args(options)

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_GROK_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_GROK_SMALL_ARGS")
            )

        current_prompt = prompt
        accumulated_response = ""
        total_usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        cycle = 0

        return self._invoke_loop(
            current_prompt=current_prompt,
            original_prompt=prompt,
            accumulated_response=accumulated_response,
            total_usage=total_usage,
            cycle=cycle,
            model=model,
            effort_args=effort_args,
            extra_args_env=extra_args_env,
            suppress_output=suppress_output,
        )

    def _invoke_loop(
        self,
        *,
        current_prompt: str,
        original_prompt: str,
        accumulated_response: str,
        total_usage: dict[str, int],
        cycle: int,
        model: str,
        effort_args: list[str],
        extra_args_env: str | None,
        suppress_output: bool,
    ) -> InvokeResult:
        while True:
            delivery = current_instruction_delivery()
            explicit_delivery = (
                delivery
                if delivery is not None and delivery.root.plan.status == "explicit"
                else None
            )
            rules_text: str
            if explicit_delivery is not None:
                explicit_rules = explicit_delivery.root.text
                if not explicit_rules:
                    explicit_delivery.report_fallback(
                        "root", "delivery_failed", "no delivered root text"
                    )
                    explicit_delivery = None
                else:
                    rules_size = len(explicit_rules.encode("utf-8"))
                    if rules_size > _GROK_RULES_ARGV_BYTE_LIMIT:
                        explicit_delivery.report_fallback(
                            "root",
                            "oversize",
                            f"delivered rules are {rules_size} bytes; limit is "
                            f"{_GROK_RULES_ARGV_BYTE_LIMIT}",
                        )
                        explicit_delivery = None
                    else:
                        rules_text = explicit_rules
            if explicit_delivery is None:
                rules_text = _grok_rules_text(os.getcwd())

            session_id = str(uuid.uuid4())
            if explicit_delivery is not None and delivery is not None:
                delivery.record_session(session_id)
            command_args = [
                _resolve_grok_executable(),
                "--prompt-file",
                "/dev/stdin",
                "--output-format",
                "streaming-messages-json",
                "--permission-mode",
                "bypassPermissions",
                "--model",
                model,
                "--cwd",
                os.getcwd(),
                "--session-id",
                session_id,
                "--no-plan",
                "--no-ask-user",
                "--no-auto-update",
                "--no-leader",
                *effort_args,
            ]

            command_args.extend(["--rules", rules_text])

            run_kwargs = (
                {"env_overrides": {"GROK_MEMORY": "0"}}
                if explicit_delivery is not None
                else {}
            )

            if extra_args_env:
                for arg in extra_args_env.split():
                    command_args.append(arg)

            if not suppress_output:
                with provider_timer("Waiting for Grok"):
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args,
                        current_prompt,
                        suppress_output,
                        session_id=session_id,
                        cwd=os.getcwd(),
                        **run_kwargs,
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    command_args,
                    current_prompt,
                    suppress_output,
                    session_id=session_id,
                    cwd=os.getcwd(),
                    **run_kwargs,
                )

            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + content.strip()
                ).strip()
                current_prompt = (
                    f"{original_prompt}\n\n"
                    f"--- Work So Far ---\n{accumulated_response}\n\n"
                    f"--- User Message ---\n{user_msg}\n\n"
                    "Continue working, incorporating the user's message above."
                )
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    command_args,
                    output=content,
                    stderr=stderr_content,
                )

            accumulated_response = (
                accumulated_response + "\n\n" + content.strip()
            ).strip()
            return InvokeResult(content=accumulated_response, usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
        *,
        env_overrides: dict[str, str] | None = None,
        session_id: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Grok Build subprocess and parse its Messages JSON stream."""
        try:
            if env_overrides is None:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                env = os.environ.copy()
                env.update(env_overrides)
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
        except FileNotFoundError as exc:
            raise _grok_executable_not_found_error(args[0]) from exc

        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )
        session_cwd = os.getcwd() if cwd is None else cwd
        probe = _GrokTurnEndProbe(session_cwd, session_id) if session_id else None
        start_completion_watchdog(process, runtime="grok", turn_end_probe=probe)

        content, stderr_content, return_code, usage = (
            stream_and_parse_messages_json_output(
                process,
                suppress_output=suppress_output,
                runtime="grok",
                tool_call_writer=append_grok_tool_call_event,
                thinking_sink=True,
            )
        )
        if session_id:
            content = _recover_grok_final_reply(
                process, content, session_cwd, session_id
            )
        return content, stderr_content, return_code, usage
