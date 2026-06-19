---
create_time: 2026-06-19
updated_time: 2026-06-19
status: research
---

# Gemini CLI / Antigravity Transition Research

## Research Request

Gemini CLI has been failing recently. Confirm whether this is because Gemini CLI is being deprecated in favor of
Antigravity, determine whether Antigravity has a CLI that should replace it, and recommend the next action for SASE.

## Bottom Line

Yes, the recent SASE Gemini failures are explained by Google's Gemini CLI to Antigravity transition, but the precise
failure is narrower than "the `gemini` binary is dead."

The observed SASE failure path uses Gemini CLI with cached personal OAuth / Gemini Code Assist for individuals
credentials. That path is now unsupported. Google announced on 2026-05-19 that, on 2026-06-18, Gemini CLI and Gemini Code
Assist IDE extensions would stop serving requests for Google AI Pro/Ultra and free Gemini Code Assist for individuals
users, and that users should transition to Antigravity CLI / Antigravity 2.0.

Antigravity does have a CLI. The command is `agy`, not `antigravity` and not `ag`. It is not installed on this machine.
SASE also does not currently have an Antigravity provider, so `agy` is not a drop-in replacement for the current
`gemini` provider.

Recommended next action: install and validate `agy`, then add a first-class SASE `antigravity` / `agy` LLM provider
instead of repointing `SASE_GEMINI_PATH` at `agy`. In the meantime, keep SASE defaulting to Codex/Claude and avoid
launching `%model:gemini/...` agents unless you explicitly configure Gemini CLI for API-key or enterprise auth and use a
model with available quota.

## Local Evidence

### Installed CLIs

Local checks on 2026-06-19:

| Probe | Result |
| --- | --- |
| `command -v gemini` | `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/gemini` |
| `gemini --version` | `0.35.0` |
| `npm view @google/gemini-cli version` | `0.47.0` latest |
| `command -v agy` | not found |
| `command -v antigravity` | not found |
| `command -v ag` | `/usr/bin/ag`, which is The Silver Searcher, not Antigravity |

Gemini is installed but old. Updating may still be worthwhile if continuing to use API-key/enterprise Gemini, but it
does not address the personal-OAuth deprecation by itself.

### Archived SASE Failure

SASE has a recent archived Gemini failure:

- Bundle: `/home/bryan/.sase/dismissed_bundles/202606/20260619123635.json`
- Agent: `01c.gem`
- Status: `FAILED`
- Start: `2026-06-19T12:36:35`
- Provider/model: `gemini` / `gemini-3.1-pro-preview`
- Command in traceback: `gemini --output-format stream-json --yolo --model gemini-3.1-pro-preview`
- Error class: `IneligibleTierError`
- Error reason: `UNSUPPORTED_CLIENT`
- Tier: `Gemini Code Assist for individuals`
- User-facing message: the client is no longer supported and the user should migrate to Antigravity.

I reproduced the same failure directly with the SASE invocation shape:

```bash
printf 'Respond with exactly OK.\n' |
  gemini --output-format stream-json --yolo --model gemini-3-flash-preview
```

That exited `1` before a model response and printed the same unsupported-client / Antigravity migration error.

### Auth Mode Matters

`~/.gemini/settings.json` has:

```text
security.auth.selectedType = oauth-personal
```

That matches the failed tier. A separate isolated test with a temporary `HOME` and the existing `GEMINI_API_KEY` reached
the Gemini API successfully for `gemini-2.5-flash`:

```bash
HOME=$(mktemp -d) GEMINI_API_KEY=... gemini --output-format stream-json --yolo --model gemini-2.5-flash
```

Result: exit `0`, assistant response `OK`.

The same isolated API-key setup for `gemini-3.1-pro-preview` did not fail with `UNSUPPORTED_CLIENT`; it reached the API
and failed with quota exhaustion for `gemini-3.1-pro`. That means there are two separate problems:

1. Personal OAuth / Code Assist for individuals is now blocked for Gemini CLI.
2. Some Gemini models, especially `gemini-3.1-pro-preview`, may still be unavailable or quota-exhausted under the API-key
   route.

## Upstream Evidence

Google's 2026-05-19 announcement, ["An important update: Transitioning Gemini CLI to Antigravity CLI"](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/),
says Google is unifying Gemini CLI work into Google Antigravity and introducing Antigravity CLI. It says Antigravity CLI
is available immediately and that, on 2026-06-18, Gemini CLI stops serving requests for Google AI Pro/Ultra users and
free Gemini Code Assist for individuals users. It also says enterprise access remains unchanged for Gemini Code Assist
Standard/Enterprise and Google Cloud-backed GitHub use.

