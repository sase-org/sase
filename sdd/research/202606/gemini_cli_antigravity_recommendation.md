---
create_time: 2026-06-19
updated_time: 2026-06-19
status: research
---

# Gemini CLI to Antigravity CLI: Failure Analysis and Recommendation

## Research Request

Confirm whether recent Gemini CLI failures are caused by Google's move to
Antigravity, determine whether Antigravity has a CLI replacement, and recommend
the next action for SASE.

## Bottom Line

The hypothesis is correct, with one important qualification: the `gemini`
binary is still installed, but the personal OAuth / Gemini Code Assist for
individuals backend path is now unsupported.

Google announced on 2026-05-19 that Gemini CLI would stop serving requests for
free Gemini Code Assist for individuals and Google AI Pro/Ultra users on
2026-06-18. Today is 2026-06-19, and local SASE/Gemini failures now reproduce
that exact server-side rejection: `IneligibleTierError` with
`UNSUPPORTED_CLIENT`, `tierId: free-tier`, and a message telling the user to
migrate to Antigravity.

Antigravity does have a CLI. The binary is `agy`, not `antigravity` and not
`ag`. It is not installed on this machine. SASE also does not currently have an
Antigravity provider, so `SASE_GEMINI_PATH=agy` is not the right fix.

Recommended next action: keep SASE defaulting to Codex/Claude for now, install
and validate `agy`, then add a first-class SASE `antigravity`/`agy` provider.
Keep the old Gemini provider as a limited API-key/enterprise fallback, but make
its `UNSUPPORTED_CLIENT` failure explicit and non-retriable.

## Evidence Reviewed

Consolidated from:

- `~/.sase/chats/202606/sase-ace_run-260619_135959.md`
- `~/.sase/chats/202606/sase-ace_run-260619_140009.md`
- `sdd/research/202606/gemini_cli_antigravity_transition.md`
- `sdd/research/202606/gemini_cli_antigravity_migration.md`

This consolidation also re-checked the local CLI state, SASE provider code,
archived failure bundle, and current Google sources on 2026-06-19.

## Local Failure Evidence

Current local probes:

| Probe | Result |
| --- | --- |
| `command -v gemini` | `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/gemini` |
| `gemini --version` | `0.35.0` |
| `command -v agy` | not found |
| `command -v antigravity` | not found |
| `~/.gemini/settings.json` auth type | `oauth-personal` |
| `sase doctor -C llm.default -v` | OK, default provider is `codex`; auth is not probed |

Direct reproduction with SASE's current invocation shape:

```bash
printf 'Respond with exactly OK.\n' |
  gemini --output-format stream-json --yolo --model gemini-3-flash-preview
```

Result: exit code `1`; the CLI loads cached credentials, then fails before a
model response with:

```text
IneligibleTierError: This client is no longer supported for Gemini Code Assist
for individuals. To continue using Gemini, please migrate to the Antigravity
suite of products: https://antigravity.google.
reasonCode: 'UNSUPPORTED_CLIENT'
tierId: 'free-tier'
tierName: 'Gemini Code Assist for individuals'
```

Archived SASE evidence matches the reproduction:

- Bundle: `/home/bryan/.sase/dismissed_bundles/202606/20260619123635.json`
- Agent: `01c.gem`
- Status: `FAILED`
- Start: `2026-06-19T12:36:35`
- Provider/model: `gemini` / `gemini-3.1-pro-preview`
- Command: `gemini --output-format stream-json --yolo --model gemini-3.1-pro-preview`
- Error: same `IneligibleTierError` / `UNSUPPORTED_CLIENT` / Antigravity migration message

This is not a missing-binary problem, not an expired-login problem, and not a
normal transient API error. The credentials load; the service rejects this
client/tier.

## Upstream Confirmation

Google's 2026-05-19 Developers Blog announcement says Antigravity CLI is
available to everyone and that on 2026-06-18 Gemini CLI and Gemini Code Assist
IDE extensions stop serving requests for Google AI Pro/Ultra and free Gemini
Code Assist for individuals users. The same announcement says enterprise users
with Gemini Code Assist Standard/Enterprise, Google Cloud-backed GitHub access,
and paid Gemini/Gemini Enterprise Agent Platform API keys remain supported.

The official Antigravity codelab identifies the replacement binary as `agy` and
shows the macOS/Linux installer:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

It also documents core non-interactive usage:

```bash
agy -p "What is the gcloud command to deploy to Cloud Run"
agy models
agy --model "Gemini 3.5 Flash (Low)"
agy --dangerously-skip-permissions
```

