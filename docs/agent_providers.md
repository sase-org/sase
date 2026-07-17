# Installing & Authenticating Agent Providers

SASE normally orchestrates an existing coding-agent CLI; the exception is the bundled `fakey` testing provider. You need
**at least one** supported real provider CLI installed **and authenticated** for production work. This page collects the
install command, the authentication command, and a link to each vendor's canonical documentation for every provider SASE
currently supports. Claude Code, Codex CLI, and Qwen Code install via `npm` (so they need `node` and `npm` on your
`PATH`); OpenCode and the Antigravity CLI use their own install methods, shown in their sections below.

`sase doctor` — specifically `sase doctor -C llm.auth -v` — is the authoritative readiness check. It prints the same
per-provider install and auth hints documented here, so if this page and `sase doctor` ever disagree, trust the doctor
output and open an issue. Vendor docs may list additional installer and account options; the snippets below
intentionally match SASE's doctor hints.

## Claude Code

Anthropic's Claude Code CLI (`claude`). This is SASE's highest-priority autodetect provider.

### Install

```bash
npm install -g @anthropic-ai/claude-code
```

### Authenticate

SASE doctor hint: run `claude` and complete the login flow.

Alternatively, Claude Code honors API-key / token variables such as `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and
`CLAUDE_CODE_OAUTH_TOKEN` — see the canonical docs for the full, current list.

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

OpenCode can also read provider API keys from the environment (for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`OPENROUTER_API_KEY`, and other `*_API_KEY` variables) — its canonical docs list the current set.

Canonical docs: <https://opencode.ai/docs>

## Qwen Code

Alibaba's Qwen Code CLI (`qwen`).

### Install

```bash
npm install -g @qwen-code/qwen-code
```

### Authenticate

SASE doctor hint: run `qwen` and complete the login flow.

Qwen Code can also use API-key access through variables such as `DASHSCOPE_API_KEY`, `QWEN_API_KEY`, or
`OPENROUTER_API_KEY` — see the canonical docs for the current list.

Canonical docs: <https://github.com/QwenLM/qwen-code>

## Antigravity CLI

Google's Antigravity CLI (`agy`). There is no separate "Gemini CLI" provider in SASE; `GEMINI.md` exists only because
Antigravity reads it for workspace context.

### Install

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

### Authenticate

SASE doctor hint: run `agy` and complete the login/trust onboarding.

Alternatively, Antigravity honors `GEMINI_API_KEY` and `GOOGLE_API_KEY` — see the canonical docs for details.

Canonical docs: <https://antigravity.google/docs/cli-install>

## Fakey Testing Provider

The deterministic `fakey` CLI is bundled with SASE for launch, failure, retry, and UI testing. It requires no separate
installation or authentication and is deliberately placed last in provider autodetection. Select it explicitly with a
model such as `%model:fakey-large` or `llm_provider.provider: fakey`; do not use it for production coding work.

For demos and hermetic end-to-end tests, `SASE_LLM_EXEC_PROVIDER=fakey` dispatches through fakey while preserving the
requested provider/model in display metadata. Run artifacts record the dispatched provider as `exec_llm_provider`.

See the [fakey reference](fakey.md) for scenarios and environment controls.

## Verify

After installing and authenticating at least one provider, confirm SASE can find and use it:

```bash
sase doctor -C llm.auth -v
```

Expect the provider to report ready. `sase doctor` is read-only and does not call provider APIs, so it verifies that the
CLI is on your `PATH` and that local auth evidence exists — it cannot confirm your token is still valid. If the check
reports a missing executable or an authentication gap, re-run the relevant install/auth step above and check again.

If a provider CLI lives at a non-standard path, point SASE at it with the provider's `SASE_<PROVIDER>_PATH` override
environment variable — `SASE_CLAUDE_PATH`, `SASE_CODEX_PATH`, `SASE_OPENCODE_PATH`, `SASE_QWEN_PATH`, `SASE_AGY_PATH`,
or `SASE_FAKEY_PATH`. For deeper integration details (model mapping, per-provider environment variables, retry/fallback
behavior), see the [LLM provider reference](llms.md).
