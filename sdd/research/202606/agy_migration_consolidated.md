---
create_time: 2026-06-19
updated_time: 2026-06-19
status: research
---

# Antigravity (`agy`) Migration Research

## Research Request

Understand the work required to migrate SASE from Gemini CLI (`gemini`) to
Antigravity CLI (`agy`), remove Gemini CLI completely, eliminate remaining
Gemini CLI references, and give `agy` as complete a SASE integration as the
current CLI supports. End with a recommended migration strategy.

This note consolidates and verifies:

- `~/.sase/chats/202606/sase-ace_run-260619_155327.md`
- `~/.sase/chats/202606/sase-ace_run-260619_155330.md`
- `sdd/research/202606/gemini_to_agy_migration.md`
- `sdd/research/202606/agy_full_support_migration_research.md`

## Bottom Line

This is a real provider migration, not a binary rename.

The current SASE Gemini support is deep: provider entry point, provider class,
Gemini-specific stream parser, Gemini tool-call normalizer, generated skill
paths, retry config, doctor hints, TUI styling, thinking-log parsing, docs,
tests, xprompts, and generic utilities that still carry Gemini names.

`agy` is installed locally and works for noninteractive print mode, but
`agy 1.0.10` does not expose a documented or help-listed equivalent to
Gemini CLI's `--output-format stream-json`. That makes full parity impossible
in the first pass unless a hidden/stable machine-readable contract is found.
The practical v1 is a first-class `agy` provider with plain stdout capture,
model aliases, generated skill support, doctor checks, and clean UI/config/docs.
Tool-call artifacts, usage accounting, and thinking extraction should be treated
as fast-follow work gated on an upstream `agy` event/log contract.

The largest product decision is what "ZERO remaining references" means. Removing
Gemini CLI/provider/runtime support from active SASE is feasible. Literal
repo-wide zero text matches for `gemini` is much larger and conflicts with
Antigravity-owned facts: official global Antigravity paths are under
`~/.gemini/antigravity-cli`, Antigravity still reads `GEMINI.md` for migration
compatibility, and model display names returned by `agy models` include
`Gemini`. Historical SDD records and protected memory also contain references.

## Verification Corrections From Prior Notes

The two prior notes were directionally aligned, but several points needed
resolution:

- `agy` is installed locally: `/home/bryan/.local/bin/agy`, version `1.0.10`.
- A direct captured subprocess smoke test works:
  `agy --print-timeout 30s --model "Gemini 3.5 Flash (Low)" --dangerously-skip-permissions -p "Respond with exactly OK."`
  returned `OK` with exit code 0.
- Therefore PTY wrapping is not proven necessary for print mode on this
  machine. Keep PTY or output-nonempty retry as a fallback to test in CI-like
  environments, but do not make it a hard assumption.
- `--print` is not stdin mode. `printf ... | agy --print` fails with
  `flag needs an argument: -print`. SASE must pass the prompt as an argument or
  discover a prompt-file/stdin mechanism.
- `agy --help` does not list `--output-format`, `--json`, `--cwd`, `inspect`, or
  any stream event mode.
- `agy inspect` is not a help-listed subcommand in 1.0.10; running it in this
  headless shell produced a TTY error rather than useful inspection output.
- The official Antigravity global generated-skill path is
  `~/.gemini/antigravity-cli/skills/`. Workspace skills are `.agents/skills/`.
  SASE's current generator writes global/home targets, so the primary provider
  hook should return `.gemini/antigravity-cli`; workspace `.agents/skills`
  support is separate follow-up behavior.
- The sibling Rust core path cited by one prior note could not be verified in
  this workspace because `../sase-core/sase-core_11` is empty. Check any real
  core checkout separately before planning a Rust binding change.

## External Facts

Google's 2026-05-19 transition announcement says Antigravity CLI is the new
terminal experience in the Antigravity platform. It explicitly says there is
not 1:1 feature parity immediately, but Antigravity CLI keeps the critical
Gemini CLI constructs: Agent Skills, Hooks, Subagents, and Extensions, with
Extensions becoming Antigravity plugins.

The consumer deadline matters for SASE: starting 2026-06-18, Gemini CLI and
Gemini Code Assist IDE extensions stopped serving requests for Google AI
Pro/Ultra and free Gemini Code Assist for individuals users. Enterprise and
API-key-backed paths remain supported, but they are not the replacement for
SASE's local personal-OAuth Gemini failures.

Official Antigravity CLI docs confirm:

- macOS/Linux installer: `curl -fsSL https://antigravity.google/cli/install.sh | bash`
- installed binary path: `~/.local/bin/agy`
- plugin import from legacy extensions: `agy plugin import gemini`
- global skills: `~/.gemini/antigravity-cli/skills/`
- workspace skills: `.agents/skills/`
- plugin directories: `~/.gemini/antigravity-cli/plugins/<plugin_name>/`
- context compatibility: workspace `GEMINI.md` and `AGENTS.md`; global
  `~/.gemini/GEMINI.md`
