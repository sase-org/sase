---
status: done
bead_id: sase-511j
prompt: sdd/prompts/202603/codex.md
---

# Plan: Add Codex (OpenAI CLI Agent) Provider to sase

## Context

The sase LLM provider system (`src/sase/llm_provider/`) supports pluggable backends via a registry pattern. Currently
two providers exist: Claude Code and Gemini CLI. The user wants to add Codex (OpenAI's terminal-based coding agent) as a
third provider, matching every feature supported by the existing two.

Codex CLI is invoked via `codex exec` for non-interactive use, supports `--json` NDJSON output, `--yolo` for
unrestricted mode, and `--ask-for-approval` for approval workflows.

---

## Phase 1: Core CodexProvider + Registration (Normal Mode)

**Goal**: Working `codex` provider for non-plan-mode invocations.

### Prerequisite: Verify CLI flags

Before writing any code, run `codex exec --help` and verify that all flags used in this plan exist: `--model`, `--yolo`,
`--json`, `--color never`, `--skip-git-repo-check`, `--sandbox`, `--ask-for-approval`, `--output-last-message`. Adapt
the plan if any flag names differ.

Also run `codex exec --json -m o4-mini - <<< "say hello"` and capture the NDJSON output to understand the event schema
for the parser.

### Files to Create

**`src/sase/llm_provider/codex.py`** (~150 lines)

- `_TIER_TO_MODEL = {"large": "o3", "small": "o4-mini"}` (defaults; user can override via `%model` directive)
- `CodexProvider(LLMProvider)`:
  - `resolve_model_name(model_tier)` - return tier-mapped model name
  - `invoke(prompt, *, model_tier, suppress_output, model_override)` - normal mode only (plan mode added in Phase 2)
  - `_run_subprocess(args, prompt, suppress_output)` - Popen with `stdin=PIPE, stdout=PIPE, stderr=PIPE, text=True`;
    write prompt to stdin then close it; delegate output streaming to the new NDJSON parser
- Command: `codex exec --model <model> --yolo --json --color never --skip-git-repo-check -`
  - `-` reads prompt from stdin (prompt is written to the stdin pipe, same as claude.py and gemini.py)
  - `--json` for structured NDJSON output (enables proper parsing)
  - `--color never` to avoid ANSI escape codes in captured output
- Extra args: check `SASE_LLM_LARGE_ARGS` then `SASE_CODEX_LARGE_ARGS` for large tier; check `SASE_LLM_SMALL_ARGS` then
  `SASE_CODEX_SMALL_ARGS` for small tier (same pattern as claude.py lines 119-126)
- Timer: `gemini_timer("Waiting for Codex")` (reuse existing timer from `rich_utils.py`)

### Files to Modify

**`src/sase/llm_provider/_subprocess.py`** - Add `stream_and_parse_codex_json_output()` (~60 lines)

- New function + `_process_codex_json_line()` helper
- Codex NDJSON event parsing (extract assistant message content from response events)
- Return signature: `(str, str, int)` — (assistant_text, stderr_content, return_code), same as
  `stream_and_parse_json_output()`
- Use the same `select.select()` non-blocking streaming pattern as the existing functions
- The NDJSON event schema must be determined empirically from the prerequisite step above; example expected events:
  message creation, content delta, message complete — extract text from content events

**`src/sase/llm_provider/registry.py`**

- In `_register_builtin_providers()`: add `from .codex import CodexProvider` and
  `register_provider("codex", CodexProvider)`
- In `get_default_provider_name()`: add `shutil.which("codex")` check between claude and gemini (priority: claude >
  codex > gemini)

### Verification

- `just install && just lint && just test` all pass
- Existing tests remain green

---

## Phase 2: Plan Mode + Shared Plan Utilities

**Goal**: Two-phase plan/implement flow matching Claude and Gemini providers, with shared utilities extracted to avoid
code duplication.

### Step 1: Extract shared plan utilities into `_plan_utils.py`

**Create `src/sase/llm_provider/_plan_utils.py`** (~120 lines)

Extract the following functions that are currently duplicated (or nearly so) across claude.py and gemini.py:

- `save_plan_to_sase(plan_file: str) -> Path` — copy a plan file to `~/.sase/plans/` with conflict resolution (currently
  gemini.py `_save_plan_to_sase()` lines 69-83, near-identical logic in claude.py lines 266-278)
- `write_plan_path_artifact(saved_plan_path: Path) -> None` — write `plan_path.json` to `SASE_ARTIFACTS_DIR` (currently
  gemini.py `_write_plan_path_artifact()` lines 86-91, near-identical logic in claude.py lines 282-287)
- `handle_plan_approval(plan_file: str | None, session_id: str) -> str | None` — TUI notification, desktop notification,
  tmux bell, polling loop (currently gemini.py `_handle_plan_approval()` lines 99-178)
- `read_plan_feedback(approval_dir: Path) -> str | None` — read rejection feedback from `plan_response.json` (currently
  claude.py `_read_plan_feedback()` lines 47-63)
- `append_plan_feedback_log(feedback: str, round_num: int) -> None` — append to `plan_feedback.jsonl` (currently
  claude.py `_append_plan_feedback_log()` lines 66-81)
- `save_response_as_plan(text: str, provider_name: str) -> str` — save response text as a plan .md file in
  `~/<provider_dir>/plans/` (currently gemini.py `_save_response_as_plan()` lines 56-66; parameterize the directory)

After extraction, update gemini.py and claude.py to import from `_plan_utils.py` instead of using their local copies.
Run `just lint && just test` to verify the refactor is clean.

### Step 2: Implement Codex plan mode

**`src/sase/llm_provider/codex.py`** - Add `_invoke_plan_mode()` (~180 lines)

#### Phase 1 (Planning):

- Command:
  `codex exec --model <model> --ask-for-approval on-request --sandbox read-only --json --color never --skip-git-repo-check --output-last-message <tmpfile> -`
  - `--output-last-message <tmpfile>` captures the final response (plan text) to a temp file
  - `--sandbox read-only` restricts to read-only operations during planning
  - `--ask-for-approval on-request` requires approval for any write actions (belt and suspenders with sandbox)
- Plan text capture fallback chain (in priority order):
  1. Check `--output-last-message` temp file for plan text
  2. Search `~/.codex/` for `.md` plan files modified after `start_time` (via `_find_codex_plan_file(after=start_time)`)
  3. Use the streamed response text directly
  4. If none of the above produce content, raise `RuntimeError`
- Save plan: `save_plan_to_sase()` from `_plan_utils.py`, then `write_plan_path_artifact()`

#### Plan approval:

- Call `handle_plan_approval()` from `_plan_utils.py` (polls for user response, sends desktop notification + tmux bell)
- If rejected, returns plan text only (no implementation phase)

#### Plan feedback retry loop (up to 5 rounds):

- When `handle_plan_approval()` returns `None` (rejected):
  - Call `read_plan_feedback()` to check for feedback text in `plan_response.json`
  - If feedback exists: call `append_plan_feedback_log()`, rebuild prompt with previous plan + feedback appended (same
    pattern as claude.py lines 217-232), clean up old approval directory, re-run phase 1
  - If no feedback: return plan text only (user rejected without feedback)
- Loop structure: `for retry_round in range(MAX_RETRIES + 1): ...` wrapping both phase 1 execution and approval

#### Phase 2 (Implementation):

- Command: `codex exec --model <model> --yolo --json --color never --skip-git-repo-check -`
- Prompt: plan content + "The above plan has been reviewed and approved. Implement it now."
- Combine phase 1 + phase 2 response text (same as claude.py line 352)

#### Sidecar link:

Not implemented for Codex. The `.impl_session` sidecar link in claude.py (lines 294-302) is specific to Claude Code's
session management for the thinking panel — Codex has no equivalent session concept. If Codex adds session support in
the future, this can be revisited.

### Step 3: Update cross-provider plan file search

**`src/sase/llm_provider/claude.py`** - Add `~/.codex/plans/` to `_find_plan_file()` search dirs (line 35)

This allows Claude's plan file search to discover plans generated by Codex sessions, maintaining cross-provider plan
visibility.

### Verification

- `just install && just lint && just test` all pass
- Verify gemini.py and claude.py still work correctly after the `_plan_utils.py` refactor (existing tests should catch
  regressions)
- Manual test with `SASE_AGENT_PLAN_MODE=1` triggers plan flow

---

## Phase 3: Tests, Documentation, and Config

**Goal**: Full test coverage, documentation, and config updates.

### Files to Modify

**`tests/test_llm_provider_providers.py`** - Add ~130 lines:

Provider tests:

- `test_codex_provider_is_llm_provider()` - isinstance check (pattern: line 36)
- `test_codex_provider_resolve_model_name()` - verify tier mapping: large→o3, small→o4-mini (pattern: line 122)
- `test_codex_provider_extra_args_from_env_small()` - mock Popen + stream, verify `SASE_CODEX_SMALL_ARGS` parsed
  (pattern: line 81)
- `test_codex_provider_extra_args_generic_env()` - verify `SASE_LLM_LARGE_ARGS` takes precedence over
  `SASE_CODEX_LARGE_ARGS`
- `test_codex_provider_raises_on_failure()` - mock non-zero exit (pattern: line 138)
- `test_codex_provider_model_override()` - verify `model_override` bypasses tier map

Registry tests:

- `test_registry_auto_detect_codex()` - mock `shutil.which` to return codex but not claude, verify "codex" selected
- `test_registry_auto_detect_priority()` - mock `shutil.which` to return both claude and codex, verify "claude" wins

NDJSON parser tests:

- `test_codex_json_parser_extracts_text()` - feed sample NDJSON events (from the Phase 1 prerequisite investigation) to
  `stream_and_parse_codex_json_output()` via a mock process, verify assistant text is extracted correctly
- `test_codex_json_parser_handles_malformed_lines()` - verify graceful handling of non-JSON lines mixed with valid
  events

Shared plan utilities tests (if not already covered by existing tests):

- `test_save_plan_to_sase_conflict_resolution()` - verify name conflict handling when dest already exists
- `test_write_plan_path_artifact_no_artifacts_dir()` - verify no-op when `SASE_ARTIFACTS_DIR` not set

**`docs/llms.md`** - Add ~100 lines:

- "Codex CLI Integration" section (after Claude, before Gemini):
  - Command construction: `codex exec --model <model> --yolo --json --color never --skip-git-repo-check -`
  - Model mapping table: large→o3, small→o4-mini
  - Plan mode behavior: two-phase with restricted sandbox + external approval
- Codex-specific environment variables table:
  - `SASE_CODEX_LARGE_ARGS` — extra CLI args for large tier (Codex-specific fallback)
  - `SASE_CODEX_SMALL_ARGS` — extra CLI args for small tier (Codex-specific fallback)
- Update Source Layout table: add codex.py and \_plan_utils.py rows
- Update Selection Logic section: claude > codex > gemini
- Update registry code example to show 3 providers
- Update Subprocess Streaming section to mention Codex NDJSON streaming

### Verification

- `just check` passes (fmt-check + lint + test including new tests)
- Documentation is accurate and consistent with the implementation

---

## Key Design Decisions

| Decision              | Choice                                                                           | Rationale                                                                                                                                                                                                       |
| --------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Output parsing        | New `stream_and_parse_codex_json_output()` in `_subprocess.py`                   | Codex NDJSON events differ from Claude's schema; separate parser avoids fragile conditionals                                                                                                                    |
| Plan mode pattern     | Gemini-style external approval + Claude-style feedback retry                     | Codex has no native plan-only mode; external approval with restricted sandbox achieves the same effect; feedback retry ensures feature parity with Claude                                                       |
| Shared plan utilities | Extract to `_plan_utils.py` in Phase 2                                           | `_save_plan_to_sase`, `_handle_plan_approval`, `_write_plan_path_artifact`, and feedback helpers are near-identical across providers; extracting avoids a third copy and makes all providers easier to maintain |
| Auto-detect priority  | claude > codex > gemini                                                          | Claude is the most mature integration; Codex on PATH indicates explicit install                                                                                                                                 |
| Default models        | large=`o3`, small=`o4-mini`                                                      | Current OpenAI reasoning/efficient models; overridable via `%model` directive                                                                                                                                   |
| Plan feedback retry   | Yes, up to 5 rounds (like Claude)                                                | Feature parity requirement                                                                                                                                                                                      |
| Sidecar link          | Skip for Codex                                                                   | `.impl_session` is Claude-specific for the thinking panel; Codex has no equivalent session concept                                                                                                              |
| Plan text capture     | `--output-last-message` primary, disk search fallback, response text last resort | Codex may not write plan files to a known directory like Gemini does; `--output-last-message` is the most reliable mechanism                                                                                    |

## Critical Files Reference

| File                                   | Role                                                                           |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| `src/sase/llm_provider/claude.py`      | Primary pattern: complex provider w/ plan mode, feedback retry, JSON streaming |
| `src/sase/llm_provider/gemini.py`      | Secondary pattern: plan mode w/ external approval polling                      |
| `src/sase/llm_provider/_subprocess.py` | Extend with Codex NDJSON parser                                                |
| `src/sase/llm_provider/_plan_utils.py` | New: shared plan utilities extracted from claude.py and gemini.py (Phase 2)    |
| `src/sase/llm_provider/registry.py`    | Register + update auto-detection                                               |
| `src/sase/llm_provider/base.py`        | Interface to implement                                                         |
| `tests/test_llm_provider_providers.py` | Extend with Codex + shared utility tests                                       |
| `docs/llms.md`                         | Extend with Codex documentation                                                |
