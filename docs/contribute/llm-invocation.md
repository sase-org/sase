---
title: LLM invocation internals
description:
  Internal provider architecture, prompt processing, subprocess handling, and invocation
  lifecycle.
---

# LLM invocation internals

This page documents the shared implementation behind provider integrations and
invocations.

## Source Layout

| File                                                       | Purpose                                                                                                                          |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/llm_provider/__init__.py`                        | Public API exports                                                                                                               |
| `src/sase/llm_provider/base.py`                            | `LLMProvider` abstract base class                                                                                                |
| `src/sase/llm_provider/_hookspec.py`                       | Pluggy hook specifications (`LLMHookSpec`)                                                                                       |
| `src/sase/llm_provider/_plugin_manager.py`                 | Plugin manager wrapping pluggy (`LLMPluginManager`)                                                                              |
| `src/sase/llm_provider/claude.py`                          | Claude Code provider implementation                                                                                              |
| `src/sase/llm_provider/codex.py`                           | Codex CLI provider implementation                                                                                                |
| `src/sase/llm_provider/fakey.py`                           | Bundled deterministic testing provider                                                                                           |
| `src/sase/llm_provider/agy.py`                             | Antigravity CLI (`agy`) provider implementation                                                                                  |
| `src/sase/llm_provider/qwen.py`                            | Qwen Code provider implementation                                                                                                |
| `src/sase/llm_provider/opencode.py`                        | OpenCode provider implementation                                                                                                 |
| `src/sase/llm_provider/muse.py`                            | Meta Muse Code provider implementation                                                                                           |
| `src/sase/llm_provider/_subprocess_muse.py`                | Muse `exec --json` JSONL stream parser                                                                                           |
| `src/sase/llm_provider/_tool_call_muse.py`                 | Muse tool-call record extraction from the event stream                                                                           |
| `src/sase/llm_provider/_muse_session_usage.py`             | Muse token-usage recovery from the on-disk session log                                                                           |
| `src/sase/llm_provider/grok.py`                            | xAI Grok Build provider implementation                                                                                           |
| `src/sase/llm_provider/_subprocess_claude.py`              | Provider-neutral Anthropic-Messages stream reader shared by Claude and Grok                                                      |
| `src/sase/llm_provider/_tool_call_grok.py`                 | Grok tool-call normalization (native names → canonical display names)                                                            |
| `src/sase/llm_provider/registry.py`                        | Provider registration and lookup                                                                                                 |
| `src/sase/llm_provider/_registry_metadata.py`              | Provider metadata normalization and cache fingerprints                                                                           |
| `src/sase/llm_provider/_registry_plugins.py`               | Plugin discovery/construction via `sase_llm` entry points                                                                        |
| `src/sase/llm_provider/models.yml`                         | Single bundled source of truth for built-in model catalogs, tier defaults, and shipped size-alias targets/fallbacks/descriptions |
| `src/sase/llm_provider/model_manifest.py`                  | Lazy cached loader and strict structural validation for `models.yml`                                                             |
| `src/sase/llm_provider/model_alias_policy.py`              | Model-alias name constants and the size-alias views projected from the manifest                                                  |
| `src/sase/llm_provider/model_alias_config.py`              | Model-alias config parsing and presentation metadata                                                                             |
| `src/sase/llm_provider/model_alias_resolution.py`          | Alias/target/effort resolution façade (import/monkeypatch surface)                                                               |
| `src/sase/llm_provider/model_alias_resolution_types.py`    | Alias-resolution types, normalization, and target availability                                                                   |
| `src/sase/llm_provider/model_alias_resolution_resolve.py`  | Alias-chain walker and effort/selector provenance                                                                                |
| `src/sase/llm_provider/model_alias_resolution_selector.py` | Selector member diagnostics and selector-value validation                                                                        |
| `src/sase/llm_provider/alias_view.py`                      | sase's TUI Launch Control alias-view construction (`build_alias_views()`)                                                        |
| `src/sase/llm_provider/config.py`                          | Config file reader (`sase.yml`)                                                                                                  |
| `src/sase/llm_provider/temporary_override.py`              | Primary/worker temporary override state and resolution                                                                           |
| `src/sase/llm_provider/provider_disable.py`                | Rust-backed temporary provider-disable facade                                                                                    |
| `src/sase/llm_provider/provider_disable_peek.py`           | Lock-free display peek for active provider disables                                                                              |
| `src/sase/llm_provider/provider_priority.py`               | Rust-backed temporary provider-priority facade (import/monkeypatch surface)                                                      |
| `src/sase/llm_provider/provider_priority_types.py`         | Provider-priority wire records, decode/write envelopes, and route keys                                                           |
| `src/sase/llm_provider/provider_priority_routing.py`       | Routing-context capture and provider availability classification                                                                 |
| `src/sase/llm_provider/provider_priority_peek.py`          | Lock-free display peek for active provider priority and routing context                                                          |
| `src/sase/finalizers/controller.py`                        | Provider-neutral finalizer planning and orchestration                                                                            |
| `src/sase/finalizers/commit.py`                            | Bundled dirty-workspace commit finalizer                                                                                         |
| `src/sase/llm_provider/types.py`                           | `ModelTier`, `InvokeResult`, `LoggingContext` types                                                                              |
| `src/sase/llm_provider/_invoke.py`                         | `invoke_agent()` orchestrator                                                                                                    |
| `src/sase/llm_provider/_subprocess.py`                     | Provider stream-parser compatibility exports                                                                                     |
| `src/sase/llm_provider/_plan_utils.py`                     | Shared plan utilities                                                                                                            |
| `src/sase/llm_provider/preprocessing.py`                   | Shared prompt preprocessing pipeline                                                                                             |
| `src/sase/llm_provider/postprocessing.py`                  | Logging, chat history, audio                                                                                                     |
| `src/sase/llm_provider/retry_config.py`                    | `ProviderRetryConfig` (per-provider retry defaults)                                                                              |

## Provider Architecture

### Base Class

All providers implement the `LLMProvider` abstract base class:

```python
class LLMProvider(ABC):
    @abstractmethod
    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult: ...