- workspace MCP: `.agents/mcp_config.json`
- global MCP docs conflict: the migration page says
  `~/.gemini/config/mcp_config.json`; the plugins page says
  `~/.gemini/antigravity-cli/mcp_config.json`. Verify against the installed CLI
  during implementation.

## Local `agy` Contract

Local checks on 2026-06-19:

| Probe | Result |
| --- | --- |
| `command -v agy` | `/home/bryan/.local/bin/agy` |
| `agy --version` | `1.0.10` |
| `command -v gemini` | `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/gemini` |
| `gemini --version` | `0.35.0` |
| `agy plugin list` | `No imported plugins.` |

`agy --help` confirms these useful flags and commands:

- `--print` / `-p` and `--prompt`: run one prompt noninteractively.
- `--prompt-interactive` / `-i`: seed an interactive session.
- `--model`: select the model for the session.
- `--print-timeout`: print-mode timeout, default `5m0s`.
- `--dangerously-skip-permissions`: auto-approve tool permission requests.
- `--sandbox`: enable terminal sandbox restrictions.
- `--add-dir`: add workspace directories, repeatable.
- `--continue` / `-c` and `--conversation`: resume conversations.
- `--log-file`: override the CLI log path.
- Subcommands: `models`, `plugin`/`plugins`, `install`, `update`,
  `changelog`, and `help`.

`agy models` currently returns these exact model display names:

| Exact model | Suggested SASE alias |
| --- | --- |
| `Gemini 3.5 Flash (Medium)` | `flash35m` |
| `Gemini 3.5 Flash (High)` | `flash35h` |
| `Gemini 3.5 Flash (Low)` | `flash35l` |
| `Gemini 3.1 Pro (Low)` | `pro31l` |
| `Gemini 3.1 Pro (High)` | `pro31h` |
| `Claude Sonnet 4.6 (Thinking)` | `sonnet46t` |
| `Claude Opus 4.6 (Thinking)` | `opus46t` |
| `GPT-OSS 120B (Medium)` | `gptoss120m` |

Default model recommendation: use `Gemini 3.5 Flash (High)` for closest
"strong Flash replacement" behavior, or `Gemini 3.5 Flash (Medium)` if SASE
wants a more conservative cost/latency default for background agents.

## Current SASE Gemini Surface

Current active-tree scan for case-insensitive `gemini` references found:

| Area | Matching files |
| --- | ---: |
| `src` | 44 |
| `tests` | 64 |
| `docs` | 13 |
| `config` | 1 |
| `pyproject.toml` | 1 |
| `README.md` | 1 |
| `xprompts` | 1 |
| `sdd` | 449 |
| `memory` | 2 |

The active migration work is concentrated in these surfaces:

- Provider registration: `pyproject.toml` has
  `gemini = "sase.llm_provider.gemini:GeminiProvider"`.
- Provider implementation:
  `src/sase/llm_provider/gemini.py`,
  `src/sase/llm_provider/_subprocess_gemini.py`, and
  `src/sase/llm_provider/_tool_call_gemini.py`.
- Re-export modules:
  `src/sase/llm_provider/_subprocess.py` and
  `src/sase/llm_provider/_tool_calls.py`.
- Metadata and detection:
  `src/sase/llm_provider/registry.py`, including provider color and
  `SASE_GEMINI_PATH` cache invalidation.
- Runtime behavior:
  Gemini invokes `gemini --output-format stream-json --yolo --model <model>`
  and sends the prompt on stdin.
- Config and schema:
  `src/sase/default_config.yml` contains Gemini retry settings and the shipped
  provider is `""` (autodetect); `config/sase.schema.json` still has stale
  Gemini examples/defaults.
- CLI and doctor:
  `src/sase/main/parser_init.py` hardcodes skill-init provider choices;
  `src/sase/doctor/checks_providers.py` recommends `@google/gemini-cli`.
- TUI:
  `src/sase/ace/tui/provider_styles.py`,
  prompt-panel helpers, and the Gemini API proxy thinking parser under
  `src/sase/ace/tui/thinking/`.
- Provider shims:
  root `GEMINI.md`, `tools/GEMINI.md`, `src/sase/ace/GEMINI.md`,
  `src/sase/amd/constants.py`, and `src/sase/memory/inventory.py`.
- Generated skills:
  `src/sase/xprompts/skills/sase_hg_commit.md` is currently scoped to
  `skill: [gemini]`.
- Generic but misnamed code:
  `src/sase/gemini_wrapper/` and `gemini_timer` in `src/sase/output.py` are
  used by non-Gemini paths and must be renamed rather than blindly deleted.
