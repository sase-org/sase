# Installing & Authenticating Agent Providers

SASE normally orchestrates an existing coding-agent CLI; the exception is the bundled
`fakey` testing provider. You need **at least one** supported real provider CLI
installed **and authenticated** for production work. This page collects the install
command, the authentication command, and a link to each vendor's canonical documentation
for every provider SASE currently supports. Claude Code, Codex CLI, and Qwen Code
install via `npm` (so they need `node` and `npm` on your `PATH`); OpenCode and the
Antigravity CLI use their own install methods, shown in their sections below.

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
`SASE_CODEX_PATH`, `SASE_OPENCODE_PATH`, `SASE_QWEN_PATH`, `SASE_AGY_PATH`, or
`SASE_FAKEY_PATH`. For deeper integration details (model mapping, per-provider
environment variables, retry/fallback behavior), see the
[LLM provider reference](llms.md).

## Inventory and Updates

`sase agent-cli` is the inventory and update surface for independently manageable
provider CLIs on this machine. Internal or bundled providers can opt out when they are
not separately installed or updated. A bare `sase agent-cli` means
`sase agent-cli list`.

```bash
sase agent-cli list            # manageable provider CLIs, versions, and install methods
sase agent-cli list -v         # add resolved executable paths, docs URLs, and probe errors
sase agent-cli update codex    # update one CLI
sase agent-cli update -a -n    # preview every planned command without running anything
```

`list` shows each CLI's resolved binary, installed version, latest known version,
install method, and an `↑` marker when an update is available. A CLI that is not
installed shows its install hint instead. The footer summarizes how many of the
supported CLIs are installed and whether any updates are known. Latest versions come
from the npm registry and are cached: `-o/--offline` uses only the cache and never
contacts the network, while `-r/--refresh` bypasses the cache. `-j/--json` emits a
stable machine-readable envelope.

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
| Self-managed with a self-update  | Runs the provider's own declared update command.                                        |
| Homebrew                         | Skipped as manual, with the `brew upgrade <package>` command to run.                    |
| Bundled visible provider         | Skipped; update it with the package that ships that provider.                           |
| Not installed, or method unknown | Skipped, with the install hint or a note that SASE will not guess an update command.    |

Anything already at its latest known version is reported as an explicit
`already up to date` skip rather than being reinstalled. Skips carry the provider's
canonical docs URL where one is known.

Runs from `sase agent-cli update` are journaled with the same bounded history used by
ACE and `,U` at `~/.sase/logs/agent_cli_updates.jsonl`. Set
`SASE_AGENT_CLI_UPDATE_JOURNAL_MAX_BYTES` to override that file's maximum size; runs
where no command reaches a terminal outcome are not recorded.

This command manages the provider CLIs only. Use [`sase update`](cli.md) to upgrade SASE
itself and its plugins.

The same inventory is available inside ACE on the SASE Admin Center's **Updates → Agent
CLIs** sub-tab, which adds marked multi-select updates and confirmation previews. See
the [Updates tab](ace.md#updates-tab) for that surface.
