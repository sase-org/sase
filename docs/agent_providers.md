# Installing & Authenticating Agent Providers

SASE normally orchestrates an existing coding-agent CLI; the exception is the bundled
`fakey` testing provider. You need **at least one** supported real provider CLI
installed **and authenticated** for production work. This page collects the install
command, the authentication command, and a link to each vendor's canonical documentation
for every provider SASE currently supports. Claude Code, Codex CLI, Qwen Code, and Grok
Build install via `npm` (so they need `node` and `npm` on your `PATH`); OpenCode, the
Antigravity CLI, and Muse Code use their own install methods, shown in their sections
below. Muse Code is the one provider SASE can install for you, with
[`sase agent-cli install muse`](#inventory-and-updates).

`sase doctor` — specifically `sase doctor -C llm.auth -v` — is the authoritative
readiness check. It prints the same per-provider install and auth hints documented here,
so if this page and `sase doctor` ever disagree, trust the doctor output and open an
issue. Vendor docs may list additional installer and account options; the snippets below
intentionally match SASE's doctor hints.

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

## OpenCode

The open-source OpenCode CLI (`opencode`).

### Install

```bash
install from https://opencode.ai/docs
```

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

Meta's Muse Code CLI (`muse`). Muse is **explicit-only**: SASE never auto-detects it,
because `muse` is a generic executable name. Select it with
`llm_provider.provider: muse`, `%model:muse/<model>`, or `SASE_MUSE_PATH`.

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

Canonical docs: <https://developer.meta.com/ai/resources/blog/build-with-muse-code/>

## Grok Build

xAI's Grok Build CLI (`grok`). SASE never auto-detects it, because the executable name
`grok` collides with `grok-dev` (a stale community CLI that also uses `~/.grok/`) and
with Homebrew's deprecated, unrelated `grok` regex tool. Select it explicitly with
`llm_provider.provider: grok`, `%model:grok/grok-4.6`, or `SASE_GROK_PATH`, or reach it
automatically whenever the `grok` CLI is installed: through the shipped
`@xsmall`/`@small`/`@medium` load-balanced pools, or as the last candidate in
`@xlarge`'s ordered fallback (behind Claude and Codex). If a `grok` on `PATH` does not
identify itself as Grok Build, `sase doctor` reports it as a distinct, actionable
finding rather than silently launching the wrong binary.

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

The `grok-4.6` model — the only model in the authenticated catalog — accepts only `low`,
`medium`, `high`, and `xhigh` for `--effort`. `%effort:none`, `%effort:minimal`, and
`%effort:max` raise a clean SASE error rather than a Grok process crash. The shipped
`@xlarge` alias carries `@max` on every fallback candidate, but that alias-borne effort
is best-effort, not explicit: when the fallback selects Grok (or Codex, which also has
no `max` level), `max` is logged and skipped and the CLI runs at its own default effort
instead of erroring.

### Usage is best-effort

Grok's `streaming-messages-json` output is a projection of its own internal usage
ledger. Subagent turns can set an internal "usage incomplete" flag that the projection
drops silently, and an interrupted turn can under-count. Text and tool records are
unaffected, and cost reporting (`total_cost_usd`) does work on the OAuth login path.

### Instruction double-load

Grok reads `AGENTS.md` natively, so SASE generates no `GROK.md` shim. Grok also
recognizes SASE's generated `CLAUDE.md` as project instructions and loads both files —
duplicating the same content. `[compat.claude] agents = false` does not suppress this.
SASE accepts the duplication for now rather than suppressing `CLAUDE.md` generation
under a Grok provider, which would break any human running `claude` in the same tree.

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

Canonical docs: <https://antigravity.google/docs/cli-install>

## Fakey Testing Provider

The deterministic `fakey` CLI is bundled with SASE for launch, failure, retry, and UI
testing. It requires no separate installation or authentication and is deliberately
placed last in provider autodetection. It is also hidden from the ACE model picker and
`%model` completion menu, so select it explicitly with a model such as
`%model:fakey-large` or `llm_provider.provider: fakey`; do not use it for production
coding work.

Because Fakey is bundled and internal, it is also absent from `sase agent-cli`
inventories and the Admin Center's **Updates → Agent CLIs** list. That management
visibility is separate from routing and diagnostics: explicit fakey selection, the
`fakey` console script, provider autodetection metadata, and `sase doctor` checks remain
supported.

For demos and hermetic end-to-end tests, `SASE_LLM_EXEC_PROVIDER=fakey` dispatches
through fakey while preserving the requested provider/model in display metadata. Run
artifacts record the dispatched provider as `exec_llm_provider`.

See the [fakey reference](fakey.md) for scenarios and environment controls.

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
`SASE_MUSE_PATH`, `SASE_GROK_PATH`, or `SASE_FAKEY_PATH`. For deeper integration details
(model mapping, per-provider environment variables, retry/fallback behavior), see the
[LLM provider reference](llms.md).

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

SASE only automates updates it can identify safely, and it never uses `sudo` and never
guesses an update command:

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

`install` takes CLI names and installs each from the install script its provider
declares. SASE fetches the script itself over HTTPS into a `0o600` temp file with a
timeout and a size cap, refuses non-HTTPS URLs and redirects off HTTPS, computes its
SHA-256, and shows the URL, digest, byte count, env overlay, target directory, and the
exact `bash <tmpfile>` command before running it — never `curl | bash`, and never
through a shell. Running a remote script always needs confirmation: pass `-y/--yes` or
answer the interactive prompt. `-n/--dry-run` prints the plan, digest included, and
executes nothing. An already-installed CLI is skipped unless you pass `-f/--force`, and
a CLI whose provider declares no install script is skipped with the manual command to
run instead. After a successful install SASE re-probes the version, reports where the
binary landed and whether that directory is on `PATH`, and prints the exact export line
to add when it is not. **SASE never edits your shell startup files.**

Runs from `sase agent-cli install` and `sase agent-cli update` are journaled with the
same bounded history used by ACE and `,U` at `~/.sase/logs/agent_cli_updates.jsonl`. Set
`SASE_AGENT_CLI_UPDATE_JOURNAL_MAX_BYTES` to override that file's maximum size; runs
where no command reaches a terminal outcome are not recorded.

This command manages the provider CLIs only. Use [`sase update`](cli.md) to upgrade SASE
itself and its plugins.

The same inventory is available inside ACE on the SASE Admin Center's **Updates → Agent
CLIs** sub-tab, which adds marked multi-select updates and confirmation previews. See
the [Updates tab](ace.md#updates-tab) for that surface.
