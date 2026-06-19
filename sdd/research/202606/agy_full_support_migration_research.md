---
create_time: 2026-06-19
updated_time: 2026-06-19
status: research
---

# Antigravity (`agy`) Full-Support Migration Research

## Research Request

Determine what it will take to migrate SASE from Gemini CLI (`gemini`) to
Antigravity CLI (`agy`), remove Gemini CLI completely, avoid remaining Gemini
references, and give `agy` as complete a SASE integration as possible.

## Bottom Line

This is a medium-to-large migration, not a binary rename.

SASE has a first-class Gemini provider, Gemini-specific stream parsers, Gemini
tool-call normalization, generated skill targets, docs, tests, config defaults,
provider shims, and historical SDD material. Antigravity CLI is available
locally as `agy` and works in print mode, but it does not expose a documented or
help-listed Gemini-compatible `stream-json` mode. A first Antigravity provider
can be implemented cleanly with plain stdout streaming, but full parity for
usage accounting and normalized tool-call artifacts depends on discovering a
stable machine-readable output contract or building a separate integration
against Antigravity logs/databases.

The largest scope decision is the meaning of "ZERO remaining references."
Removing Gemini CLI/provider support from active SASE surfaces is feasible.
Achieving literal repo-wide zero text matches for `gemini` is much larger and
conflicts with current Antigravity realities: Antigravity's official global
config path is under `~/.gemini/antigravity-cli/`, the model names returned by
`agy models` include "Gemini", and Antigravity still reads `GEMINI.md` for
workspace compatibility. This research note itself would also be a remaining
historical reference unless archived material is exempted or later removed.

## External Findings

Google's May 19, 2026 transition announcement says Antigravity CLI is the new
terminal experience and that it is part of the Antigravity platform. It also
says Antigravity CLI will not have 1:1 feature parity immediately, but keeps
critical Gemini CLI constructs: Agent Skills, Hooks, Subagents, and Extensions
as Antigravity plugins. The consumer timeline matters: on June 18, 2026 Gemini
CLI and Gemini Code Assist IDE extensions stopped serving requests for Google AI
Pro/Ultra and free Gemini Code Assist for individuals users. Enterprise and API
key paths remain supported.

Official Antigravity CLI docs show:

- Install path on macOS/Linux: `~/.local/bin/agy`.
- Installer: `curl -fsSL https://antigravity.google/cli/install.sh | bash`.
- Config path: `~/.gemini/antigravity-cli/settings.json`.
- Keybindings path: `~/.gemini/antigravity-cli/keybindings.json`.
- Global skill path: `~/.gemini/antigravity-cli/skills/`.
- Workspace skill path: `.agents/skills/`.
- Plugin path: `~/.gemini/antigravity-cli/plugins/<plugin_name>/`.
- Plugin structure: `plugin.json`, optional `mcp_config.json`, `hooks.json`,
  `skills/`, `agents/`, and `rules/`.
- Migration command for legacy extensions: `agy plugin import gemini`.
- Context compatibility: Antigravity still parses workspace `GEMINI.md` and
  `AGENTS.md`, and global `~/.gemini/GEMINI.md`.
- MCP migration requires standalone `mcp_config.json` files and remote URI key
  updates from `url` or `httpUrl` to `serverUrl`.

There is one docs inconsistency to verify during implementation: the migration
doc says global MCP servers live at `~/.gemini/config/mcp_config.json`, while
the plugins doc says `~/.gemini/antigravity-cli/mcp_config.json`. The installed
CLI should be treated as authoritative.

## Local `agy` Evidence

Local checks on 2026-06-19:

| Probe | Result |
| --- | --- |
| `command -v agy` | `/home/bryan/.local/bin/agy` |
| `agy --version` | `1.0.10` |
| `command -v gemini` | `/home/bryan/.config/nvm/versions/node/v22.14.0/bin/gemini` |
| `agy plugin list` | `No imported plugins.` |

`agy --help` confirms these relevant flags/subcommands:

- `--print` / `-p`: run one prompt non-interactively and print the response.
- `--prompt`: alias for `--print`.
- `--prompt-interactive` / `-i`: seed an interactive session.
- `--model`: select the model for the session.
- `--print-timeout`: print-mode timeout, default `5m0s`.
- `--dangerously-skip-permissions`: auto-approve tool permission requests.
- `--sandbox`: enable terminal sandbox restrictions.
- `--add-dir`: add a directory to the workspace, repeatable.
- `--continue` / `-c`: continue the most recent conversation.
- `--conversation`: resume a previous conversation by ID.
- `--log-file`: override the CLI log file path.
- Subcommands: `models`, `plugin`, `plugins`, `install`, `update`,
  `changelog`, `help`.

