---
create_time: 2026-06-19
updated_time: 2026-06-20
status: research
bead_id: sase-50.7
---

# Antigravity (`agy`) Provider — Phase 7 End-to-End Hardening

This note records the Phase 7 hardening results for the Antigravity (`agy`) LLM
provider migration (epic `sase-50`, plan
`sdd/epics/202606/agy_provider_mvp.md`). It proves the migration works as a real
SASE provider — not just as isolated unit tests — and pins the remaining
non-parity to missing upstream `agy` machine-readable output rather than SASE
architecture.

## Environment

- Local `agy`: `/home/bryan/.local/bin/agy`, version `1.0.10`.
- Workspace: `sase_10` ephemeral clone; `just install` run before checks.

## What Was Verified

### 1. Targeted provider suites (green)

Ran the focused suites the plan calls out first:

- `tests/test_llm_provider_agy.py` — provider subclassing, tier resolution,
  exact argv construction, env-var precedence (`SASE_LLM_*` before `SASE_AGY_*`),
  `SASE_AGY_PATH`, `SASE_AGY_PRINT_TIMEOUT`, missing-executable diagnostics,
  non-zero exit handling, interrupt resume-prompt reconstruction, fake-CLI live
  reply capture, and no-shell-interpolation of quote/newline/space prompts.
- `tests/test_agy_integration_polish.py` — registry metadata, autodetect slot
  (`priority=30`), nested `agy/<model>` resolution with spaces/parens, model
  picker, prompt-panel/badge styling, temporary + worker overrides, retry
  defaults, skill-init routing to `~/.gemini/antigravity-cli/skills/`, and the
  provider-neutral commit-skill resolution.
- `tests/test_llm_provider_registry.py`, `tests/test_llm_provider_providers.py`,
  `tests/test_llm_provider_core.py`.
- `tests/doctor/test_checks_providers.py` — actionable missing-`agy` and clean
  found-`agy` doctor output (`SASE_AGY_PATH` derived, `Antigravity CLI` setup
  hint, model resolutions incl. the space/paren display name).
- `tests/llm_provider/test_temporary_override_resolution.py`,
  `tests/main/test_init_skills_sources.py`,
  `tests/main/test_init_skills_target_paths.py`,
  `tests/test_model_picker_modal.py`,
  `tests/ace/tui/tools/test_reader_agy.py` (Phase 5 Tools-panel parity gate),
  `tests/test_gemini_active_surface_guard.py` (Phase 6 removal guard).

All 166 targeted tests passed.

### 2. Large-prompt `--print` argv guard (green)

The Phase 2 handoff left one transport gap: `agy --print` requires the full
prompt as one argv element, so very large SASE prompts could fail at the OS
argument-size boundary with an opaque spawn error. Phase 7 now closes that gap
inside `AgyProvider`:

- prompts are measured as UTF-8 bytes before `subprocess.Popen`;
- prompts above the conservative 120 KiB guard fail before spawning `agy`;
- the diagnostic explicitly says the limitation is `agy --print` argv
  transport and that Antigravity CLI does not yet document a stable
  stdin/prompt-file contract SASE can use as a fallback.

Unit coverage in `tests/test_llm_provider_agy.py` proves the oversized-prompt
path does not call `subprocess.Popen`.

### 3. Real minimal SASE invocation through `invoke_agent()`

Drove a real `agy` call through the full provider-neutral path
(`preprocess -> get_provider("agy") -> provider.invoke -> run_commit_finalizer
-> postprocess`) with `provider_name="agy"`, `model_tier="small"`
(`Gemini 3.5 Flash (Low)`), and `SASE_ARTIFACTS_DIR` set. Results:

- Returned useful content (the requested token, verbatim).
- Wrote `live_reply.md` into the artifacts dir with the reply content.
- Recorded provider/model metadata: `metadata_llm_provider="agy"`,
  `metadata_model="Gemini 3.5 Flash (Low)"` (the values handed to chat history).

This satisfies the Phase 7 acceptance: *a real `agy` smoke run returns useful
content, writes `live_reply.md`, and records provider/model metadata.*

### 4. Commit-finalizer smoke (controlled workspace)

Added `tests/llm_provider/test_commit_finalizer_agy.py`: a *real* `AgyProvider`
instance is driven through `run_commit_finalizer()` in a controlled git
workspace (only the `agy` subprocess boundary is stubbed). It proves there is no
`agy`-specific finalizer branch — the same provider-neutral orchestration that
finalizes Claude/Codex turns:

- Re-invokes the real `AgyProvider.invoke()` for a dirty workspace, the
  follow-up turn commits the leftover work, the tree goes clean, and the result
  is `finalized` (`passes=1`, shared `commit_finalizer_pass_1_*` artifacts).
- Short-circuits a clean workspace to `clean` (`passes=0`) without re-invoking
  `agy`.

### 5. `just check`

`just install` then `just check` pass (see the bead/commit for the run).

## Final Known Gaps (blocked on upstream `agy`)

Antigravity CLI 1.0.10 exposes no stable machine-readable contract (no
documented `--output-format stream-json`, JSON event mode, or stable
log/conversation schema). Because SASE will not scrape the human TUI rendering
to fabricate artifacts, the following remain unsupported and are documented in
`docs/llms.md#structured-artifacts-parity-gap`:

| Capability             | Status for `agy` MVP | Blocker                                   |
| ---------------------- | -------------------- | ----------------------------------------- |
| Final reply / resume   | Supported            | `live_reply.md` + timestamps, plain stdout|
| Tool-call timeline     | Unsupported          | No stable tool-use/tool-result events     |
| Usage accounting       | Unsupported          | No stable token counters in print mode    |
| Thinking extraction    | Unsupported          | No stable thinking/log schema             |

Each gap is a consequence of the upstream CLI surface, not of SASE's provider
architecture: the moment `agy` ships a stable output/log/conversation contract,
SASE can emit normalized `tool_calls.jsonl` / `usage.json` rows through the
existing provider-neutral readers with no panel or runner changes (pinned by
`tests/ace/tui/tools/test_reader_agy.py`).

## Fast-Follow (when upstream lands a contract)

1. Add `_subprocess_agy.py` structured parsing and (only if tool events are
   extractable without scraping) `_tool_call_agy.py`.
2. Normalize into the existing `tool_calls.jsonl` schema with `runtime="agy"`.
3. Write `usage.json` from stable token counters only.
4. Add fixtures captured from real `agy` output/logs.

## References

- Epic plan: `sdd/epics/202606/agy_provider_mvp.md`
- Migration research: `sdd/research/202606/agy_migration_consolidated.md`
- Provider docs: `docs/llms.md` (Antigravity (`agy`) Integration)