- Docs/tests/xprompts:
  `docs/llms.md`, `docs/configuration.md`, `docs/xprompt.md`, README,
  provider tests, parser tests, TUI tests, skill-target tests, and
  `xprompts/reads.md`.

One subtlety: active non-Gemini code also contains model names such as
`google/gemini-3-flash-preview` in the OpenCode provider. A literal
no-`gemini` active-tree rule would require deciding whether to remove those
unrelated model aliases too.

## Provider Work Required

Create a new `agy` provider rather than aliasing `gemini`:

- Provider ID: `agy`
- Display name: `Antigravity`
- Short name: `agy`
- Binary env var: `SASE_AGY_PATH`
- Default binary: `agy`
- Autodetect CLI: `agy`
- Autodetect priority: reuse Gemini's late fallback slot (`30`) unless the user
  wants Antigravity to outrank Qwen/OpenCode.
- Skill context:
  `provider_name=Antigravity`, `provider_tool_name=Antigravity CLI`.
- Skill deploy subpath:
  `llm_skill_deploy_subpath() -> ".gemini/antigravity-cli"` for global skills.

Initial invocation shape should follow verified local behavior:

```python
[
    agy_binary,
    "--print-timeout",
    timeout_as_go_duration,
    "--model",
    resolved_model_name,
    "--dangerously-skip-permissions",
    "--print",
    prompt,
]
```

SASE should set `cwd` in `subprocess.Popen` directly. Use `--add-dir <path>`
only when extra workspace roots are needed.

Implementation choices:

- Use existing plain streaming (`stream_process_output`) and live reply files
  for v1.
- Return `usage=None` or zeroed usage unless a stable usage source is found.
- Do not scrape human TUI output for tool calls.
- Add an `agy` parser module only if `--log-file`, conversation data, or future
  JSON output provides a stable schema.
- For long prompts, spike argument-length behavior and look for a prompt-file
  mechanism. If none exists, add a clear size guard and error message.
- Keep interrupt handling similar to OpenCode/Qwen: restart with accumulated
  context unless conversation resume can be made reliable.

## Removal And Cleanup Work

Remove Gemini CLI support:

- Delete the Gemini provider entry point and provider modules.
- Remove Gemini parser and tool-call re-exports.
- Remove `SASE_GEMINI_PATH`, Gemini autodetect, Gemini color/style entries,
  doctor install/auth hints, retry defaults, and schema/default examples.
- Remove Gemini-specific model aliases and `%model:gemini/...` examples.
- Remove root/tool/ACE `GEMINI.md` shims from active templates/inventory.
- Remove or replace Gemini API proxy thinking parsing. There is no confirmed
  `agy` equivalent today.
- Delete Gemini-specific tests; update cross-provider tests to use `agy` where
  appropriate.
- Regenerate generated skills after source changes with `sase skill init --force`
  and then deploy through the normal chezmoi path if needed.

Rename generic leftovers if active-tree zero references are required:

- `src/sase/gemini_wrapper/` -> a neutral package such as
  `sase.file_references` or `sase.prompt_references`.
- `GeminiCommandWrapper` compatibility exports should be removed, not aliased,
  if zero active references is mandatory.
- `gemini_timer` -> `agent_timer` or `provider_timer`; update all provider
  imports and tests.
- Update docs/tests that mention these old names.

Memory and generated-skill constraints:

- `memory/generated_skills.md` says generated skill files are generated from
  `src/sase/xprompts/skills/` and must not be hand-edited in deployed chezmoi
  locations.
- It also says `/sase_hg_commit` is Gemini-only today. If Gemini is removed,
  either delete that generated skill or retarget it to `agy` only after an
  Antigravity/hg smoke test.
- Project instructions require approval before modifying memory files directly.
  Use the audited memory workflow for `memory/generated_skills.md` and
  `memory/gotchas.md`.

## Parity Gap

| Capability | Gemini provider today | `agy` v1 likely support | Notes |
| --- | --- | --- | --- |
| Headless invocation | stdin + `stream-json` | `--print <prompt>` | Verified locally. |
| Model selection | `--model <id>` | `--model "<display name>"` | Verified locally. |
| Auto-approve | `--yolo` | `--dangerously-skip-permissions` | Verified in help and smoke test. |
| Live final text | parsed stream | plain stdout | Good enough for v1. |
| Tool-call artifacts | normalized JSONL | not available | Need stable upstream schema/logs. |
| Usage accounting | stream result stats | not available | Need stable upstream schema/logs. |
| Thinking extraction | Gemini proxy logs | not available | Remove until `agy` exposes equivalent. |
| Skills | global `.gemini` paths | global Antigravity path | Official path still contains `.gemini`. |
| Plugins | Gemini extensions | Antigravity plugins | `agy plugin import gemini` exists. |
| Conversation resume | provider reconstructs context | `--continue`/`--conversation` available | Needs spike before relying on it. |