Important local behavior:

- `agy models` succeeds and returns:
  - `Gemini 3.5 Flash (Medium)`
  - `Gemini 3.5 Flash (High)`
  - `Gemini 3.5 Flash (Low)`
  - `Gemini 3.1 Pro (Low)`
  - `Gemini 3.1 Pro (High)`
  - `Claude Sonnet 4.6 (Thinking)`
  - `Claude Opus 4.6 (Thinking)`
  - `GPT-OSS 120B (Medium)`
- A print-mode smoke test exits 0 and prints clean stdout:
  `agy --print-timeout 30s --model "Gemini 3.5 Flash (Low)" --dangerously-skip-permissions -p "Respond with exactly OK."`
  returned `OK`.
- `--print` is a string flag, not stdin mode. Running
  `printf ... | agy --print` fails with exit code 2 and
  `flag needs an argument: -print`.
- `agy 1.0.10 --help` does not show `--cwd`, even though some docs/examples
  refer to cwd-based usage. SASE should set the subprocess working directory
  directly and use `--add-dir` for additional roots if needed.
- `agy --help` does not show `--output-format`, `--json`, or a stream event
  mode.

## Current SASE Gemini Surface Area

Repo scan summary for `gemini` / `gemini-cli` references:

| Top-level area | Matching files |
| --- | ---: |
| `sdd` | 428 |
| `tests` | 46 |
| `src` | 28 |
| `docs` | 13 |
| `memory` | 2 |
| `pyproject.toml` | 1 |
| `config` | 1 |
| `README.md` | 1 |
| `xprompts` | 1 |

Tracked files and paths with Gemini-specific names include:

- `.gemini/settings.json`
- `GEMINI.md`
- `tools/GEMINI.md`
- `src/sase/ace/GEMINI.md`
- `src/sase/gemini_wrapper/`
- `src/sase/llm_provider/gemini.py`
- `src/sase/llm_provider/_subprocess_gemini.py`
- `src/sase/llm_provider/_tool_call_gemini.py`
- `tests/llm_provider/test_gemini_stream_parser.py`
- `tests/test_gemini_wrapper.py`
- Historical SDD prompts, tales, epics, and prior Antigravity research.

There are also local `__pycache__` paths with Gemini names. They are not the
main migration target, but a literal path-level cleanup should remove generated
bytecode caches after code moves.

## Active Code Impact

The core built-in provider registration is in `pyproject.toml`:

```toml
[project.entry-points."sase_llm"]
gemini = "sase.llm_provider.gemini:GeminiProvider"
```

The current Gemini provider does all of the following:

- Uses provider ID `gemini` and short name `gem`.
- Defaults to `gemini-3-flash-preview`.
- Uses `SASE_GEMINI_PATH` or `gemini`.
- Exposes Gemini model names and short aliases such as `flash3`, `pro31p`,
  `pro25`, and `flash25`.
- Invokes `gemini --output-format stream-json --yolo --model <model>` and
  passes the prompt on stdin.
- Parses Gemini `stream-json` events for assistant text, result/error details,
  and usage.
- Normalizes Gemini stream tool events into SASE `tool_calls.jsonl`.
- Deploys extra skills under `.gemini/jetski`.
- Provides Gemini-specific skill template context.
- Reconstructs context after interrupts because Gemini CLI lacks session
  persistence in the current provider.

Other active references that need migration or deletion:

- `src/sase/llm_provider/_subprocess.py` exports Gemini stream helpers.
- `src/sase/llm_provider/_tool_calls.py` imports Gemini tool-call capture.
- `src/sase/llm_provider/registry.py` knows Gemini colors and invalidates
  metadata on `SASE_GEMINI_PATH`.
- `src/sase/default_config.yml` has Gemini retry config and prompt text.
- `src/sase/doctor/checks_providers.py` recommends installing
  `@google/gemini-cli` and authenticating with `gemini`.
- `src/sase/ace/tui/provider_styles.py` contains Gemini UI styling.
- `src/sase/ace/tui/widgets/prompt_panel/_helpers.py` has model-display logic
  for Gemini.
