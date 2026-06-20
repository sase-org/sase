---
create_time: 2026-06-19 18:55:35
status: done
prompt: sdd/prompts/202606/agy_provider_mvp.md
bead_id: sase-50
tier: epic
---
# Plan: Add an Antigravity (`agy`) LLM Provider MVP

## Problem

SASE's current Gemini CLI provider is no longer a reliable local consumer path. Google moved the consumer terminal
experience to Antigravity CLI, whose binary is `agy`, while SASE still has a deep Gemini-specific integration: provider
entry point, subprocess invocation, stream parser, tool-call artifacts, model metadata, generated skill paths, doctor
hints, retry config, docs, tests, and several generic helpers with Gemini-era names.

The migration must not be a `SASE_GEMINI_PATH=agy` alias. `agy` has different flags, model names, config paths, and
prompt transport. It is also currently less machine-readable than Gemini CLI: local `agy 1.0.10` and official docs show
`--print`, `--model`, `--print-timeout`, `--dangerously-skip-permissions`, `--log-file`, `--continue`, and
`--conversation`, but no documented `--output-format stream-json` or JSON event mode.

The MVP should be ambitious, but honest about upstream limits: support every SASE provider surface that can be supported
through stable `agy` behavior, and explicitly gate tool-call/usage/thinking parity on a stable output/log/conversation
contract rather than scraping human TUI text.

## Principles

- Add `agy` as a first-class provider through the existing pluggy/entry-point provider system.
- Keep provider-specific code thin: command construction, local env resolution, and parser glue only.
- Reuse shared preprocessing, postprocessing, retry, interrupt, commit finalizer, artifact, model override, and TUI
  metadata paths.
- Do not add runner branches such as `if provider == "agy"`.
- Prefer additive migration first, then cleanup, so each phase can be verified independently.
- Do not modify protected memory files without explicit approval. If generated skill source behavior changes, use the
  generated-skill workflow from `memory/generated_skills.md`.

## Current Facts

- Local `agy` exists at `/home/bryan/.local/bin/agy`, version `1.0.10`.
- Local `agy --help` exposes `--print/-p`, `--prompt`, `--model`, `--print-timeout`, `--dangerously-skip-permissions`,
  `--sandbox`, `--add-dir`, `--continue/-c`, `--conversation`, and `--log-file`.
- Local `agy models` returns exact display names with spaces, including `Gemini 3.5 Flash (High)`,
  `Gemini 3.5 Flash (Low)`, `Claude Opus 4.6 (Thinking)`, and `GPT-OSS 120B (Medium)`.
- Official Antigravity docs put global skills under `~/.gemini/antigravity-cli/skills/` and workspace skills under
  `.agents/skills/`.
- Official docs and local help do not currently document JSON or stream events for `agy`.

## Phase 1: Contract Spike and Capability Decision

Goal: pin the `agy` CLI contract before implementation agents encode assumptions.

Tasks:

1. Re-run focused local probes against the installed `agy`:
   - `agy --help`
   - `agy models`
   - `agy --print-timeout 30s --model "Gemini 3.5 Flash (Low)" --dangerously-skip-permissions --print "Respond with exactly OK."`
   - long multi-line prompt through `--print`
   - argument-length behavior for realistically large SASE prompts
   - `--log-file` content after a prompt with tool use
   - `--continue` and `--conversation` behavior in print mode
   - failure modes for missing auth, bad model names, timeout, and non-zero exits
2. Check whether `agy` supports any stable machine-readable output via documented flags, log files, conversation state,
   or plugin/hook outputs.
3. Record the result in `sdd/research/202606/agy_contract_spike.md` or by updating the existing consolidated `agy`
   research note.
4. Decide the MVP parser path:
   - structured parser if a stable JSON/log schema exists;
   - plain stdout provider if it does not.

Acceptance:

- The next phase has exact command examples, expected return codes, model names, timeout format, and prompt transport.
- Any structured-output claim is backed by a fixture captured from local `agy 1.0.10` or official docs.
- If no structured contract exists, the plan explicitly marks tool-call artifacts, usage accounting, and thinking
  extraction as unsupported in MVP rather than partially faking them.

## Phase 2: Core `agy` Provider

Goal: implement the provider MVP using existing provider abstractions and plain stdout streaming unless Phase 1 proves a
structured stream exists.

Tasks:

1. Add `src/sase/llm_provider/agy.py`.
2. Register the provider in `pyproject.toml` under `[project.entry-points."sase_llm"]` as:
   `agy = "sase.llm_provider.agy:AgyProvider"`.
3. Implement provider metadata hooks:
   - provider id: `agy`
   - display/tool context: Antigravity / Antigravity CLI
   - short name: `agy`
   - autodetect CLI: `agy`
   - autodetect priority: late fallback, probably the old Gemini slot (`30`)
   - CLI color: a distinct Antigravity color, not Gemini blue
   - skill deploy subpath: `.gemini/antigravity-cli`
   - known model names: exact `agy models` display names from Phase 1
   - model short aliases: compact aliases for exact display names with spaces
