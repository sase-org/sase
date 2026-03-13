---
status: draft
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

### Files to Create

**`src/sase/llm_provider/codex.py`** (~150 lines)

- `_TIER_TO_MODEL = {"large": "o3", "small": "o4-mini"}` (defaults; user can override via `%model` directive)
- `CodexProvider(LLMProvider)`:
  - `resolve_model_name(model_tier)` - return tier-mapped model name
  - `invoke(prompt, *, model_tier, suppress_output, model_override)` - normal mode only (plan mode added in Phase 2)
  - `_run_subprocess(args, prompt, suppress_output)` - Popen, stdin write, stream output
- Command: `codex exec --model <model> --yolo --json --color never --skip-git-repo-check -`
  - `-` reads prompt from stdin
  - `--json` for structured NDJSON output (enables proper parsing)
  - `--color never` to avoid ANSI escape codes in captured output
- Extra args: check `SASE_LLM_LARGE_ARGS` then `SASE_CODEX_LARGE_ARGS` (same pattern as claude.py lines 119-126)
- Timer: `gemini_timer("Waiting for Codex")` (reuse existing timer from `rich_utils.py`)

### Files to Modify

**`src/sase/llm_provider/_subprocess.py`** - Add `stream_and_parse_codex_json_output()` (~60 lines)

- New function + `_process_codex_json_line()` helper
- Codex NDJSON event parsing (extract assistant message content)
- Same return signature: `(str, str, int)`
- **NOTE**: The implementer should first run `codex exec --json -m o4-mini - <<< "say hello"` to inspect the actual
  event schema before writing the parser

**`src/sase/llm_provider/registry.py`**

- In `_register_builtin_providers()`: add `from .codex import CodexProvider` and
  `register_provider("codex", CodexProvider)`
- In `get_default_provider_name()`: add `shutil.which("codex")` check between claude and gemini (priority: claude >
  codex > gemini)

### Verification

- `just install && just lint && just test` all pass
- Existing tests remain green

---

## Phase 2: Plan Mode

**Goal**: Two-phase plan/implement flow matching Claude and Gemini providers.

### Approach

Follow Gemini's external approval pattern (gemini.py lines 262-373):

- Phase 1: Run with restricted mode to generate plan
- Poll for user approval via `_handle_plan_approval()` (gemini.py lines 99-178)
- Phase 2: Run with `--yolo` to implement

### Files to Modify

**`src/sase/llm_provider/codex.py`** - Add `_invoke_plan_mode()` (~200 lines)

- Phase 1 command:
  `codex exec --model <model> --ask-for-approval on-request --sandbox read-only --json --color never --skip-git-repo-check --output-last-message <tmpfile> -`
  - `--output-last-message` captures final response (plan text) to a file
  - `--sandbox read-only` restricts to read-only operations
- Plan file handling:
  - `_find_codex_plan_file()` - search `~/.codex/` for .md plan files (with `after` timestamp filter, like gemini.py
    line 34)
  - Fall back to `--output-last-message` captured file or response text
  - `_save_response_as_plan()` - save as `.md` in `~/.codex/plans/` (like gemini.py line 56)
  - Copy to `~/.sase/plans/` via `_save_plan_to_sase()` (like gemini.py line 69)
  - Write `plan_path.json` artifact (like gemini.py line 86)
- Plan approval: reuse pattern from gemini.py's `_handle_plan_approval()` (lines 99-178)
  - Poll `~/.sase/plan_approval/<session_id>/plan_response.json`
  - Desktop notification + tmux bell
  - Auto-approve check
- Plan feedback retry loop (up to 5 rounds, matching claude.py lines 145-236):
  - Read feedback from `plan_response.json`
  - Append to `plan_feedback.jsonl`
  - Re-launch phase 1 with feedback appended to prompt
- Phase 2 command: `codex exec --model <model> --yolo --json --color never --skip-git-repo-check -`
  - Prompt includes plan content + "implement it now" instruction
- Combine phase 1 + phase 2 responses

**`src/sase/llm_provider/claude.py`** - Add `~/.codex/plans/` to `_find_plan_file()` search dirs (line 35)

### Verification

- `just install && just lint && just test` all pass
- Manual test with `SASE_AGENT_PLAN_MODE=1` triggers plan flow

---

## Phase 3: Tests, Documentation, and Config

**Goal**: Full test coverage, documentation, and config updates.

### Files to Modify

**`tests/test_llm_provider_providers.py`** - Add ~100 lines:

- `test_codex_provider_is_llm_provider()` - isinstance check (pattern: line 36)
- `test_codex_provider_resolve_model_name()` - verify tier mapping (pattern: line 122)
- `test_codex_provider_extra_args_from_env_small()` - mock Popen + stream, verify SASE_CODEX_SMALL_ARGS parsed (pattern:
  line 81)
- `test_codex_provider_raises_on_failure()` - mock non-zero exit (pattern: line 138)
- `test_codex_provider_model_override()` - verify model_override bypasses tier map
- `test_registry_auto_detect_codex()` - mock shutil.which, verify claude > codex > gemini priority

**`docs/llms.md`** - Add ~80 lines:

- "Codex CLI Integration" section (after Claude, before Gemini)
- Command construction, model mapping table, env vars table
- Plan mode behavior description
- Update Source Layout table (add codex.py row)
- Update Selection Logic section (claude > codex > gemini)
- Update registry code example to show 3 providers

### Verification

- `just check` passes (fmt-check + lint + test including new tests)
- Documentation is accurate and consistent

---

## Key Design Decisions

| Decision             | Choice                                                         | Rationale                                                                                              |
| -------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Output parsing       | New `stream_and_parse_codex_json_output()` in `_subprocess.py` | Codex NDJSON events differ from Claude's schema; separate parser avoids fragile conditionals           |
| Plan mode pattern    | Gemini-style external approval                                 | Codex has no native plan-only mode; external approval with restricted sandbox achieves the same effect |
| Auto-detect priority | claude > codex > gemini                                        | Claude is the most mature integration; Codex on PATH indicates explicit install                        |
| Default models       | large=`o3`, small=`o4-mini`                                    | Current OpenAI reasoning/efficient models; overridable via `%model` directive                          |
| Plan feedback retry  | Yes, up to 5 rounds (like Claude)                              | Feature parity requirement                                                                             |

## Critical Files Reference

| File                                   | Role                                                                           |
| -------------------------------------- | ------------------------------------------------------------------------------ |
| `src/sase/llm_provider/claude.py`      | Primary pattern: complex provider w/ plan mode, feedback retry, JSON streaming |
| `src/sase/llm_provider/gemini.py`      | Secondary pattern: plan mode w/ external approval polling                      |
| `src/sase/llm_provider/_subprocess.py` | Extend with Codex NDJSON parser                                                |
| `src/sase/llm_provider/registry.py`    | Register + update auto-detection                                               |
| `src/sase/llm_provider/base.py`        | Interface to implement                                                         |
| `tests/test_llm_provider_providers.py` | Extend with Codex tests                                                        |
| `docs/llms.md`                         | Extend with Codex documentation                                                |