- `src/sase/ace/tui/thinking/parser.py` parses Gemini API proxy logs.
- `src/sase/amd/constants.py` includes `GEMINI.md` as a provider shim.
- `src/sase/memory/inventory.py` treats `GEMINI.md` as an instruction file.
- `src/sase/main/parser_init.py` exposes `gemini` in `sase skill init -p`.
- `src/sase/skills/cli_list.py` contains Gemini color/order metadata.
- `src/sase/workflows/crs.py` has Gemini-specific workflow language.
- `xprompts/reads.md` explicitly selects
  `%model:gemini/gemini-3.1-pro-preview`.
- `config/sase.schema.json`, `README.md`, and provider docs reference Gemini.

## `gemini_wrapper` Is Partly Generic

`src/sase/gemini_wrapper/` is not only a Gemini CLI wrapper anymore. Its
`file_references.py` module contains generic preprocessing utilities used by
multiple flows, including:

- `src/sase/sdd/_write.py`
- `src/sase/workflows/commit/precommit_hooks.py`
- `src/sase/main/plan_propose_handler.py`
- `src/sase/plan_approval_actions.py`
- `src/sase/xprompt/processor.py`
- `src/sase/llm_provider/preprocessing.py`
- `src/sase/main/init_skills_handler.py`
- TUI notification modal formatting.

For zero active Gemini references, this package should be split:

- Move generic file-reference/prettier helpers to a neutral module such as
  `sase.prompt_references`, `sase.file_references`, or
  `sase.llm_provider.preprocessing_refs`.
- Delete the old Gemini command wrapper compatibility exports once imports and
  tests are moved.
- Rename tests currently named `test_gemini_wrapper.py` to the new generic
  module name.

Keeping a backward-compat import alias would violate the zero-reference goal.

## Provider Design For `agy`

Recommended provider identity:

| Field | Recommendation |
| --- | --- |
| Provider ID | `agy` |
| Display name | `Antigravity` |
| Short name | `agy` |
| Binary env var | `SASE_AGY_PATH` |
| Default binary | `agy` |
| Autodetect CLI | `agy` |
| Autodetect priority | Replace Gemini's late fallback slot, likely after OpenCode |
| Skill context tool name | `Antigravity CLI` |

`agy` is better than `antigravity` as the primary provider ID because it matches
the actual binary and keeps model directives compact: `%model:agy/<alias>`.

The initial invocation shape should be based on local evidence:

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

SASE should set `cwd` on the subprocess rather than relying on a CLI flag. Add
`--add-dir <path>` only if SASE needs Antigravity to see extra workspace roots.

Open implementation questions:

- What is the largest prompt SASE sends in practice, and can it fit safely in
  `execve` argument limits when `--print` requires a string value?
- Does `agy` have a hidden or future prompt-file/stdin mechanism?
- Does `agy` have a hidden or future machine-readable output mode?
- What is the correct timeout mapping from SASE's provider timeout to Go-style
  duration strings?
- Does `--dangerously-skip-permissions` fully prevent noninteractive approval
  hangs for tool-using prompts?

## Model Mapping

Antigravity is not just a Gemini model runner. Local `agy models` exposes
Gemini, Claude, and GPT-OSS models through the Antigravity harness.

The provider should expose exact `agy models` display names and SASE-friendly
aliases. Aliases matter because display names contain spaces and parentheses,
which are awkward in xprompt `%model:` directives and spawned-agent suffixes.

Suggested initial alias map:

| Exact `agy` model | Suggested alias |
| --- | --- |
| `Gemini 3.5 Flash (Medium)` | `flash35m` |
| `Gemini 3.5 Flash (High)` | `flash35h` |
| `Gemini 3.5 Flash (Low)` | `flash35l` |
| `Gemini 3.1 Pro (Low)` | `pro31l` |
| `Gemini 3.1 Pro (High)` | `pro31h` |
| `Claude Sonnet 4.6 (Thinking)` | `sonnet46t` |
| `Claude Opus 4.6 (Thinking)` | `opus46t` |
| `GPT-OSS 120B (Medium)` | `gptoss120m` |

Default model should be chosen deliberately. `Gemini 3.5 Flash (High)` is a
reasonable first default if the goal is to replace the old Gemini Flash default
with the strongest local Flash tier. `Gemini 3.5 Flash (Medium)` is a safer
latency/cost default if SASE wants conservative background-agent behavior.

## Output, Tool Calls, And Usage