4. Implement model tier defaults. Recommended initial mapping:
   - `large`: `Gemini 3.5 Flash (High)`
   - `small`: `Gemini 3.5 Flash (Low)` Keep all other `agy models` names available through `%model:agy/<exact name>` and
     configured aliases.
5. Implement command construction using subprocess argument lists, not shell strings:
   - binary from `SASE_AGY_PATH` or `agy`
   - `--print-timeout <duration>`
   - `--model <resolved model>`
   - `--dangerously-skip-permissions`
   - `--print <prompt>`
6. Add provider-specific env args with the established precedence:
   - `SASE_LLM_LARGE_ARGS` before `SASE_AGY_LARGE_ARGS`
   - `SASE_LLM_SMALL_ARGS` before `SASE_AGY_SMALL_ARGS` Add `SASE_AGY_PRINT_TIMEOUT` only if Phase 1 shows timeout
     tuning is necessary.
7. Use shared `stream_process_output()` for stdout/stderr/live reply capture in the plain-output path.
8. Reuse `start_interrupt_monitor()` and the Qwen/OpenCode-style restart-with-accumulated-context pattern unless Phase 1
   proves `--continue` can reliably preserve print-mode conversation state.
9. Return `InvokeResult(content=..., usage=None)` unless structured usage is verified.
10. Add precise missing-binary and non-zero-exit diagnostics. Do not treat empty stdout as success unless the CLI exit
    and artifacts prove it is expected.

Acceptance:

- Unit tests cover provider subclassing, tier resolution, model override, exact argv construction, env var precedence,
  `SASE_AGY_PATH`, missing executable errors, non-zero exit handling, interrupt resume prompt construction, and fake CLI
  live reply capture.
- `%model:agy/Gemini 3.5 Flash (High)` preserves the nested provider/model string after the first slash.
- A fake `agy` subprocess test proves no shell interpolation occurs when prompts contain quotes, newlines, or spaces.

## Phase 3: Registry, Doctor, Config, and TUI Integration

Goal: make `agy` participate in SASE's provider ecosystem the same way Claude, Codex, Qwen, and OpenCode do.

Tasks:

1. Update registry metadata cache invalidation so new provider path env vars do not require adding one more hardcoded
   list entry per provider. Prefer deriving `SASE_<PROVIDER>_PATH` names from registered metadata where practical.
2. Add doctor setup hints for Antigravity:
   - install: `curl -fsSL https://antigravity.google/cli/install.sh | bash`
   - auth: run `agy` and complete login/trust onboarding
3. Ensure `sase doctor -C llm.default -v` reports `SASE_AGY_PATH`, executable path, auth-not-verified status, and model
   resolutions when `agy` is selected.
4. Add default retry policy for retryable `agy` transport/rate-limit/timeouts through `llm_default_retry_config()` or
   `default_config.yml`, not runner branches.
5. Ensure temporary default override, worker model override, model picker/search, provider labels, and provider colors
   handle model names with spaces and parentheses.
6. Update any config schema/examples that enumerate known providers or provider/model syntax.

Acceptance:

- Registry tests cover `agy` metadata, short name, color, autodetect ordering, model-to-provider map, and nested
  provider/model resolution.
- Doctor tests cover missing and found `agy` executable paths.
- Temporary override and model-picker tests include at least one exact `agy` model with spaces.
- No new provider-specific branching is introduced outside provider metadata, doctor hints, and provider-local code.

## Phase 4: Skills and Runtime Instruction Support

Goal: make Antigravity agents receive the same generated SASE skills and commit workflow support as Claude and Codex.

Tasks:

1. Update skill-init provider choices and tests so `sase skill init -p agy` is supported.
2. Use `AgyProvider.llm_skill_template_context()` and `llm_skill_deploy_subpath()` to route generated skills to
   `~/.gemini/antigravity-cli/skills/` through SASE's existing global skill deployment machinery.
3. Verify whether Antigravity recognizes existing skill frontmatter as documented. Adjust source skill templates only if
   needed, then run `sase skill init --force` per the generated-skill instructions.
4. Ensure `/sase_git_commit`, `/sase_plan`, `/sase_questions`, `/sase_memory_read`, and other core generated skills are
   available to `agy`.
5. Do not hand-edit deployed chezmoi skill files. If deployed outputs need refreshing, do it through generation.
6. Decide `sase_hg_commit` separately. It is Gemini-only in current memory; do not automatically move it to `agy` unless
   a real Antigravity/hg workflow is validated.

Acceptance:

- Skill target tests prove `agy` writes global skills under `.gemini/antigravity-cli/skills/`.
- A generated-skill smoke check shows `agy` can see at least `/sase_git_commit` or the Antigravity equivalent slash
  command after generation.
- Commit finalizer tests continue to use the provider-neutral path and do not need `agy` stop hooks.

## Phase 5: Structured Artifacts Parity Gate

Goal: support Claude/Codex-level artifacts where `agy` exposes stable data, and clearly document gaps where it does not.