## Zero-Reference Policy

Recommended policy for the implementation task:

1. No Gemini CLI provider, no `gemini` runtime ID, no `gemini` binary
   invocation, no `SASE_GEMINI_PATH`, no Gemini CLI install/auth docs, and no
   active compatibility aliases.
2. Permit narrow Antigravity-owned exceptions only where needed for correct
   behavior: `~/.gemini/antigravity-cli`, legacy import command examples, and
   exact model display names returned by `agy`.
3. Do not rewrite historical SDD records by default. They are evidence, not
   live product surface.
4. Do not modify protected memory files without approval.

Literal repo-wide zero `rg -i gemini` is possible only as a separate archival
cleanup. It would require deleting/redacting historical SDD, changing or
isolating official Antigravity paths, deciding what to do with model names that
contain `Gemini`, removing OpenCode's Google Gemini model alias, and updating
memory through the approved workflow.

## Tests To Plan

Add or update focused tests for:

- `agy` provider metadata, model aliases, and provider/model directive
  resolution.
- Invocation argv, cwd behavior, timeout formatting, long-prompt guard, and
  stdout capture.
- Failure diagnostics when `agy` exits nonzero or returns empty stdout.
- Doctor checks for `agy --version`; optional deep check for `agy models`.
- Generated skill target paths:
  `~/.gemini/antigravity-cli/skills/<skill>/SKILL.md`.
- Provider autodetect ordering and `sase skill init -p agy`.
- TUI provider styles, prompt-panel model display, and model names with spaces.
- Removal of Gemini parser/thinking tests or replacement with `agy` tests.
- Active-surface reference guard, with an explicit allowlist if Antigravity-owned
  `gemini` strings remain.

Suggested active-surface guard after migration:

```bash
rg -i 'gemini-cli|@google/gemini-cli|SASE_GEMINI_PATH|\bgemini\b|GEMINI\.md' \
  pyproject.toml config src tests README.md docs xprompts
```

If policy permits Antigravity-owned strings, keep the allowlist small and tied
to specific files/tests.

## Recommended Migration Strategy

Use an additive-then-subtractive migration, but keep it short-lived so the repo
does not carry both providers for long.

1. Define the zero-reference policy before coding. I recommend active-surface
   zero for Gemini CLI/provider/runtime support, with explicit upstream
   exceptions for Antigravity-owned paths and exact model names. Treat literal
   repo-wide zero as a separate archival/memory cleanup.

2. Spike the exact `agy` contract in the implementation environment: print
   mode, long prompt behavior, timeout mapping, model aliases, noninteractive
   permissions, `--continue`/`--conversation`, `--log-file`, and whether any
   stable JSON/log schema exists. Record the installed `agy` version.

3. Add the new `agy` provider first. Use provider ID `agy`, `SASE_AGY_PATH`,
   exact `agy models` names behind SASE aliases, plain stdout streaming, global
   skill deploy path `.gemini/antigravity-cli`, doctor support, TUI styling, and
   focused provider tests.

4. Prove `agy` end to end through SASE with a real minimal prompt, generated
   skill target planning, and the provider/model directive path.

5. Remove Gemini CLI support in one sweep: entry point, provider modules,
   stream parser, tool-call normalizer, retry config, doctor hints, shims, model
   maps, TUI special cases, thinking parser, docs, README, xprompts, and tests.

6. Rename generic `gemini_wrapper` and `gemini_timer` symbols before enforcing
   active-tree zero references. Do not leave backward-compatible import aliases
   if zero references is the goal.

7. Resolve generated-skill fallout: delete or retarget `sase_hg_commit`, run
   `sase skill init --force`, and update skill-path tests. Use the approved
   memory workflow before changing memory notes.

8. Run focused suites first, then `just check`. Add the active-surface reference
   guard once the desired allowlist is settled.

9. Fast-follow only after upstream support exists: implement `agy` tool-call
   JSONL artifacts, usage accounting, richer diagnostics, and thinking display
   from a stable Antigravity output/log/conversation contract.

## Sources

- Google Developers Blog, "An important update: Transitioning Gemini CLI to
  Antigravity CLI", 2026-05-19:
  <https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/>
- Antigravity CLI installation docs:
  <https://antigravity.google/assets/docs/cli/cli-install.md>
- Antigravity CLI migration docs:
  <https://antigravity.google/assets/docs/cli/gcli-migration.md>
- Antigravity CLI plugins and skills docs:
  <https://antigravity.google/assets/docs/cli/cli-plugins.md>
- Antigravity CLI reference:
  <https://antigravity.google/assets/docs/cli/cli-reference.md>
- Local prior failure analysis:
  `sdd/research/202606/gemini_cli_antigravity_recommendation.md`