This is the main parity gap.

Gemini CLI support currently relies on `--output-format stream-json`. That gives
SASE:

- Incremental assistant text extraction.
- Structured error/result diagnostics.
- Usage counters.
- Tool-call records in SASE's normalized `tool_calls.jsonl` format.

`agy 1.0.10 --help` and the official docs reviewed here do not expose an
equivalent stream JSON mode. Local print mode produces clean plain stdout for a
trivial prompt, so a first implementation can use SASE's plain subprocess
streamer and ANSI cleanup.

Expected provider v1 limitations unless a JSON mode is found:

- No token usage metrics from the response stream.
- No normalized Antigravity tool-call artifact rows.
- Less structured error diagnostics.
- Less detailed TUI Tools panel integration.
- No replacement for the existing Gemini API proxy thinking parser.

Do not hand-roll fragile parsing of human-oriented TUI text for tool calls. If
tool-call parity matters, inspect Antigravity's `--log-file` output,
conversation databases, or upstream docs/forums for a stable contract.

## Skills, Plugins, Hooks, And MCP

Generated skills are relevant because project memory says skill files are
generated from `src/sase/xprompts/skills/`, and `sase skill init --force` should
be run after changing generated skill sources or provider skill targeting.

For `agy`, implement:

- `llm_skill_deploy_subpath() -> ".gemini/antigravity-cli"` to place global
  skills at the official `~/.gemini/antigravity-cli/skills/<skill>/SKILL.md`.
- Antigravity-specific skill template context:
  - `provider_name`: `Antigravity`
  - `provider_tool_name`: `Antigravity CLI`
  - `provider_native_ask_tool`: verify whether `ask_user` remains correct in
    Antigravity skills.
- Optional workspace skill support for `.agents/skills/` if SASE wants a repo
  local deployment mode. The current global skill deployer writes under home or
  chezmoi; workspace `.agents/skills` is a separate behavior.
- Plugin support documentation and possible helper workflows for:
  - `agy plugin import gemini`
  - `agy plugin install`
  - `agy plugin validate`
  - Antigravity plugin directory layout.
- MCP docs/config migration from legacy inline settings to
  `mcp_config.json`, with `serverUrl` for remote endpoints.

The existing `sase_hg_commit` generated skill is marked Gemini-only. If Gemini
is removed, either delete this skill or retarget it to `agy` only after an
Antigravity/hg smoke test proves the same commit workflow works.

## Configuration, Doctor, And UX

Config changes:

- Remove `llm_provider.retry.gemini` defaults.
- Add `llm_provider.retry.agy` only if Antigravity has known retryable error
  patterns.
- Update schema examples from `gemini` to `agy`, `claude`, or provider-neutral
  examples.
- Update model-purpose/fanout examples away from Gemini CLI models.

Doctor changes:

- Replace Gemini CLI install hint with Antigravity CLI install instructions.
- Check `agy --version` for basic readiness.
- Optionally add a deep check that runs `agy models` because it verifies auth
  and model discovery without generating a model response.
- Avoid a default model-response smoke test in normal doctor mode because it may
  consume credits and can mutate conversation history.

TUI/UX changes:

- Add `agy` styling and model-picker entries.
- Remove Gemini-specific badge/style entries.
- Replace Gemini timer naming (`gemini_timer`) with a neutral helper such as
  `agent_timer` or `provider_timer`; all providers currently import the Gemini
  named helper.
- Remove or replace Gemini API proxy thinking parsing.
- Confirm prompt-panel display handles model names with spaces and parentheses.

## Tests To Update

High-impact test areas:

- Provider registration and resolution tests.
- Autodetect and doctor readiness tests.
- Retry config tests.
- Provider invocation tests for command arguments, cwd behavior, timeouts, and
  plain stdout parsing.
- Deletion or replacement of Gemini stream parser tests.
- Tool-call tests should either skip Antigravity parity until a structured
  stream exists or cover a newly discovered stable format.
- Skill target path tests should expect
  `~/.gemini/antigravity-cli/skills/...` for global Antigravity skills.
- XPrompt loader/parser tests with provider-scoped skills and model directives.
- Agent-loader/model suffix tests, especially aliases for `agy` models.
- TUI provider-style and model-picker tests.
- Memory/AMD shim tests that currently assert `GEMINI.md`.
- File-reference tests after moving `gemini_wrapper.file_references`.