Tasks if Phase 1 finds a stable structured contract:

1. Add `src/sase/llm_provider/_subprocess_agy.py` for structured parsing.
2. Add `src/sase/llm_provider/_tool_call_agy.py` only if tool-use/tool-result events can be extracted without scraping
   human display text.
3. Normalize tool records into the existing `tool_calls.jsonl` schema with `runtime: "agy"` and `source: "stream"` or
   another accurate source label such as `"log"`.
4. Write `usage.json` only from stable token counters.
5. Add fixtures from real `agy` output/logs and cross-provider Tools panel reader tests.

Tasks if no stable structured contract exists:

1. Keep plain stdout as the supported MVP path.
2. Do not create fake `tool_calls.jsonl` rows from display glyphs or prose.
3. Add a small provider/docs note stating that tool-call timeline, usage accounting, and thinking extraction require a
   future Antigravity machine-readable contract.
4. Add tests proving plain stdout still writes `live_reply.md` and no malformed tool artifact is created.

Acceptance:

- Either real parser fixtures exist, or unsupported structured features are explicit and tested.
- The ACE Tools panel remains provider-neutral; it does not learn `agy`-specific display scraping.
- No provider lies about usage or tool calls.

## Phase 6: Gemini Migration and Cleanup

Goal: make Antigravity the replacement path while preserving SASE's pluggable provider model.

Tasks:

1. Remove Gemini from normal autodetect and user-facing setup recommendations once `agy` is working.
2. Keep the old Gemini provider only if the project still wants explicit enterprise/API-key fallback. If kept:
   - make `UNSUPPORTED_CLIENT` / `IneligibleTierError` non-retryable and actionable;
   - document that consumer OAuth Gemini CLI stopped serving requests on 2026-06-18;
   - do not advertise Gemini as the migration target.
3. If the desired policy is active-surface removal, delete or quarantine Gemini provider modules, stream parser, tool
   normalizer, Gemini retry defaults, doctor hints, and Gemini-specific tests after `agy` replacements land.
4. Rename generic leftovers before enforcing reference guards:
   - `gemini_timer` -> `agent_timer` or `provider_timer`
   - `src/sase/gemini_wrapper/` -> a neutral file/prompt reference package
5. Update README, `docs/llms.md`, `docs/configuration.md`, `docs/xprompt.md`, xprompts, and schema examples.
6. Add an active-surface reference guard with a tight allowlist for Antigravity-owned strings such as
   `~/.gemini/antigravity-cli` and exact model display names containing `Gemini`.

Acceptance:

- There is no active SASE path that invokes the `gemini` binary for consumer fallback.
- User-facing docs point users to `agy`.
- Any remaining `gemini` strings are intentional, tested, and either historical/SDD or Antigravity-owned path/model
  facts.
- Generic helper renames do not leave backward-compatible aliases if the chosen policy is active-surface zero.

## Phase 7: End-to-End Hardening

Goal: prove the migration works as a real SASE provider, not just as isolated unit tests.

Tasks:

1. Run targeted tests first:
   - provider command tests
   - registry/model resolution tests
   - doctor provider tests
   - skill-init target tests
   - temporary override/model picker tests
   - parser/artifact tests if Phase 5 added structured parsing
2. Run at least one real minimal SASE invocation with `provider_name="agy"` or `%model:agy/<model>` and
   `SASE_ARTIFACTS_DIR` set.
3. Run a commit-finalizer smoke scenario with a fake provider or controlled workspace to prove `agy` participates in the
   shared finalizer path.
4. Run `just install` before full checks if the workspace has not been initialized recently, then run `just check`.
5. Capture final known gaps in docs and a short SDD tale/research note if structured parity remains blocked by upstream
   CLI support.

Acceptance:

- `just check` passes.
- A real `agy` smoke run returns useful content, writes `live_reply.md`, and records provider/model metadata.
- Doctor output is actionable when `agy` is missing and clean when it is installed.
- Any remaining non-parity with Claude/Codex is explicitly tied to missing `agy` machine-readable output, not SASE
  architecture.

## Non-Goals

- Do not implement `agy` by reusing the Gemini provider with a different binary path.
- Do not scrape Antigravity's human TUI rendering to synthesize tool-call or usage artifacts.
- Do not add provider-specific branches to the shared runner, commit finalizer, retry engine, or ACE reader.
- Do not rewrite historical SDD records merely to remove old Gemini mentions.
- Do not modify memory files without explicit approval.

## References

- Local research: `sdd/research/202606/gemini_cli_antigravity_recommendation.md`
- Local research: `sdd/research/202606/agy_migration_consolidated.md`
- Google transition announcement:
  <https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/>
- Antigravity CLI reference: <https://antigravity.google/assets/docs/cli/cli-reference.md>
- Antigravity migration docs: <https://antigravity.google/assets/docs/cli/gcli-migration.md>
- Antigravity plugins and skills docs: <https://antigravity.google/assets/docs/cli/cli-plugins.md>
