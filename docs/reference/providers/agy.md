---
title: Antigravity provider
description:
  Antigravity CLI command construction, model mapping, and provider-specific behavior.
---

# Antigravity provider

This page describes how SASE integrates Antigravity CLI for agent invocations.

## Antigravity (`agy`) Integration

The `AgyProvider` invokes Google's Antigravity CLI (`agy`), the replacement for the
retired consumer Gemini CLI. It is a plain-stdout provider: the current Antigravity CLI
does not document a machine-readable JSON/stream output mode, so SASE streams plain
stdout instead of parsing a structured event stream.

### Command Construction {#command-construction-1}

```
agy --print-timeout <duration> --model <model> --dangerously-skip-permissions --add-dir <workspace> --print <prompt>
```

The prompt is passed as the value of `--print` (not on stdin) as a single argv element,
so prompts containing quotes, newlines, or shell metacharacters are never
shell-interpolated. `--print-timeout` defaults to `24h` (Antigravity's own `5m` default
is too short for long agentic runs) and is a Go duration string.

SASE pins Antigravity to the agent workspace in two ways: it launches the subprocess
with `cwd=<workspace>` and passes `--add-dir <workspace>` to the CLI. The workspace is
resolved from `SASE_ACTIVE_PROJECT_DIR`, then provider project and workspace env vars,
and finally the current working directory.

Because the current Antigravity CLI does not document a stable stdin or prompt-file
contract for print mode, SASE cannot fall back to streaming the prompt when that single
argv element becomes too large for the OS. `AgyProvider` therefore rejects prompts above
a conservative 120 KiB UTF-8 guard before spawning `agy`, with an error that names the
upstream argv transport limitation and asks the user to reduce the prompt or use a
stdin-capable provider.

Before invoking `agy --print`, SASE wraps the user prompt with a compact print-mode
directive. It tells the model that tool approval has already been granted by
`--dangerously-skip-permissions`, commands must run synchronously, background tasks
should not be used because print mode has no event loop for later notifications, and the
final answer must be written directly to stdout.

### Print-Mode No-Progress Recovery

Antigravity's `run_command` tool can dispatch long-running commands as background tasks.
In an interactive Antigravity session, the UI can deliver the later completion
notification and the model can continue. In `agy --print`, SASE starts a single
non-interactive process and reads stdout; there is no follow-up event loop. Some models
therefore end the print turn with prose such as "I will wait to be notified" or "please
approve the command" even though the subprocess exits `0`.

`AgyProvider` treats those replies as no-progress, not success. When the supported
trajectory extractor is available, SASE first checks the structural diff: zero tool-use
steps or a final pending/backgrounded `run_command` step triggers recovery. When
trajectory data is unavailable, a conservative text heuristic catches
planning-only/waiting replies. SASE then restarts `agy --print` with accumulated context
and a provider-local continuation nudge that asks the model to run tools synchronously
and output the final answer. If the reply still makes no progress after the bounded
continuation budget, `invoke()` raises `LLMInvocationError` so the run fails loudly
instead of writing a false-success answer.

### Model Mapping {#model-mapping-1}

`agy` stable model slugs are used verbatim, matching `agy models` output. The tier
defaults are:

<!-- BEGIN GENERATED: model-tiers-agy -->

| Tier    | Model                   |
| ------- | ----------------------- |
| `large` | `gemini-3.7-flash-high` |
| `small` | `gemini-3.7-flash-low`  |

<!-- END GENERATED: model-tiers-agy -->

All other `agy models` slugs remain reachable through the model picker, configured
aliases, and provider/model directives such as `%m:agy/gemini-3.6-flash-high`. Whether a
shipped size alias currently routes to an Antigravity member is visible in the generated
[shipped size-alias defaults](models.md#implicit-role-aliases).

Gemini 4 Argon is catalogued as `gemini-4-argon-high`, `gemini-4-argon-medium`, and
`gemini-4-argon-low`; effort is chosen by the slug variant. Antigravity serves it only
to Google AI Ultra and eligible Gemini Enterprise accounts, and `agy` fails the run when
the signed-in account lacks access. For that reason the agy tier defaults stay on Gemini
Flash, and no shipped size alias routes to Argon.

### Environment Variables {#environment-variables-1}

| Variable                                 | Description                                                        |
| ---------------------------------------- | ------------------------------------------------------------------ |
| `SASE_AGY_PATH`                          | Path to the Antigravity CLI binary (default: `"agy"`).             |
| `SASE_AGY_PRINT_TIMEOUT`                 | Override the `agy --print-timeout` Go duration (default: `"24h"`). |
| `SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS` | Override the no-progress continuation cap (default: `2`).          |
| `SASE_AGY_LARGE_ARGS`                    | Extra args for the `large` tier (after `SASE_LLM_LARGE_ARGS`).     |
| `SASE_AGY_SMALL_ARGS`                    | Extra args for the `small` tier (after `SASE_LLM_SMALL_ARGS`).     |

### Skill Deployment

`sase skill init -p agy` writes generated SASE skills to
`~/.gemini/antigravity-cli/skills/`, the documented Antigravity global skill path. The
leading `.gemini` here is an Antigravity-owned path, not a Gemini CLI path.

### Structured Artifacts Parity Gap

The Antigravity CLI exposes no stable machine-readable stdout contract: there is no
documented `--output-format stream-json` or JSON event mode. Because SASE will not
scrape Antigravity's human TUI rendering to synthesize artifacts, the `agy` provider
preserves these invariants:

- **Tool-call timeline** — SASE never invents rows from stdout display glyphs or prose.
  For explicitly supported Antigravity versions, a guarded best-effort extractor may
  decode new rows from Antigravity's local trajectory DB and append
  `source="trajectory"` records to `tool_calls.jsonl`; otherwise sase's TUI
  [Agents Tab LLM Calls Panel](../tui/agents-deck-panels.md#agents-tab-llm-calls-panel)
  shows nothing for `agy` runs.
- **Usage accounting** — `InvokeResult.usage` is `None` and no `usage.json` is written;
  `agy` print mode exposes no stable token counters.
- **Thinking extraction** — no thinking artifact is produced.

The plain-stdout path still writes `live_reply.md` (and `live_reply_timestamps.jsonl`)
like every other provider, so the final reply, chat history, and resume support work
normally. These structured features are fast-follow work gated on a future Antigravity
machine-readable output/log/conversation contract.

### Timer Display {#timer-display-1}

While waiting for a response, a `Waiting for Antigravity` spinner is shown (unless
`suppress_output` is `True`).

## Related

- [Providers and models](index.md) — the provider integration overview.
- [Models and aliases](models.md) — model names and tier defaults.