Add a regression guard for active surfaces after migration. Example active-path
search:

```bash
rg -i 'gemini-cli|@google/gemini-cli|SASE_GEMINI_PATH|\bgemini\b|GEMINI\.md|\.gemini/skills' \
  pyproject.toml config src tests README.md docs xprompts
```

The exact allowlist must be decided because Antigravity's official paths and
model display names contain `gemini`.

## Zero-Reference Scope

There are three possible definitions:

1. **Recommended active-surface zero**: remove Gemini CLI/provider support from
   active code, tests, docs, config, README, and xprompts. Permit historical SDD
   research/prompts/tales and protected memory to remain unless explicitly
   cleaned in a separate archival task.
2. **Provider-zero with upstream exceptions**: remove Gemini CLI/provider
   support everywhere active, but permit Antigravity-required upstream tokens
   such as `~/.gemini/antigravity-cli` and model display names returned by
   `agy models`.
3. **Literal repo-wide zero**: no tracked file path or content may contain
   `gemini` in any case.

Literal repo-wide zero has major consequences:

- Existing and newly written SDD research files must be deleted, renamed, or
  redacted.
- Historical prompt/tale/epic files must be rewritten or removed.
- Root `GEMINI.md`, `tools/GEMINI.md`, and `src/sase/ace/GEMINI.md` must be
  removed.
- Protected memory files require explicit user approval and the audited memory
  workflow; do not edit them directly.
- Official Antigravity global paths containing `~/.gemini/antigravity-cli`
  cannot appear literally in docs/tests/code. Code would need to compute or
  isolate those strings, which is more confusing and less maintainable.
- Exact Antigravity model display names containing "Gemini" cannot be documented
  or represented literally. SASE would need aliases only, but the provider still
  must pass exact names to `agy`.

For engineering quality, avoid contorting implementation solely to hide upstream
strings. A better goal is: no Gemini CLI provider, no `gemini` runtime ID, no
Gemini CLI binary invocation, no Gemini CLI docs, and no active compatibility
aliases, with narrow documented exceptions for Antigravity-owned paths/model
names if needed.

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
- Antigravity CLI usage docs:
  <https://antigravity.google/assets/docs/cli/cli-using.md>
- Antigravity CLI reference:
  <https://antigravity.google/assets/docs/cli/cli-reference.md>
- Antigravity CLI conversations docs:
  <https://antigravity.google/assets/docs/cli/cli-conversations.md>
- Official codelab, "Hands-on with Antigravity CLI":
  <https://codelabs.developers.google.com/antigravity-cli-hands-on>
- Prior local SASE research:
  `sdd/research/202606/gemini_cli_antigravity_recommendation.md`

## Recommended Migration Strategy

1. Define the zero-reference policy before coding. I recommend active-surface
   zero plus explicit upstream exceptions for Antigravity-owned paths and model
   display names. Treat literal repo-wide zero as a separate archival cleanup
   because it touches protected memory and historical SDD files.

2. Implement a new `agy` provider first; do not alias `gemini` to `agy`. Use
   `SASE_AGY_PATH`, provider ID `agy`, short name `agy`, autodetect CLI `agy`,
   and exact model names from `agy models` behind SASE-friendly aliases.

3. Start with proven print-mode support using `--print`, `--model`,
   `--dangerously-skip-permissions`, and `--print-timeout`, with subprocess
   `cwd` set by SASE. Use plain stdout streaming and document that usage/tool
   call parity is pending a stable Antigravity machine-readable output contract.

4. Move generated skill support to the official Antigravity global path
   `~/.gemini/antigravity-cli/skills/`, update skill templates to Antigravity
   terminology, and decide separately whether SASE should also write workspace
   `.agents/skills/`.

5. Remove the Gemini provider and active Gemini CLI surface in one sweep:
   entry point, provider module, stream parser, tool-call normalizer, retry
   config, doctor hints, model maps, TUI styles, workflow examples, docs, README,
   xprompts, and tests. Rename generic `gemini_wrapper` utilities before deleting
   the compatibility wrapper.

6. Regenerate provider skills with `sase skill init --force`, update docs/tests,
   and run the focused provider, doctor, xprompt, skill-path, and TUI test suites.

7. Add a CI/regression search for forbidden active Gemini CLI references. Keep
   the allowlist explicit and small; if the user later requires literal
   repo-wide zero, do a follow-up cleanup with approval for memory files and a
   conscious decision about historical SDD records.