```

| Parameter         | Type          | Description                                                       |
| ----------------- | ------------- | ----------------------------------------------------------------- |
| `prompt`          | `str`         | Already-preprocessed prompt text                                  |
| `model_tier`      | `ModelTier`   | `"large"` or `"small"`                                            |
| `suppress_output` | `bool`        | If `True`, suppress real-time console output                      |
| `model_override`  | `str \| None` | Concrete model name from `%model`, a temporary override, or retry |

Returns `InvokeResult(content=..., usage=...)`. Providers raise
`subprocess.CalledProcessError` for failed CLI exits or a provider-specific exception
for launch/configuration failures.

### Registry

Providers are discovered via `importlib.metadata.entry_points(group="sase_llm")`. The
built-in providers are packaged the same way as external provider plugins; their entry
points live in `pyproject.toml`:

```toml
[project.entry-points."sase_llm"]
claude = "sase.llm_provider.claude:ClaudeCodeProvider"
codex  = "sase.llm_provider.codex:CodexProvider"
fakey = "sase.llm_provider.fakey:FakeyProvider"
agy = "sase.llm_provider.agy:AgyProvider"
grok = "sase.llm_provider.grok:GrokProvider"
muse = "sase.llm_provider.muse:MuseProvider"
opencode = "sase.llm_provider.opencode:OpenCodeProvider"
qwen   = "sase.llm_provider.qwen:QwenProvider"
```

External plugin packages declare additional entries under the same group.

To get a provider instance:

```python
provider = get_provider()          # Uses default from config
provider = get_provider("claude")  # Explicit provider name
```

### Selection Logic

1. If `provider_name` is passed to `invoke_agent()`, use that.
2. If the prompt has a `%model` directive, resolve explicit `provider/model` syntax
   first, then known model names from installed plugin metadata.
3. If no explicit provider/model was supplied, use an active temporary override from
   `~/.sase/llm_override.json`.
4. Otherwise, read the `llm_provider.provider` field from `~/.config/sase/sase.yml`.
5. If no config exists (or provider is empty), auto-detect by walking registered plugins
   in ascending `llm_autodetect_priority()` order and picking the first whose
   `llm_autodetect_cli_name()` is on `PATH`. Built-in priorities: `claude=0`,
   `codex=10`, `qwen=15`, `opencode=18`, `agy=30`. External plugins slot in by declaring
   their own priority. `agy` autodetects via the `agy` CLI name in the late-fallback
   slot. A provider that declares no priority never participates in autodetection:
   `muse` and `grok` deliberately omit one, because `muse` and `grok` are both generic
   executable names and autodetect only checks `PATH` presence. Model-alias routing is
   separate: whichever shipped size aliases currently target Grok or Muse can select
   that provider whenever its executable is available (see
   [Grok Build Integration](../reference/providers/grok.md#grok-build-integration),
   [Muse Code Integration](../reference/providers/muse.md#muse-code-integration), and
   the generated
   [shipped size-alias defaults](../reference/providers/models.md#implicit-role-aliases)).

## Commit Finalization

For SASE agent runs, `invoke_agent()` resolves the host-owned `finalizers` plan before
the provider turn and runs the generic finalizer controller before success
postprocessing after the provider returns. The bundled `builtin@commit` instance checks
the active project workspace through the active VCS provider and checks configured
linked repositories as Git worktrees at their resolved `workspace_dir`. Repositories
opened through `/sase_repo` are enforced like the main workspace.

Normal turns learn the terminal action from generated agent instructions in
`sase/memory/sase.md` (inlined into `AGENTS.md`): use `/sase_final` as the last normal
action. The skill publishes context and exits early when no payload is required. If a
required declaration is missing or stale after the normal response, the host opens one
bounded recovery turn that explicitly asks the agent to use `/sase_final`. The submitted
declaration gives each dirty repository exactly one `commit` decision with a
Conventional Commit message; `commit` is the only legal repository action. When the run
has an assigned bead (`SASE_BEAD_ID`), each commit decision also carries an explicit
`bead_action`: `keep` for intermediate work, proposals, and linked or sidecar
repositories, or `close` only on the primary repository once the whole bead is complete
and verified (see [Explicit Bead Action](../commit_workflows.md#explicit-bead-action)).
Typed deferrals can name explicit paths that must not be committed, using
host-adjudicated reasons such as `foreign_work` or `protected_paths`. Accepted commit
decisions dispatch through the appropriate stitch workflow. A narrow generated SDD plan
closeout, where the only enforced change is one markdown file's frontmatter
`status: wip` becoming `status: done`, is committed directly with a `SASE_TYPE=sdd`
commit.

When an artifacts directory is available, the host writes generic artifacts such as
`final_context.json`, `final_submission.json`, `finalizer_baseline.json`, and
`finalizer_result.json`, plus per-instance files under `finalizers/<instance>/` and
stitch evidence in `commit_results.json`. If dirty work remains after the configured
attempt budget, a declaration is stale or refused, a conflict is unresolved, or a
publication/discarded-work guard fails, the invocation is converted into an
`LLMInvocationError` rather than being logged as a successful clean run.

The older provider-native commit hook scripts are no longer shipped; SASE-launched agent
sessions rely on the shared finalizer path.

## Token Usage Tracking

The LLM provider layer tracks token usage for providers that emit parseable usage
events. Claude and Qwen usage is read from their stream-json result events. OpenCode
usage is accumulated from `step_finish` token counters. Muse emits no token counts on
stdout at all, so its usage is recovered after the process exits from the
[session log SASE named](../reference/providers/muse.md#token-usage-and-model-identity)
via `--session-id`. Codex currently captures assistant text and reasoning summaries but
does not emit `usage.json`. Grok's `result.usage` uses the same four keys as Claude's,
but is best-effort: subagent turns and interrupted turns can under-count or zero out
because the `streaming-messages-json` projection drops Grok's internal "usage
incomplete" marker — see [Token Usage](../reference/providers/grok.md#token-usage).

When usage is available, input tokens, output tokens, cache-creation tokens, and
cache-read tokens are persisted as a `usage.json` artifact in the agent run directory.

### Artifact Format

```json
{
  "input_tokens": 12345,
  "output_tokens": 6789,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 3456
}
```

When telemetry is enabled, token counts are recorded as local debugging counters
(`sase_llm_input_tokens_total`, `sase_llm_output_tokens_total`,
`sase_llm_cache_read_tokens_total`). See [docs/contribute/telemetry.md](telemetry.md)
for the full telemetry reference.

Source: `src/sase/llm_provider/_subprocess.py`, `src/sase/llm_provider/types.py`

## Prompt Preprocessing Pipeline

Before any prompt reaches a provider, it passes through the shared preprocessing
pipeline defined in `preprocessing.py`. The pipeline has an early phase used for macro
expansion and directive extraction, then a late phase used for command, file, template,
and formatting work.

### Steps

| Phase | Step                       | Syntax                                     | Description                                              |
| ----- | -------------------------- | ------------------------------------------ | -------------------------------------------------------- |
| Early | Optional workflow Jinja2   | `{{ var }}`                                | Render workflow-supplied template context before macro   |
| Early | macro references           | `#name`                                    | Expand reusable prompt snippets or workflows             |
| Early | Prompt directives          | `%model`, `%m`, other `%...` directives    | Extract directives after macro expansion                 |
| Late  | Disabled/fenced protection | `%macros_enabled:false`, fenced code       | Protect regions that should not be rewritten             |
| Late  | Command substitution       | `$(cmd)`                                   | Execute shell commands and inline their output           |
| Late  | Artifact references        | `@kind:payload`                            | Expand known artifact kinds into portable semantic prose |
| Late  | File references            | `@path`                                    | Process, validate, or skip file references               |
| Late  | Top-level Jinja2           | `{{ var }}`                                | Render remaining top-level Jinja2 templates              |
| Late  | Prettier formatting        | -                                          | Format with prettier for consistent markdown             |
| Late  | Comment stripping          | `<!-- ... -->`                             | Remove HTML/markdown comments                            |
| Late  | Restore protected regions  | fenced code / disabled-region placeholders | Restore protected content after rewrites                 |