The official Antigravity CLI codelab says installation on macOS/Linux is:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

It also says the installed binary is `agy`, and shows:

```bash
agy --version
agy
agy -p "What is the gcloud command to deploy to Cloud Run"
agy models
agy --model "Gemini 3.5 Flash (Low)"
```

Sources:

- Google Developers Blog transition announcement:
  <https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/>
- Google Codelab, "Hands-on with Antigravity CLI":
  <https://codelabs.developers.google.com/antigravity-cli-hands-on>
- Antigravity CLI GitHub repository:
  <https://github.com/google-antigravity/antigravity-cli>
- Gemini CLI GitHub repository:
  <https://github.com/google-gemini/gemini-cli>

## SASE Impact

SASE still has a built-in Gemini provider:

- Entry point: `pyproject.toml`, `gemini = "sase.llm_provider.gemini:GeminiProvider"`
- Provider binary: `src/sase/llm_provider/gemini.py` uses `SASE_GEMINI_PATH` or `gemini`
- Invocation shape: `gemini --output-format stream-json --yolo --model <model>`
- Default model: `gemini-3-flash-preview`
- Known models include `gemini-3.1-pro-preview`
- Doctor hint still recommends `npm install -g @google/gemini-cli`

SASE currently defaults to Codex in this environment:

```text
sase doctor -C llm.default -v
selected provider: codex
selection source: config (`llm_provider.provider=codex`)
```

So normal default runs are insulated. The breakage happens when a prompt or workflow explicitly selects Gemini, such as
`%model:gemini-3.1-pro-preview` or a multi-model fanout that includes Gemini.

## Why `SASE_GEMINI_PATH=agy` Is Not The Right Fix

Do not point the existing Gemini provider at `agy` without a compatibility layer.

Gemini CLI and Antigravity CLI have different CLI contracts:

- Gemini supports `--output-format stream-json`; SASE parses Gemini stream-json events.
- Antigravity docs emphasize TUI usage plus non-interactive `agy -p`; they do not document the same stream-json event
  contract.
- Gemini uses `--yolo`; Antigravity uses different permission language such as `--dangerously-skip-permissions`.
- Antigravity model names are display names such as `Gemini 3.5 Flash (Low)`, not the same provider-local strings SASE
  currently exposes.
- Antigravity is a new shared-agent-harness product with its own config, auth, permissions, logs, and session model.

Treat `agy` as a new provider, not as a binary alias for `gemini`.

## Recommendation

1. Keep `llm_provider.provider=codex` as the default until SASE has a real Antigravity provider.

2. Install Antigravity CLI and validate it manually:

   ```bash
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   agy --version
   agy
   agy models
   agy -p "Respond with exactly OK."
   ```

3. Add a new SASE provider for `agy`.

   First implementation should be conservative:

   - Provider name: `antigravity` or `agy`
   - Binary env override: `SASE_ANTIGRAVITY_PATH` or `SASE_AGY_PATH`
   - Initial invocation: `agy -p <prompt>` plus the closest permission/model flags verified by `agy --help`
   - Output parser: plain text first, unless `agy` exposes a stable JSON/stream mode
   - Model metadata: populate from `agy models` or a small known-model list
   - Doctor check: verify `agy --version`, auth/onboarding state if detectable, and a short smoke test only in deep mode

4. Improve the old Gemini path rather than deleting it immediately.

   Gemini CLI can still work with API-key auth for at least `gemini-2.5-flash` in this environment. That makes it useful
   as a limited fallback, but SASE should surface the new failure clearly:

   - Detect `UNSUPPORTED_CLIENT` / `IneligibleTierError`.
   - Report that personal OAuth / Gemini Code Assist for individuals no longer works after 2026-06-18.
   - Suggest `agy` migration or API-key/enterprise Gemini auth.
   - Avoid retrying this error for 60/300/1800 seconds; it is not transient.

5. Update docs/config after `agy` support exists.

   Places to update:

   - `src/sase/doctor/checks_providers.py`
   - provider entry points in `pyproject.toml`
   - model picker/provider metadata
   - generated skills/provider tool labels
   - any docs that describe Gemini as a default or recommended external agent

## Decision

The next action should be an implementation task: add first-class Antigravity CLI support to SASE. Use Codex/Claude as
the default while that work is underway. If Gemini is needed before then, switch away from personal OAuth and use a
known-working API-key model such as `gemini-2.5-flash`, accepting that current pro-preview quota may still fail.
