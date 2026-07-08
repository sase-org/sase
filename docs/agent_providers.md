# Installing & Authenticating Agent Providers

SASE orchestrates an existing coding-agent CLI; it does not ship, replace, or manage that CLI's own install and
authentication flow. You need **at least one** supported provider CLI installed **and authenticated** before you launch
an agent. This page collects the install command, the authentication command, and a link to each vendor's canonical
documentation for every provider SASE currently supports.

`sase doctor` — specifically `sase doctor -C llm.auth -v` — is the authoritative readiness check. It prints the same
per-provider install and auth hints documented here, so if this page and `sase doctor` ever disagree, trust the doctor
output and open an issue.

## Claude Code

Anthropic's Claude Code CLI (`claude`). This is SASE's highest-priority autodetect provider.

### Install

```bash
npm install -g @anthropic-ai/claude-code
```

Claude Code is distributed via npm, so it needs `node` / `npm` on your `PATH`.

### Authenticate

run `claude` and complete the login flow

As an alternative to interactive login, Claude Code honors API-key / token environment variables such as
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and `CLAUDE_CODE_OAUTH_TOKEN`. See the canonical docs for the full, current
list.

Canonical docs: <https://docs.claude.com/en/docs/claude-code>

## Codex CLI

OpenAI's Codex CLI (`codex`).

### Install

```bash
npm install -g @openai/codex
```

Codex is distributed via npm, so it needs `node` / `npm` on your `PATH`.

### Authenticate

```bash
codex login
```

As an alternative to interactive login, Codex honors `OPENAI_API_KEY`. See the canonical docs for details.

Canonical docs: <https://developers.openai.com/codex/cli>

## OpenCode

The open-source OpenCode CLI (`opencode`).

### Install

OpenCode is not distributed via npm through SASE's hint; install it with one of the methods on its canonical docs page
(npm, Homebrew, the install script, and more are documented there). The `sase doctor` install hint is literally
`install from https://opencode.ai/docs`.

### Authenticate

```bash
opencode auth login
```

OpenCode can also read provider API keys from the environment (for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, and other `*_API_KEY` variables). Its canonical docs list the current set and explain
provider/model configuration.

Canonical docs: <https://opencode.ai/docs>

## Qwen Code

Alibaba's Qwen Code CLI (`qwen`).

### Install

```bash
npm install -g @qwen-code/qwen-code
```

Qwen Code is distributed via npm, so it needs `node` / `npm` on your `PATH`.

### Authenticate

run `qwen` and complete the login flow

The Qwen OAuth free tier was discontinued on 2026-04-15. Configure API-key access (for example `DASHSCOPE_API_KEY`,
`QWEN_API_KEY`, `OPENROUTER_API_KEY`, or another Qwen-supported provider) through Qwen Code's own auth flow rather than
relying on the retired OAuth free tier. See the canonical docs for the current list.

Canonical docs: <https://github.com/QwenLM/qwen-code>

## Antigravity CLI

Google's Antigravity CLI (`agy`), the replacement for the retired consumer Gemini CLI. There is no separate "Gemini CLI"
provider in SASE; `GEMINI.md` exists only because Antigravity reads it for workspace context.

### Install

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Antigravity is installed via its own installer script, not npm.

### Authenticate

run `agy` and complete the login/trust onboarding

As an alternative to interactive login, Antigravity honors `GEMINI_API_KEY` and `GOOGLE_API_KEY`. See the canonical docs
for details.

Canonical docs: <https://antigravity.google/docs/cli-install>

## Verify

After installing and authenticating at least one provider, confirm SASE can find and use it:

```bash
sase doctor -C llm.auth -v
```

Expect the provider to report ready. `sase doctor` is read-only and does not call provider APIs, so it verifies that the
CLI is on your `PATH` and that local auth evidence exists — it cannot confirm your token is still valid. If the check
reports a missing executable or an authentication gap, re-run the relevant install/auth step above and check again.

If a provider CLI lives at a non-standard path, point SASE at it with the provider's `SASE_<PROVIDER>_PATH` override
environment variable — `SASE_CLAUDE_PATH`, `SASE_CODEX_PATH`, `SASE_OPENCODE_PATH`, `SASE_QWEN_PATH`, or
`SASE_AGY_PATH`. For deeper integration details (model mapping, per-provider environment variables, retry/fallback
behavior), see the [LLM provider reference](llms.md).