### Order Matters

The pipeline runs in strict order. Prompt directives are extracted after macro
expansion, so directives embedded in macros are honored. Before extraction, segments
disabled by a static `%if(should_run=false)` are dropped, and a kept segment loses only
its `%if(...)` line (see
[Static Conditional Segments](../reference/macros/directive-syntax.md#static-conditional-segments)).
Late-phase command substitution and reference processing run with fenced blocks
protected, so examples inside code fences are not executed or rewritten. Canonical
artifact references are expanded before ordinary file references: built-in artifact
expansions become portable semantic prose (for example
`the 202608/foobar.md file in the plans sidecar repo`) and do not inject `@path` tokens
that the ordinary file-reference pass would re-parse. Unknown `@kind:` references remain
unchanged as prose. The retired `#ref/<kind>` renderer syntax is not accepted.
Inline-code references also remain literal. Explicit custom path-bound document
providers may still emit path-shaped text; those remain excluded from the subsequent
`@path` pass.

During the same pass, SASE stages prompt references for later archive publication. File
references are recorded in the workspace-local `.sase/artifacts/prompt-artifacts.jsonl`
manifest. Home-directory `@path` references are copied to the readable working-copy tree
`.sase/artifacts/home/`, external bytes are pooled by digest under
`.sase/artifacts/pool/`, and clean tracked files in known repositories are recorded as
VCS-backed rows instead of copied. The committing agent's prompt archive then links
those rows from the agents sidecar. A captured `@file:<path>` reference expands to a
workspace-relative `.sase/artifacts/pool/...` path, matching the
`.sase/artifacts/home/...` convention used by the plain `@path` pass.

### Home Mode

When `is_home_mode=True`, file-reference processing skips copy side effects. This is
used when the invocation doesn't need workspace-local copies from `@path` references.

### Source Functions

The preprocessing steps delegate to functions from two libraries:

- **`macro`**: `process_macro_references()`, `extract_prompt_directives()`,
  `is_jinja2_template()`, `render_toplevel_jinja2()`
- **`artifact_refs`**: `process_artifact_references()`, `validate_artifact_references()`
- **`file_references`**: `process_command_substitution()`, `process_file_references()`,
  `validate_file_references()`, `format_with_prettier()`, `strip_html_comments()`

## Subprocess Streaming

Providers use shared helpers in `_subprocess.py` and the `_subprocess_*` modules to
stream LLM output in real time. Plain text, JSON-line, and provider-specific parsers
share the same artifact hooks for live replies and usage files.

### Mechanism

1. The provider spawns the CLI tool via `subprocess.Popen`. Providers that consume
   prompts from stdin set `stdin=PIPE`; OpenCode passes the prompt as the final
   `opencode run` argument, and Muse passes a `0o600` `--prompt-file` under SASE's
   managed temp root.
2. The prompt is supplied using the provider's documented transport, either stdin or an
   argv message argument.
3. Stdout and stderr are set to **non-blocking** mode via `os.set_blocking()`.
4. A `select.select()` loop polls both streams. Plain-text providers wait 0.1 seconds on
   every poll. JSON-line providers also wait 0.1 seconds, unless stdout records have
   already been decoded and are waiting. Those records are dispatched before the loop
   blocks, and stdout is not read again until that backlog is clear. Stderr can still be
   read on the same turn.
5. Plain-text providers read complete lines through the text wrapper. JSON-line
   providers read raw bytes: each read is at most 64 KiB, and one turn takes at most 256
   KiB from a pipe or 256 stdout records before it polls the process and can read the
   other pipe. The two pipes alternate which is served first. An incremental UTF-8
   decoder keeps a character that is split across reads, and undecodable bytes are
   replaced. Each complete stdout record is dispatched as it is decoded, including when
   one write contains many lines. A partial trailing line waits for the next read.
6. After the process exits, a normal shutdown drains whatever is still buffered.
   Plain-text providers switch the pipes back to blocking and read the remaining lines,
   including a final line with no newline. JSON-line providers keep the same bounded
   reads until both pipes reach EOF, then dispatch a final stdout record that has no
   trailing newline. If the teardown watchdog has already settled the process, reading
   stops after a short settle. Bytes already read are still dispatched, including a
   final stdout record with no trailing newline. Bytes still sitting in a pipe that a
   leaked child holds open can be left unread.
7. Helpers return stdout/assistant text, stderr diagnostics, return code, and usage data
   when the provider reports it.

### Live Reply File

When `SASE_ARTIFACTS_DIR` is set, the streaming output is also written in real-time to
`<SASE_ARTIFACTS_DIR>/live_reply.md`. While the Agents-tab follow is active, the Reply
card replaces that body from this file and `live_reply_timestamps.jsonl`; see
[Agents Tab Main Deck](../reference/tui/agents-main-deck.md#agents-tab-main-deck-1). The
file remains available after execution completes.

Providers that support richer streams may write sidecar artifacts. Codex and Grok both
write reasoning content to `<SASE_ARTIFACTS_DIR>/codex_thinking.jsonl` (the filename is
shared rather than renamed per provider, since sase's TUI `read_codex_thinking` reads
that exact path); providers with token counters write `<SASE_ARTIFACTS_DIR>/usage.json`;
Muse records the model it actually configured and its session id in
`<SASE_ARTIFACTS_DIR>/run_metadata.json`.

ACE follows reply growth in the Main Reply card for the selected live agent.
File-watcher events drive the normal update, with a one-second stat-only poll as a
backstop; reply writes do not reload the Agents roster. The provider's terminal reply
remains authoritative for the invocation result, while streamed deltas are the visible
in-progress copy and a salvage source when terminal text is unavailable. Muse controls
when it emits text: it is usually quiet through tool work, replies tend to arrive near
the end of generation, and a short answer may arrive as one burst. ACE displays
available deltas promptly but cannot show text Muse has not emitted. Under Rich's
interactive provider timer, console output keeps fragments together until a newline;
plain stdout and agent logs continue flushing fragments as they arrive.

### Output Suppression

When `suppress_output=True`, lines are still captured but not printed to the console.
This is used for background invocations where the caller only needs the final result.

### Provider Teardown Watchdog

A provider CLI can finish its turn, have its final declaration accepted, and then never
exit, often because a background process leaked from its tool sandbox keeps a pipe open.
Every provider that starts the interrupt monitor also starts a completion watchdog
(`start_completion_watchdog` in `_subprocess_plain.py`). It is a no-op without
`SASE_ARTIFACTS_DIR`.

Once `<SASE_ARTIFACTS_DIR>/final_submission.json` is written by a declaration accepted
_after_ the provider started, the watchdog waits a grace period. If the provider is
still alive when it expires, the watchdog terminates it (SIGTERM, then SIGKILL) and
reaps its leaked descendants. Descendants are found by walking `ppid` from a snapshot
taken _before_ the provider is signalled, so a leaked process in its own session or
process group is still reached. Registered live agents, monitors, and procs, the current
process, and its ancestors are never signalled, and neither is anything they spawned. If
the live registry cannot be read, no descendant is signalled at all.

The stall is recorded in `<SASE_ARTIFACTS_DIR>/provider_teardown_stall.json` (provider,
pid, acceptance time, grace, seconds waited, and the argv of each reaped descendant) and
as a `[sase] ...` line on stderr. The turn is not reported as failed:
`stream_json_lines` and `stream_process_output` return the streamed reply with return
code `0`.

| Variable                               | Default | Effect                                          |
| -------------------------------------- | ------- | ----------------------------------------------- |
| `SASE_PROVIDER_TEARDOWN_GRACE_SECONDS` | `120`   | Grace period after acceptance; `0` disables it. |

A provider that wedges _before_ submitting its declaration is not covered.

## Postprocessing

After a provider returns (or raises an error), the orchestration layer runs
postprocessing steps.

### On Success (`postprocess_success`) {#on-success-postprocesssuccess}

1. **Audio notification**: Plays a sound via `run_bam_command("Agent reply received")`
   (skipped if `suppress_output`).
2. **Log to sase.md**: Appends a timestamped entry with the prompt and response to
   `<artifacts_dir>/sase.md` (if `artifacts_dir` is set).
3. **Save chat history**: Writes to `~/.sase/chats/` if `workflow` is set. See
   [Chat History](#chat-history).

### On Error (`postprocess_error`) {#on-error-postprocesserror}

1. **Rich error display**: Prints the prompt and error via `print_prompt_and_response()`
   with an `_ERROR` suffix on the agent type label (skipped if `suppress_output`).
2. **Log to sase.md**: Same as success, but the response is the error message and the
   agent type gets an `_ERROR` suffix.
3. **Save error chat history**: Writes to `~/.sase/chats/` with an `_ERROR` agent
   suffix.

### sase.md Log Format

Each entry in the log file follows this format:

```markdown
## <timestamp> - <agent_type> - iteration <N> - tag <workflow_tag>

### PROMPT:

\`\`\` <prompt text> \`\`\`

### RESPONSE:

\`\`\` <response text> \`\`\`

---
```

### Prompt File Saving

Before invocation, the preprocessed prompt is saved to
`<artifacts_dir>/<agent_type>_prompt.md` (or `<agent_type>_iter_<N>_prompt.md` if an
iteration number is set). This allows reviewing the exact prompt that was sent.

## Chat History

Chat histories are stored as markdown files in `~/.sase/chats/`.

### File Naming

```
<branch_or_workspace>-<workflow>-[<agent>-]<timestamp>.md
```

| Part                  | Source                                   | Example             |
| --------------------- | ---------------------------------------- | ------------------- |
| `branch_or_workspace` | Output of `branch_or_workspace_name`     | `my_feature`        |
| `workflow`            | Workflow name, normalized                | `crs`, `run`        |
| `agent`               | Agent type (omitted if same as workflow) | `editor`, `planner` |
| `timestamp`           | `YYmmdd_HHMMSS` format                   | `260214_153042`     |

Dashes and slashes in workflow names are normalized to underscores.

### File Format

```markdown
# Chat History - <workflow> (<agent>)

**Timestamp** <display_timestamp>

**MODEL** <provider>/<model>

**AGENT** <sase_agent_name>

## Previous Conversation

<previous history if resuming>

---

## Prompt

<prompt text>

## Response

<response text>
```

The `MODEL` and `AGENT` blocks are omitted when the invocation did not provide that
metadata. `MODEL` can contain just a model name, just a provider name, or both. When
both provider and model are known, it is rendered as `<provider>/<model>` unless the
model already includes that prefix.

### Resume Support

Resume uses the `#fork` and `#fork_by_chat` workflows through normal detached `sase run`
launches. `#fork` resolves an agent name to its artifacts directory, extracts the
response path from `done.json`, and delegates to `#fork_by_chat`, which loads the chat
history and prepends it to the new conversation. Use `#fork_by_chat(<path-or-basename>)`
for direct chat-file-based resumption.

Fork expansion is recursive: if the loaded chat history itself contains `#fork` or
`#fork_by_chat` references, those are expanded inline as well. Legacy `#resume` and
`#resume_by_chat` references in old transcripts are still recognized. Cycle detection
prevents infinite loops when chat histories reference each other.

## Invocation Lifecycle

The `invoke_agent()` function in `_invoke.py` orchestrates the complete lifecycle of an
LLM invocation. Here is the end-to-end flow:

```
invoke_agent(prompt, agent_type, model_tier, ...)
│
├── 1. Handle deprecated model_size → model_tier mapping
├── 2. Check SASE_MODEL_TIER_OVERRIDE / SASE_MODEL_SIZE_OVERRIDE env vars
├── 3. Build LoggingContext from parameters
│
├── 4. Preprocess prompt unless skip_preprocessing=True
│   ├── early phase: optional workflow Jinja2, macro expansion, directive extraction
│   └── late phase: command substitution, file refs, top-level Jinja2, formatting, comment stripping
│
├── 5. Resolve %model / temporary provider-model override
├── 6. Display decision counts (if not suppressed)
├── 7. Print prompt via Rich (if not suppressed)
├── 8. Generate or use provided timestamp
├── 9. Save prompt to artifacts directory
│
├── 10. Get provider from registry and invoke
│   ├── Run the continuation budget preflight (monitor successors or when enforced)
│   ├── Build CLI command with flags
│   ├── Spawn subprocess (Popen)
│   ├── Supply prompt via provider transport
│   └── Stream stdout/stderr in real-time
│
├── 11. Run commit finalizer for SASE agent runs
│   ├── Skip when disabled or outside an agent run
│   ├── Check main workspace and configured Git linked repos
│   ├── Enforce dirty linked repo clones
│   ├── Auto-commit exact tracked SDD done-status closeouts
│   └── Run bounded follow-up provider invocations until enforced repos are clean or failed
│
├── 12. Postprocess
│   ├── Success path:
│   │   ├── Audio notification
│   │   ├── Log to sase.md
│   │   └── Save chat history
│   └── Error path:
│       ├── Rich error display
│       ├── Log error to sase.md
│       └── Save error chat history
│
└── 13. Return AIMessage(content=response), or raise LLMInvocationError on failure
```

### Parameters

| Parameter             | Type                        | Default    | Description                                       |
| --------------------- | --------------------------- | ---------- | ------------------------------------------------- |
| `prompt`              | `str`                       | (required) | Raw prompt to send                                |
| `agent_type`          | `str`                       | (required) | Agent type label (e.g., `"editor"`)               |
| `model_tier`          | `ModelTier`                 | `"large"`  | Model tier to use                                 |
| `model_size`          | `"big" \| "little" \| None` | `None`     | Deprecated, use `model_tier`                      |
| `iteration`           | `int \| None`               | `None`     | Iteration number for logging                      |
| `workflow_tag`        | `str \| None`               | `None`     | Workflow tag for logging                          |
| `artifacts_dir`       | `str \| None`               | `None`     | Directory for sase.md, prompt, and stream files   |
| `workflow`            | `str \| None`               | `None`     | Workflow name for chat history                    |
| `suppress_output`     | `bool`                      | `False`    | Suppress console output                           |
| `timestamp`           | `str \| None`               | `None`     | Shared timestamp (`YYmmdd_HHMMSS`)                |
| `is_home_mode`        | `bool`                      | `False`    | Skip file copying for `@` references              |
| `branch_or_workspace` | `str \| None`               | `None`     | Override the chat-history filename prefix         |
| `decision_counts`     | `dict[str, Any] \| None`    | `None`     | Planning agent decision counts                    |
| `provider_name`       | `str \| None`               | `None`     | Override provider (default from config)           |
| `skip_preprocessing`  | `bool`                      | `False`    | Use `prompt` as already-preprocessed input        |
| `directives`          | `PromptDirectives \| None`  | `None`     | Pre-extracted directives for `skip_preprocessing` |

### Return Value

On success, returns an `AIMessage` (from `langchain_core.messages`) whose `content` is
the provider response. On provider failure, `invoke_agent()` logs the error and raises
`LLMInvocationError` with the formatted error text.

## Related

- [Providers and models](../reference/providers/index.md) — user-facing provider
  behavior.
- [External provider plugins](../reference/providers/plugins.md) — provider extension
  points.
