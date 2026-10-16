---
title: "Installing and authenticating agent CLIs"
description:
  "Provider CLIs that SASE can install, authenticate, inspect, and update safely."
---

# Installing & Authenticating Agent Providers

SASE normally orchestrates an existing coding-agent CLI; the exception is the bundled
`fakey` testing provider. You need **at least one** supported real provider CLI
installed **and authenticated** for production work. This page collects the install
command, the authentication command, and a link to each vendor's canonical documentation
for every provider SASE currently supports. Claude Code, Codex CLI, OpenCode, Qwen Code,
and Grok Build are npm packages (so installing them needs `node` and `npm` on your
`PATH`; OpenCode's section also links its vendor installer), while the Antigravity CLI
and Muse Code use their own install methods, shown in their sections below. SASE can
install most providers for you with [`sase agent-cli install`](#inventory-and-updates):
every npm-packaged CLI installs via `npm install -g <package>`, and Muse Code installs
from its provider-declared install script. The Antigravity CLI is the one built-in
provider you install yourself.

`sase doctor` — specifically `sase doctor -C llm.auth -v` — is the authoritative
readiness check. It prints the same per-provider install and auth hints documented here,
so if this page and `sase doctor` ever disagree, trust the doctor output and open an
issue. Vendor docs may list additional installer and account options; the snippets below
intentionally match SASE's doctor hints.

Installed provider CLIs are also launchable interactively with
[`sase tmux-agent`](../tui/launch-control.md#tmux-agent) (or `t` in Launch Control).
Those windows are unmanaged agent CLIs, not SASE agents — they do not appear in
`sase agent list`.

If Launch Control or `sase doctor` reports a provider as disabled, that is routing
policy, not a missing install. A **hard** disable blocks SASE automatic routing and
explicit `%model` requests for that provider until expiry or clearing; a **soft**
disable only steers pools away from it. Usage-limit detection can hard-disable Claude
for a week and Grok Build for 48 hours automatically. Interactive tmux Agent windows
still launch a hard-disabled CLI. See
[Provider routing](../tui/launch-control.md#provider-routing-controls) and
[Usage-Limit Auto-Disable](usage.md#usage-limit-auto-disable).

## Instruction delivery

SASE records intended instructions and delivers them through the provider's supported
channel. For each root provider invocation with an artifacts directory, SASE attempts to
render a memory-built bundle and v2 manifest into `<artifacts>/instructions/`.
Successful preparation exports `SASE_INSTRUCTIONS_FILE` for that call, then restores it.
Claude, Codex, Grok, and Muse deliver the root bundle through explicit adapter channels
by default, suppressing SASE-owned native instruction files according to each adapter's
capabilities. Per-provider feature flags select explicit or native delivery. The
architecture is recorded as
[Instructions Are Rendered Per Invocation And Delivered By Adapters](https://github.com/sase-org/sase/blob/master/sase/memory/decisions/instructions-per-invocation.md).
The manifest alone does not prove that a provider loaded the bundle; use
[Verifying instruction delivery](#verifying-instruction-delivery). See
[Delivery](../../contribute/instruction-bundle-internals.md#delivery).

A **root** is the agent SASE launches; a **native helper** is a subagent started through
that provider's tools. Explicit delivery combines the shared contract, project memory,
and home memory in one bundle and suppresses native duplicates as shown below. Calls
without an artifacts directory use the provider's native instruction path.

| Provider            | Root channel (flag on)                                             | Subagent                                                                 | Native suppression (flag on)                                                                | Flag                           |
| ------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------ |
| Claude              | `--append-system-prompt-file` (`claude.append_system_prompt_file`) | `--append-subagent-system-prompt-file`, or `none` if the CLI probe fails | exact-path `claudeMdExcludes` of SASE-owned root and home files; `autoMemoryEnabled: false` | `claude_explicit_instructions` |
| Codex               | `developer_instructions` (`codex.developer_instructions`, 32 KiB)  | `inherits_root`                                                          | `project_doc_max_bytes=0` in SASE-managed projects; no SASE `AGENTS.md` in the shadow home  | `codex_explicit_instructions`  |
| Grok                | `--rules` (`grok.rules`, 120 KiB)                                  | `none`                                                                   | none needed (no `--trust`); `GROK_MEMORY=0`                                                 | `grok_explicit_instructions`   |
| Muse                | prompt prefix (`muse.prompt_prefix`)                               | `none`                                                                   | drop `--trust-workspace`                                                                    | `muse_explicit_instructions`   |
| agy, Qwen, OpenCode | native `AGENTS.md` discovery (`provider_legacy`)                   | `inherits_native`                                                        | none                                                                                        | none                           |

### Rollback

`sase flag disable <provider>_explicit_instructions` on each execution host selects that
provider's native instruction path. Substitute `claude`, `codex`, `grok`, or `muse` for
`<provider>`; `sase flag enable <provider>_explicit_instructions` restores explicit
delivery. A render or delivery failure already falls back per invocation, restoring the
native shadow-home paths for Codex; see
[Codex instruction delivery](codex.md#codex-instruction-delivery). Codex's allowlist
shadow home applies in both flag states.

## Verifying instruction delivery

`sase instructions verify` compares SASE's recorded delivery intent with instruction
text observable in providers' own session records, including native helpers where
supported. Missing or partial logs can leave delivery unverifiable. The default window
is the newest 20 runs per provider from the last 7 days (`-n`, maximum 200, and
`--since` change that). The command reports; it does not gate (exit 0 even when rows
show bugs). A bad `--since` or `--until` value exits 2. See
[Instruction Bundles](../memory/instruction-bundles.md) for the memory-built bundles
behind these columns.

| Column        | Meaning                                                                                             |
| ------------- | --------------------------------------------------------------------------------------------------- |
| `manifest`    | Observed sessions with a recorded manifest for the same provider (`k/N`; agy counts runs).          |
| `bundle`      | Count of markers for the matched manifest invocation (`—` when unavailable, `◌` when unobservable). |
| `delivery`    | `explicit`, `legacy:<reason>`, or `shadow` for the matched manifest.                                |
| `contract`    | Occurrences of `SASE Final Declaration` across native and explicit sources.                         |
| `home`        | Whether the home layer was loaded through either channel.                                           |
| `project`     | Whether the project layer was loaded through either channel.                                        |
| `directive`   | Whether the provider's single-turn directive appeared in either channel.                            |
| `native-full` | Contract occurrences in native sources only.                                                        |
| `foreign`     | Claude's exact auto-memory fingerprint, Codex foreign global AGENTS.md, or Grok memory state.       |
| `helpers`     | Helper type, template, final attempts, accepted declarations, helper marker, and root-marker leak.  |

A session first matches a manifest by its bundle marker's invocation id. A session that
carries another invocation's marker never falls through to session id or time. Otherwise
it matches by the adapter-recorded session id, then by provider and render time (5 s of
skew allowed) against records that recorded no session ids. Explicit records with
recorded session ids are not time-matched. Codex rollout stems match a recorded thread
id: discovery uses the filename stem (`rollout-<local-time>-<thread-id>`), and manifests
store the bare thread id. Codex rollouts are found in local-date directories
(`~/.codex/sessions/YYYY/MM/DD`), so discovery scans one UTC day on each side of the run
window.

A marker-less session that no same-provider root record lists, when all of those records
recorded session ids, is not the run's session. A nested `claude -p` started by a tool
inside the workspace is the typical case. verify, coverage, and conformance skip such
sessions; `verify -a` labels each one `⊘ foreign` instead of scoring it.

`sase instructions verify -c` prints the per-provider-purpose coverage table: manifests,
sessions, covered, up to 10 uncovered `(agent, session)` pairs, shadow-failure
(`.error.json`) counts, and warm/cold `render_ms` p50/p95. With `-a NAME`, each observed
root session also gets its intended-vs-observed section table: every included manifest
section with the count of loaded sources whose text contains it, split into `native` and
`explicit` channels (frame and heading-only sections are skipped). Counts use non-
overlapping occurrences. Partial transcripts retain counts found in the prefix; a row is
`◌` only when no occurrence appears in a partial read.

Symbols: `✓` present, `✗` absent, `◌` unverifiable (agy reports every instruction column
as `◌`, with directive presence only when the conversation record exposes the prompt).

JSON includes a `channels` breakdown for each delivery column with native and explicit
values. Native sources are Claude `instructions` attachments, the Codex
`# AGENTS.md instructions` block, Muse `rules_file` records, and Grok `agents_md_files`.
Explicit sources are Claude `prompt_snapshot.systemPrompt`, Codex developer messages,
the Grok `<human_rules>` block, and Muse prompt prefixes. Muse `rules_file` content
stays native even when it is also represented in run-context records.

`sase doctor -D -C instructions` runs the deep checks. `instructions.delivery` applies
the explicit contract (bundle 1×, contract 1×, project ✓, directive ✓, native-full 0,
and home ✓ when present in the manifest) while retaining compatibility expectations for
providers with no observed explicit sessions. `instructions.conformance` WARNs on
missing or duplicate root markers, missing helper markers, root markers leaking into
Claude helpers, and unexpected delivery fallbacks. `instructions.helpers` WARNs on
accepted helper declarations or root calls denied by the helper guard.

`instructions.coverage` samples the newest 10 runs per provider in the last 24 hours.
When that sample contains manifests, it WARNs on bundle-render errors and uncovered
sessions whose runs began after the earliest sampled manifest. With no manifests it
reports `SKIP`, so a skipped check is not proof that bundles were delivered.

## Soak readout

`sase instructions readout` classifies finished, provider-backed root runs in a window
(`-s/--since` default `7d`, `-u/--until`) per provider and delivery mode. Monitor and
gate turns are excluded; research runs get their own rows; dismissed runs without
`done.json` count as `unknown`. The command reports; it does not gate. A bad `--since`
or `--until` value exits 2.

Delivery mode is `explicit` when the ordinary root manifest has
`delivery.status: explicit`, `legacy` for `inherits_native` or `shadow`, and `none` for
runs without a manifest. The table subtitle prints each provider's first explicit
`rendered_at`; the soak watch starts there.

Classes, first match wins. Handoffs are recognized from host records first:

1. accepted submission (`final_submission.json`)
2. plan handoff (`plan_path.json`, written only by the plan-handoff handler)
3. monitor handoff with a prepared completion intent (`monitor_id` /
   `monitor_member_agent_name` plus a non-empty
   `continuation/completion_intents/index.json` `intents` object, or a real
   `sase final prepare` in the tool-call tail)
4. plain monitor handoff (`monitor_id` / `monitor_member_agent_name` without a prepared
   intent)
5. other adopted handoff (lifecycle `handoff` phase: questions, gate, pipe, or
   successor)
6. tool-call text fallback for older runs (`sase plan propose` / `validate` / `decide`;
   `sase monitor start` with or without a real prepare; `sase pipe` / `sase questions` /
   `sase handoff`)
7. declaration not required (`final_context.json`)
8. **miss**

An aborted handoff (`handoff_aborted.json`) is never a handoff. Non-Claude providers do
not record the handoff call itself in `tool_calls.jsonl` (the handoff SIGTERMs the
runner before that call is flushed), so host records are the authoritative signal.
Readouts computed before this host-evidence step overcount misses for Grok, Codex, and
Muse.

Misses are an upper bound and are labelled `≤`. `-j` emits one stable JSON document with
`schema_version: 1`. Memory columns join `~/.sase/projects/<project>/memory_reads.jsonl`
rows to runs by artifact identity and time (mean audited reads per run, and the share of
runs with at least one read).

```bash
sase instructions readout --since 7d
sase instructions readout -p claude -j
sase instructions readout -s 2026-09-10T00:00:00Z -u 2026-10-05T00:00:00Z
```

## Root and helper agents

Only the root SASE agent — the provider turn SASE launched — submits the final
declaration; native subagents and forked helpers return their result to their parent
instead (decision `helpers-return-roots-declare`). Mechanical enforcement exists only
where a provider exposes a helper channel. Everything else relies on that contract
sentence. Limits by provider capability, not hidden:

| Provider  | Helper coverage                                                                                                                                                                                                                        |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude    | Helper bundle plus PreToolUse guard (static template on fallback); live probes confirm forked (depth-2) helpers carry `agent_id`, so the guard covers forks. Further details: [Instruction Bundles](../memory/instruction-bundles.md). |
| Codex     | Children inherit the process-level `developer_instructions`. There is no separate helper bundle or mechanical guard; helpers must follow the root-only declaration rule.                                                               |
| Grok      | Subagents get nothing; sentence only, with the child channel deferred.                                                                                                                                                                 |
| Muse, agy | No helper coverage.                                                                                                                                                                                                                    |

## Claude Code

Anthropic's Claude Code CLI (`claude`). This is SASE's highest-priority autodetect
provider.

### Install

```bash
npm install -g @anthropic-ai/claude-code
```

### Authenticate

SASE doctor hint: run `claude` and complete the login flow.

Alternatively, Claude Code honors API-key / token variables such as `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, and `CLAUDE_CODE_OAUTH_TOKEN` — see the canonical docs for the
full, current list.

Canonical docs: <https://code.claude.com/docs>

### Native helpers

With `claude_explicit_instructions` enabled (the default), SASE delivers the root bundle
through `--append-system-prompt-file` and a separate helper bundle through
`--append-subagent-system-prompt-file`. Per-run settings exclude only exact SASE-owned
root and home instruction paths and disable Claude auto-memory. Nested repo guides and
hand-written home files remain discoverable. Resume cycles retain their session
snapshot; interrupt restarts use the same delivered files with a new recorded session
id.

Native subagents inherit the root's environment, so the helper bundle
(`# SASE Helper Instructions`) accompanies a PreToolUse guard that denies their
root-only operations (`sase final …`, turn-ending commands, root-only skills); forked
helpers carry `agent_id` and are covered too. Helper render or file failures use the
packaged static helper template. An unsupported helper channel omits the helper file and
keeps the guard. Root file failures restore the single-turn directive and native
discovery for that invocation. Disabling `claude_explicit_instructions`, or invoking
without an instruction delivery plan, restores the native argv, static helper template,
native discovery, and auto-memory behavior. Details:
[Claude Code Integration](claude.md#native-helpers).

## Codex CLI

OpenAI's Codex CLI (`codex`).

### Install

```bash
npm install -g @openai/codex
```

### Authenticate

SASE doctor hint: run `codex login`.

Alternatively, Codex honors `OPENAI_API_KEY` — see the canonical docs for details.

Canonical docs: <https://developers.openai.com/codex/cli>

### Instruction delivery

With `codex_explicit_instructions` enabled (the default), SASE sends the root bundle
through `developer_instructions`. For a managed project it also sets
`project_doc_max_bytes=0`, disabling native project-document loading for that
invocation. The per-run shadow `$CODEX_HOME` uses an allowlist: `config.toml` is copied,
`sessions/` stays linked, and SQLite state and `history.jsonl` are never linked. With
the flag enabled, it retains foreign global instruction files but omits SASE-owned
copies and native memories. Helpers inherit the root bundle (`inherits_root`). Disabling
the flag restores the single-turn directive, native project discovery, and
home-instruction paths; the allowlist still applies. See
[Codex instruction delivery](codex.md#codex-instruction-delivery) for the size limit,
fallback limitation, and shadow-home details.

## OpenCode

The open-source OpenCode CLI (`opencode`).

### Install

```bash
install from https://opencode.ai/docs
```

SASE can also install it from its npm package with `sase agent-cli install opencode`
(`npm install -g opencode-ai`).

### Authenticate

SASE doctor hint: run `opencode auth login`.

OpenCode can also read provider API keys from the environment (for example
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ZHIPU_API_KEY`, and other
`*_API_KEY` variables) — its canonical docs list the current set.

Canonical docs: <https://opencode.ai/docs>

## Qwen Code

Alibaba's Qwen Code CLI (`qwen`).

### Install

```bash
npm install -g @qwen-code/qwen-code
```

### Authenticate

SASE doctor hint: run `qwen` and complete the login flow.

Qwen Code can also use API-key access through variables such as `DASHSCOPE_API_KEY`,
`QWEN_API_KEY`, or `OPENROUTER_API_KEY` — see the canonical docs for the current list.

Canonical docs: <https://github.com/QwenLM/qwen-code>

## Muse Code

Meta's Muse Code CLI (`muse`). SASE never auto-detects it, because `muse` is a generic
executable name. Select it with `llm_provider.provider: muse`, `%model:muse/<model>`, or
`SASE_MUSE_PATH`. Model-alias routing is separate: whichever shipped size aliases
currently include a Contributor member can select it whenever a `muse` executable is
available — and the Contributor model trains on its inputs and outputs. See
[Muse Code Integration](muse.md#muse-code-integration) and the generated
[shipped size-alias defaults](models.md#implicit-role-aliases) for how to opt out.

### Install

```bash
sase agent-cli install muse
```

SASE downloads <https://dev.meta.ai/install.sh> itself over HTTPS, shows the URL, the
SHA-256 digest of exactly what it downloaded, the exact shell-free command, and the
target directory (`$MUSE_INSTALL_DIR`, default `~/.local/bin`), and only then runs it
after your confirmation. It passes `MUSE_UPGRADE_MODE=1`, which suppresses the
installer's `export PATH=...` appends — **SASE never edits your shell startup files.**
If the install directory is not on your `PATH`, SASE prints the exact export line to add
yourself. Use `-n/--dry-run` to see the whole plan, digest included, without executing
anything.

### Authenticate

SASE doctor hint: run `muse login`, or set `META_API_KEY`.

### Update

Muse is self-updating through its own launcher, so `sase agent-cli update muse` runs
`MUSE_SYNC_UPDATE=1 muse --version`, which updates the launcher and the binary and then
reports the resulting version. Latest versions come from Muse's channel endpoint rather
than npm, and versions compare exactly rather than by PEP 440 — Muse's release ids
(`0.1.0-R708.1`) are not PEP 440 versions, and a semver comparison would report "no
known updates" forever.

SASE always launches agent runs with `MUSE_NO_AUTO_UPDATE=1` so Muse cannot swap its own
binary mid-run; update it through `sase agent-cli` instead.

### Instruction delivery

With the default-on `muse_explicit_instructions` sunset flag, SASE prefixes Muse's
prompt with the complete rendered root bundle and invocation marker, then the original
user prompt. It omits `--trust-workspace`, so Muse does not also load native workspace
instructions. Each generated `--session-id` is recorded in the manifest. Interrupt and
stranded-wait continuations reuse the same prefixed prompt, keeping one bundle and one
`SASE Final Declaration` contract occurrence per cycle. `--no-foreign-personal-context`
remains enabled.

If explicit delivery is disabled, Muse keeps its single-turn directive prompt prefix and
`--trust-workspace`. A failed explicit prefix falls back to that native instruction path
for the invocation. Set `muse_explicit_instructions` off to use native delivery during
the seven-day soak.

### Subscription usage { #muse-subscription-usage }

Muse collects [subscription usage](#subscription-usage) — its 5-hour session window and
its weekly window — through a local probe against `muse serve` (Muse's MSP session
host). The probe makes **no model call and spends no tokens**: it opens an ephemeral,
shell-less host, starts a session on Muse's built-in `echo` provider, and reads the
usage the host learns in response. It aborts without sending a turn if the host does not
report an `echo` session with no model, so a future Muse that ignores the request can
never cost a real model turn on a refresh tick.

The probe runs on the normal background cadence
(`llm_provider.usage_metrics.refresh_seconds`, or `active_refresh_seconds` while Muse is
[in active use](../config/llm-provider-behavior.md#llmproviderusagemetrics), never
faster than Muse's 180-second polling floor), costs about three seconds of wall clock
per refresh, and follows the same eligibility rules as every other provider: Muse must
be resolvable and either referenced by a model alias or explicitly enabled. The
user-facing switch is `llm_provider.usage_metrics.providers.muse.enabled`. Inspect the
result with `sase usage list -p muse`. A host that has not yet reported any usage — for
example a logged-out one — is shown as no observation rather than as `0%` used.

Canonical docs: <https://developer.meta.com/ai/resources/blog/build-with-muse-code/>

## Grok Build

xAI's Grok Build CLI (`grok`). Default provider autodetection never selects it, because
the executable name collides with `grok-dev` (a stale community CLI that also uses
`~/.grok/`). Select the provider explicitly with `llm_provider.provider: grok` or
`%model:grok/<model>` (see the generated
[Built-in Model Catalog](models.md#built-in-model-catalog) for current names); use
`SASE_GROK_PATH` when you also need to choose the executable. Model-alias routing is
separate: whenever a `grok` executable is available, whichever shipped size aliases
currently target Grok can select it (see the generated
[shipped size-alias defaults](models.md#implicit-role-aliases)).

Routing availability checks only whether the executable exists; it does not verify that
the binary is Grok Build. Run `sase doctor` before launching. Its bounded
`grok --version` probe reports a distinct, actionable identity-mismatch finding; point
`SASE_GROK_PATH` at the `@xai-official/grok` binary before continuing if that warning
appears.

### Install

```bash
npm install -g @xai-official/grok
```

`@xai-official/grok` is an npm trampoline: `npm install -g` places a shim on `PATH`, but
the real Grok Build binary it downloads on first run lives under `~/.grok/bin/`, not
`node_modules`.

### Authenticate

SASE doctor hint: run `grok login` (or `grok login --device-code` on a headless host),
or set `XAI_API_KEY`.

### Update

`sase agent-cli update grok` runs Grok Build's own self-update (`grok update`).

SASE always launches agent runs with `--no-auto-update` so Grok cannot swap its own
binary mid-run; update it through `sase agent-cli` instead.

### Execution posture

SASE runs Grok with `--permission-mode bypassPermissions` and no sandbox profile — the
same posture SASE already uses for Codex and OpenCode. This is powerful local execution:
Grok can read, write, and run shell commands anywhere the SASE process can, without
per-action approval prompts.

### Effort ceiling

Grok models accept only `low`, `medium`, `high`, and `xhigh` for `--effort` (see the
generated [Built-in Model Catalog](models.md#built-in-model-catalog) for the current
model names). `%effort:none`, `%effort:minimal`, and `%effort:max` raise a clean SASE
error rather than a Grok process crash. The generated
[shipped size-alias defaults](models.md#implicit-role-aliases) show the effort each
alias target carries. A user-configured Codex target that pairs an alias-borne `@max` is
best-effort: `max` is logged and skipped and the CLI runs at its own default effort
instead of erroring.

### Usage is best-effort

Grok's `streaming-messages-json` output is a projection of its own internal usage
ledger. Subagent turns can set an internal "usage incomplete" flag that the projection
drops silently, and an interrupted turn can under-count. Text and tool records are
unaffected, and cost reporting (`total_cost_usd`) does work on the OAuth login path.

### Instruction delivery

SASE runs Grok in untrusted workspaces with no `--trust` flag, so Grok loads no native
instruction files (`agents_md_files` stays empty in the session's
`prompt_context.json`). SASE generates no `GROK.md` shim. With the default-on
`grok_explicit_instructions` sunset flag, `--rules` receives the complete rendered root
bundle once, including its home and project layers, followed by the invocation marker.
The adapter records Grok's `--session-id` for each cycle and sets `GROK_MEMORY=0` for
that process. The subagent slot is `none`.

The 120 KiB argv limit applies to the delivered bundle. If it cannot be sent, that
invocation falls back atomically to the native `--rules` payload: the SASE single-turn
directive (opening with `SASE single-turn instructions for Grok:`), followed by the
project root `AGENTS.md` text in SASE-managed projects (the directive alone elsewhere).
This fallback leaves Grok's memory-v2 setting unchanged. Set
`grok_explicit_instructions` off to use that native payload for every invocation.

### Privacy

Prompts, workspace context, and tool results are sent to xAI. Non-enterprise Grok Build
sessions are **not** zero-data-retention by default; review Grok Build's own privacy and
telemetry controls (including `/privacy`, `[telemetry]` settings, and Zero Data
Retention for enterprise accounts) before pointing SASE at Grok Build on a workspace
with sensitive contents. See <https://docs.x.ai/build/settings> for the current
controls. SASE does not set or manage any of these settings on your behalf.

Canonical docs: <https://docs.x.ai/build/overview>

## Antigravity CLI

Google's Antigravity CLI (`agy`). There is no separate "Gemini CLI" provider in SASE;
`GEMINI.md` exists only because Antigravity reads it for workspace context.

### Install

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

### Authenticate

SASE doctor hint: run `agy` and complete the login/trust onboarding.

Alternatively, Antigravity honors `GEMINI_API_KEY` and `GOOGLE_API_KEY` — see the
canonical docs for details.

### Subscription usage { #agy-subscription-usage }

Antigravity collects [subscription usage](#subscription-usage) — its Gemini weekly and
5-hour windows plus the Claude/GPT weekly and 5-hour windows — through a local `/usage`
probe. The probe makes **no model call and spends no tokens**: it runs
`agy -p /usage --output-format json --mode plan --sandbox --print-timeout 15s` in print
mode with stdin closed, which answers without starting an agent turn. It requires
`agy >= 1.1.11` (older builds would run `/usage` as a real paid turn, so the collector
refuses them). A logged-out CLI prints `Authentication required…` to stderr and then
blocks on an OAuth paste prompt; the collector watches stderr and returns logged-out
promptly instead of waiting out the deadline. Its log file stays in the probe's managed
temp dir rather than `~/.gemini/…`, and auto-update is disabled for the probe spawn.

The probe runs on the normal background cadence
(`llm_provider.usage_metrics.refresh_seconds`, or `active_refresh_seconds` while agy is
[in active use](../config/llm-provider-behavior.md#llmproviderusagemetrics), never
faster than its 120-second polling floor), costs about three to five seconds of wall
clock per refresh, and follows the same eligibility rules as every other provider: agy
must be resolvable and either referenced by a model alias or explicitly enabled. The
Gemini buckets are `model_family`-scoped to `gemini` and the Claude/GPT buckets to `3p`.
The user-facing switch is `llm_provider.usage_metrics.providers.agy.enabled`. Inspect
the result with `sase usage list -p agy`.

Canonical docs: <https://antigravity.google/docs/cli-install>

## Fakey Testing Provider

The deterministic `fakey` CLI is bundled with SASE for launch, failure, retry, and UI
testing. It requires no separate installation or authentication and is deliberately
placed last in provider autodetection. It is also hidden from sase's TUI model picker
and `%model` completion menu, so select it explicitly with a model such as
`%model:fakey-large` or `llm_provider.provider: fakey`; do not use it for production
coding work.

Because Fakey is bundled and internal, it is also absent from `sase agent-cli`
inventories and the Admin Center's **Updates** tab **Agent CLIs** section. That
management visibility is separate from routing and diagnostics: explicit fakey
selection, the `fakey` console script, provider autodetection metadata, and
`sase doctor` checks remain supported.

For demos and hermetic end-to-end tests, `SASE_LLM_EXEC_PROVIDER=fakey` dispatches
through fakey while preserving the requested provider/model in display metadata. Run
artifacts record the dispatched provider as `exec_llm_provider`.

See the [fakey reference](../../contribute/fakey.md) for scenarios and environment
controls.

## Verify

After installing and authenticating at least one provider, confirm SASE can find and use
it:

```bash
sase doctor -C llm.auth -v
```

Expect the provider to report ready. `sase doctor` is read-only and does not call
provider APIs, so it verifies that the CLI is on your `PATH` and that local auth
evidence exists — it cannot confirm your token is still valid. If the check reports a
missing executable or an authentication gap, re-run the relevant install/auth step above
and check again.

If a provider CLI lives at a non-standard path, point SASE at it with the provider's
`SASE_<PROVIDER>_PATH` override environment variable — `SASE_CLAUDE_PATH`,
`SASE_CODEX_PATH`, `SASE_OPENCODE_PATH`, `SASE_QWEN_PATH`, `SASE_AGY_PATH`,
`SASE_MUSE_PATH`, `SASE_GROK_PATH`, or `SASE_FAKEY_PATH`. `sase doctor`, routing
availability, `sase agent-cli`, and tmux Agent honor every one of these. Agent runs
honor them too, with one current exception: the Claude provider always launches `claude`
from `PATH`, so keep a working `claude` on `PATH` even when `SASE_CLAUDE_PATH` is set.
For deeper integration details (model mapping, per-provider environment variables,
retry/fallback behavior), see the [LLM provider reference](index.md).

## Subscription Usage

Subscription usage is a machine-local view of included provider allowance windows — for
example, the remaining share of a session or weekly plan window, which models share it,
when that window resets, and when SASE last observed it. It is separate from per-agent
token usage and from [usage-limit auto-disable](usage.md#usage-limit-auto-disable): a
low observation does not itself disable routing.

Inspect the cache without provider I/O via `sase usage` / `sase usage list`. Use
`sase usage refresh` to submit or join bounded durable probes; foreground mode waits and
then renders the updated cache.

```bash
sase usage
sase usage list -p codex --verbose
sase usage refresh
```

sase's TUI exposes the same cache from Launch Control: press `u`, or choose **Open
Providers · Usage** from the command palette. See
[Providers · Usage](../tui/launch-control.md#providers-usage).

Observations are dated best-effort readings from each provider's own CLI, not guarantees
of remaining capacity. Periodic collection runs on the scheduler's 60-second `usage`
routine and probes inline, so it creates no proc rows; user-triggered refreshes still
submit visible procs. Collection is on by default; opt out with
`llm_provider.usage_metrics.enabled: false`, or per provider on a host that shares an
account with another machine. See [Subscription Usage](usage.md#subscription-usage).

## Inventory and Updates

`sase agent-cli` is the inventory, install, and update surface for independently
manageable provider CLIs on this machine. Internal or bundled providers can opt out when
they are not separately installed or updated. A bare `sase agent-cli` means
`sase agent-cli list`.

```bash
sase agent-cli list            # manageable provider CLIs, versions, and install methods
sase agent-cli list -v         # add resolved executable paths, docs URLs, and probe errors
sase agent-cli update codex    # update one CLI
sase agent-cli update -a -n    # preview every planned command without running anything
sase agent-cli install muse    # install a CLI from the install script its provider declares
sase agent-cli install muse -n # show the URL, digest, command, and target; execute nothing
```

`list` shows each CLI's resolved binary, installed version, latest known version,
install method, and an `↑` marker when an update is available. A CLI that is not
installed shows its install hint instead. The footer summarizes how many of the
supported CLIs are installed and whether any updates are known. Latest versions come
from the npm registry — or, for a channel-versioned CLI such as Muse Code, from the
provider-declared JSON endpoint — and are cached: `-o/--offline` uses only the cache and
never contacts the network, while `-r/--refresh` bypasses the cache. `-j/--json` emits a
stable machine-readable envelope. Most CLIs compare versions with PEP 440 semantics; a
provider whose release ids are not PEP 440 (Muse Code) declares exact comparison
instead, so "different from what I have" is precisely "there is an update".

`update` takes CLI names (provider, binary, or display name) or `-a/--all` for every
installed CLI; a bare `sase agent-cli update` with neither is a usage error. Commands
run sequentially and without a shell. `-n/--dry-run` prints the exact command or skip
reason for each CLI and changes nothing.

SASE only automates updates it can identify safely, and it never guesses an update
command. `sase agent-cli` itself never runs `sudo`; when a manual step needs root, an
agent must go through a human-reviewed [sudo request](../automation/sudo.md) instead:

| Install method                   | Behavior                                                                                |
| -------------------------------- | --------------------------------------------------------------------------------------- |
| npm, writable global root        | Runs `npm install -g <package>@latest`.                                                 |
| npm, non-writable global root    | Skipped as manual, with the exact command to run under an npm setup owned by your user. |
| Self-managed with a self-update  | Runs the provider's own declared update command, with any env overlay it declares.      |
| Homebrew                         | Skipped as manual, with the `brew upgrade <package>` command to run.                    |
| Bundled visible provider         | Skipped; update it with the package that ships that provider.                           |
| Not installed, or method unknown | Skipped, with the install hint or a note that SASE will not guess an update command.    |

Anything already at its latest known version is reported as an explicit
`already up to date` skip rather than being reinstalled. Skips carry the provider's
canonical docs URL where one is known.

`install` takes CLI names and installs each from the install script or npm package its
provider declares. For a script CLI, SASE fetches the script itself over HTTPS into a
`0o600` temp file with a timeout and a size cap, refuses non-HTTPS URLs and redirects
off HTTPS, computes its SHA-256, and shows the URL, digest, byte count, env overlay,
target directory, and the exact `bash <tmpfile>` command before running it — never
`curl | bash`, and never through a shell. For an npm CLI, SASE checks that `npm` is on
`PATH` and that the global root is writable (otherwise the CLI is skipped with the exact
command to run under an npm setup owned by your user), then shows the package, the exact
`npm install -g <package>` command, and the targeted global bin directory with its
on-PATH status before running it — never with `sudo`. Running an installer always needs
confirmation: pass `-y/--yes` or answer the interactive prompt. `-n/--dry-run` prints
the plan, digest included, and executes nothing. An already-installed CLI is skipped
unless you pass `-f/--force`, and a CLI whose provider declares neither a script nor an
npm package is skipped with the manual command to run instead. After a successful
install SASE re-probes the version, reports where the binary landed and whether that
directory is on `PATH`, and prints the exact export line to add when it is not. **SASE
never edits your shell startup files.**

Runs from `sase agent-cli install` and `sase agent-cli update` are journaled with the
same bounded history used by sase's TUI, `,U`, and `,E` at
`~/.sase/logs/agent_cli_updates.jsonl`. Set `SASE_AGENT_CLI_UPDATE_JOURNAL_MAX_BYTES` to
override that file's maximum size; runs where no command reaches a terminal outcome are
not recorded.

This command manages the provider CLIs only. Use [`sase update`](../cli/update.md) to
upgrade SASE itself and its plugins.

The same inventory is available inside sase's TUI, as the **Agent CLIs** section of the
SASE Admin Center's Updates tab, which adds marked multi-select updates, inline installs
for missing CLIs with `*` mark-all, and confirmation previews. See the
[Updates tab](../tui/updates-tab.md#updates-tab-1) for that surface.

## Related

- [Providers and models](index.md) — provider integrations and model routing.
- [Instruction bundles](../memory/instruction-bundles.md) — how providers receive
  instructions.

## `sase agent-cli`

`sase agent-cli` inventories the supported coding-agent CLIs, installs the ones whose
provider declares an install script, and updates the ones whose install method can be
identified safely. With no subcommand, it defaults to `sase agent-cli list`. See
[Agent providers](#inventory-and-updates) for the per-install-method update behavior.

<a id="cli-options-49"></a> Moved to [sase agent-cli](agent-clis.md#sase-agent-cli).

<a id="command-behavior-33"></a> Moved to
[Installing & Authenticating Agent Providers](agent-clis.md#command-behavior-33).

## Command behavior {#command-behavior-33}

`-o/--offline` uses only cached latest-version data and never contacts the network;
`-r/--refresh` bypasses that cache.