The prior agents' work was directionally correct. The strongest correction is
precision: Gemini CLI is not universally dead. It is dead for this local
personal-OAuth/free-tier path. API-key or enterprise Gemini paths may still work
for some models, but they are not the supported consumer replacement and do not
solve SASE's current OAuth-backed failures.

## SASE Impact

SASE still has a built-in Gemini provider:

- `pyproject.toml`: `gemini = "sase.llm_provider.gemini:GeminiProvider"`
- `src/sase/llm_provider/gemini.py`: uses `SASE_GEMINI_PATH` or `gemini`
- Invocation: `gemini --output-format stream-json --yolo --model <model>`
- Prompt delivery: writes the full prompt to stdin
- Parser: `src/sase/llm_provider/_subprocess_gemini.py` parses Gemini-specific
  `stream-json` events and usage
- Doctor hint: `src/sase/doctor/checks_providers.py` still recommends
  `npm install -g @google/gemini-cli`

Default SASE runs in this workspace are insulated because the selected provider
is `codex`. The breakage happens when a prompt or workflow explicitly selects
Gemini, such as `%model:gemini-3.1-pro-preview`, or when a fanout includes
Gemini.

`sase doctor` will not catch this class of failure today. It is intentionally
read-only and does not call provider APIs, so it can report "executable found"
while real Gemini invocations fail during auth/setup.

## Why `SASE_GEMINI_PATH=agy` Is Not Enough

Treat `agy` as a different provider, not a binary alias.

| Concern | Current Gemini provider | Antigravity CLI evidence |
| --- | --- | --- |
| Binary | `gemini` | `agy` |
| Prompt | stdin | documented `-p` prompt flag |
| Model flag | `--model <provider-id>` | `--model "<display name>"`; `agy models` lists supported names |
| Permissions | `--yolo` | `--dangerously-skip-permissions` / permission modes |
| Output | `--output-format stream-json` | no verified Gemini-compatible `stream-json` contract in the official sources checked |
| Parser | Gemini event schema | unknown; likely needs a new parser or plain-text first pass |
| Config/auth | `~/.gemini/settings.json` and Gemini CLI auth | Antigravity CLI onboarding/config under Antigravity |

The blocking technical question is output format. SASE's current Gemini provider
depends on streaming JSON for live output, tool-call artifacts, and usage data.
Before implementation, run an `agy --help`/smoke-test spike and verify whether
`agy` has a stable JSON or streamed event mode. If not, the first SASE
Antigravity provider should start with plain text output and explicitly mark
usage/tool-call fidelity as incomplete.

## Recommendation

1. Keep `llm_provider.provider=codex` as the default and avoid Gemini-selected
   runs unless you intentionally switch Gemini to API-key/enterprise auth.

2. Install and validate Antigravity CLI:

   ```bash
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   agy --version
   agy
   agy models
   agy -p "Respond with exactly OK."
   agy --help
   ```

3. During the spike, answer these questions before coding:

   - Does `agy` support machine-readable output, especially a streamed mode?
   - What exact non-interactive flags work with model selection and permissions?
   - How are long, multi-line prompts passed safely if `-p` is required?
   - What model identifiers should SASE expose: display names from `agy models`
     or SASE-friendly aliases mapped to those display names?

4. Add a new first-class SASE provider rather than mutating
   `SASE_GEMINI_PATH`:

   - Provider id: `antigravity` or `agy`
   - Binary env override: `SASE_AGY_PATH` or `SASE_ANTIGRAVITY_PATH`
   - Initial invocation: verified `agy -p ...` plus model/permission flags
   - Parser: plain text first unless a stable JSON/stream mode exists
   - Doctor: check `agy --version`; reserve auth/model smoke tests for deep mode

5. Improve the old Gemini provider's error handling:

   - Detect `UNSUPPORTED_CLIENT` / `IneligibleTierError`
   - Explain that personal OAuth / Gemini Code Assist for individuals stopped
     working after 2026-06-18
   - Suggest Antigravity CLI, API-key auth, or enterprise Gemini auth
   - Do not retry this error as if it were transient

## Decision

Open an implementation task to add Antigravity CLI support to SASE. The old
Gemini provider should remain as an explicit API-key/enterprise fallback, but it
should no longer be treated as a healthy individual-account runtime.

## Sources

- Google Developers Blog: <https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/>
- Official Antigravity CLI codelab: <https://codelabs.developers.google.com/antigravity-cli-hands-on>
- Antigravity CLI docs: <https://antigravity.google/docs/cli-getting-started>
- Antigravity migration docs: <https://antigravity.google/docs/gcli-migration>
- Gemini CLI GitHub repository/discussion: <https://github.com/google-gemini/gemini-cli/discussions/27274>
