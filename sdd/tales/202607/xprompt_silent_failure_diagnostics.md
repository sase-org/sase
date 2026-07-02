---
create_time: 2026-07-02 15:57:04
status: done
prompt: sdd/prompts/202607/xprompt_silent_failure_diagnostics.md
---
# Plan: Make xprompt silent failures loud — unresolved-reference warnings + definition load-error surfacing

## Background

The blog launch readiness audit (`sdd/research/202607/blog_launch_readiness_audit.md`, concern #2) found that the
xprompt authoring journey fails silently in every common mistake mode. This plan addresses the two requested items of
the recommended pre-launch scope:

- **(a)** Warn at expansion/launch time when a `#name`-shaped token survives expansion unresolved. Today the expander
  simply skips unknown references (`src/sase/xprompt/processor.py:397-407` — `break` when no known xprompt is present,
  `continue` per unknown match), so a typo like `#reviewww` — or a reference to an xprompt whose definition failed to
  load — is sent to the LLM as literal text with zero feedback.
- **(b)** Surface definition load errors in `sase xprompt list` and `sase doctor` with `skipped: <file>: <error>` lines.
  Today a workflow YAML parse error returns `None` (`src/sase/xprompt/workflow_loader.py:253-262`), load-time workflow
  validation errors are swallowed (`workflow_loader.py:200-201`), broken markdown frontmatter is silently treated as
  body text (`src/sase/xprompt/loader_parsing.py:50-52`), and a project `sase.yml` load failure logs at debug only
  (`src/sase/xprompt/loader_sources.py:468-473`). One YAML typo and the xprompt just doesn't exist — nowhere the user
  looks says why.

Item (c) of the audit's scope (fixing the draft `xprompts-in-depth.md` blog post) is **explicitly out of scope** — that
draft will likely be deleted. The audit's third bullet (name-shadowing warnings) is also out of scope.

**Rust core boundary note:** xprompt discovery and expansion live entirely in Python in this repo (only frontmatter
schema validation touches `sase_core_rs`). This work adds diagnostics around that existing Python pipeline, so no
`sase-core` changes are required.

## Goals

1. A user who launches a prompt containing an unresolved `#name`-shaped token gets a visible, non-blocking warning at
   launch time — from `sase run`, from `sase xprompt expand`, and from the `sase ace` TUI prompt input.
2. A user whose xprompt/workflow definition file fails to load sees exactly which file was skipped and why, in both
   `sase xprompt list` and `sase doctor`.
3. Zero behavior change otherwise: launches still proceed, expansion output is unchanged, `sase xprompt list` stdout
   remains machine-parseable JSON, and hot paths (TUI, completion) pay no new cost.

## Non-goals

- Blocking or erroring on unknown references (prose like `#include` at line start can look reference-shaped; this is a
  warning, never a launch failure).
- Name-shadowing/collision warnings (audit bullet 3).
- Warning surfaces inside detached agent child processes, axe-driven launches, or workflow-step execution (the three
  interactive surfaces above cover the launch-week user journey; child-side surfacing can be a follow-up).
- Fixing or publishing the draft blog post (item (c)).

---

## Part A — Warn when a `#name`-shaped token survives expansion unresolved

### A1. New scanner module: `src/sase/xprompt/unresolved.py`

Pure logic, no I/O side effects, modeled on the existing reference scanner
`src/sase/xprompt/used_xprompts.py:collect_used_xprompts` (which already demonstrates the correct normalization +
protection + lexical-scan recipe). Two-level API:

1. `find_unresolved_reference_names(expanded_text, *, extra_xprompts=None) -> tuple[str, ...]` Scans
   **already-expanded** text. Steps:
   - Fast path: return `()` when `"#" not in expanded_text`.
   - Apply the same normalization expansion applies: `resolve_xprompt_aliases`, `normalize_vcs_underscore_refs`.
   - Compute ignored ranges via `fenced_block_ranges` + `disabled_region_ranges` and skip references inside them (same
     as `used_xprompts.py`).
   - Iterate `iter_xprompt_references()` (`src/sase/xprompt/_parsing_references.py`) and flag a reference name as
     unresolved when it is **none** of:
     - a known xprompt or workflow — check against `get_all_prompts()` plus `extra_xprompts`/workflow-local definitions
       (workflows must count as resolved: standalone `#!name` and embedded workflow references are intentionally
       consumed _after_ xprompt expansion);
     - a VCS workflow reference — match against `get_ref_patterns()` and `get_workflow_names()` from
       `sase.workspace_provider`, plus known-project refs via `extract_known_project_vcs_ref` (covers `#git:...`,
       `#gh:...`, `#cd:...`, `#<project>:ref`, and underscore-normalized forms);
     - an agent fork/resume reference (`#fork`/`#resume` grammar, `src/sase/agent/multi_prompt_reference_resume.py`).
   - Dedupe while preserving first-seen order.
2. `scan_query_for_unresolved_references(query) -> tuple[str, ...]` Convenience wrapper for launch surfaces holding the
   **raw** query: parse via `parse_multi_prompt` (to pick up frontmatter-local xprompts and `---` segments), expand each
   segment with `process_xprompt_references(..., extra_xprompts=local_xprompts)`, then scan each expanded segment with
   (1) and merge/dedupe results. **Exception-safe by contract:** any exception during parsing/expansion (including
   `SystemExit` from expansion errors) is caught and yields `()` — the scanner must never fail or alter a launch; the
   real launch path surfaces real errors itself.

Also provide a small message formatter shared by all surfaces, including a did-you-mean suggestion via
`difflib.get_close_matches` against the known-name set, e.g.:

```
unknown xprompt reference '#reviewww' will be passed to the agent as literal text
(did you mean '#review'? run 'sase xprompt list' to see available names)
```

### A2. Surface 1 — `sase run` (CLI)

In `launch_query` (`src/sase/main/query_handler/_launch.py`), directly alongside the existing pre-launch
`missing_required_input_names` scan (the established precedent for parent-process prompt checks): call
`scan_query_for_unresolved_references(query)` and, for each finding, emit `print_status(..., "warning")`
(`src/sase/output.py`). Non-blocking — the launch proceeds and still prints `Agent started (PID ...)`.

### A3. Surface 2 — `sase xprompt expand` (CLI)

In `_handle_expand` (`src/sase/main/xprompt_handler.py:28-59`): after computing the fully-processed text, run the
scanner on it (the expansion already happened here, so use `find_unresolved_reference_names` with the parsed local
xprompts) and print warnings to **stderr** — stdout must remain exactly the expanded prompt.

### A4. Surface 3 — `sase ace` TUI prompt launch

The TUI launch already runs as a tracked background task with a synchronous worker body and UI-thread completion effects
(`LaunchTaskMixin`, `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` / `_launch_multi_prompt.py`). Run the scan
inside the existing worker body (off the event loop — no new work on the render/keypress path, per the TUI perf rules),
thread any findings through the launch outcome, and surface them in `on_complete` via
`self.notify(..., severity="warning")`. Keep it to one aggregated toast per launch (e.g.
`Unknown xprompt reference(s): #reviewww, #fooo — passed through as literal text`).

### A5. Performance & noise considerations

- Every surface takes the `"#" not in prompt` fast path first.
- `sase run`/TUI launches with references already pay a catalog load for multi-agent expansion; the scan reuses the same
  loader calls (per-call `get_all_prompts()`); no caching changes are needed.
- False positives (prose hashtags such as `#include` at start of line) are accepted by design: warning-only, fenced code
  blocks and disabled regions are already excluded, and mid-word `#` (URLs like `.../page#anchor`) never matches the
  reference grammar's leading-context rule.

---

## Part B — Surface definition load errors in `sase xprompt list` and `sase doctor`

### B1. New issue collector: `src/sase/xprompt/load_issues.py`

The loaders (`get_all_xprompts`/`get_all_workflows`/`get_all_prompts`) are called from many hot paths (completion,
expansion, TUI), so error collection must be zero-cost unless a diagnostic caller opts in. Use a `contextvars`-based
collector:

- `XPromptLoadIssue` frozen dataclass: `source` (file path or source label), `error` (human-readable reason), `kind`
  (`"workflow"`, `"frontmatter"`, `"config"`, `"step_import"`, ...).
- `record_load_issue(source, error, *, kind)` — no-op when no collector is active.
- `collect_xprompt_load_issues()` context manager — activates a fresh list and yields it; **dedupes** on
  `(source, error)` because a single diagnostic pass loads the same file several times (`get_all_prompts` +
  `get_all_xprompts` + `get_all_workflows`).

### B2. Instrument the silent-failure sites (record, keep existing behavior)

Workflow YAML (`src/sase/xprompt/workflow_loader.py`):

- `_load_workflow_from_file` (:244-262): `OSError`/`yaml.YAMLError` → record with the exception message; top-level YAML
  not a mapping → record `"top-level YAML is not a mapping"`. Still return `None`.
- `_load_workflow_from_mapping`: swallowed `WorkflowValidationError` (:200-201) → record `str(exc)`; `steps` not a list
  / no steps parsed (:176-177, :203-204) → record. (The deferred `validate_workflow_variables` pass at :234-239
  intentionally defers to runtime and still returns a workflow — leave untouched.)
- `_resolve_step_imports` / `_load_step_definition` (:46-109): a missing/failed `use:` import currently drops the step
  with only a debug-level `log.warning` → also record an issue naming the workflow file and the `use:` ref.

Markdown xprompts (`src/sase/xprompt/loader_parsing.py`, `src/sase/xprompt/loader_sources.py`):

- `parse_yaml_front_matter` (:19-60) currently makes "invalid YAML" indistinguishable from "no frontmatter". Add an
  error-aware variant (or optional out-param) that reports the `yaml.YAMLError`; keep the existing public signature and
  behavior for all other callers (it is also used on raw user prompts, where fallback-to-body is legitimate).
- `load_xprompt_from_file` (`loader_sources.py:60-111`): use the error-aware variant and record
  `<file>: invalid YAML frontmatter (treated as plain body): <error>`; record `OSError` read failures too.
- `load_project_local_xprompts` (`loader_sources.py:455-487`): record the swallowed `sase.yml` read/parse failure.
- `parse_xprompt_entries` (`loader_parsing.py:367-439`): entries silently skipped by the `continue` branches (non-string
  name, non-string `content`, value neither string nor dict) → record with the source label and entry name. (Whole-file
  config-layer YAML errors are already covered by the existing `config.layers` doctor check.)

### B3. `sase xprompt list` surfacing

In `_handle_list` (`src/sase/main/xprompt_handler.py:62-154`): wrap the three loader calls in
`collect_xprompt_load_issues()`. Print the JSON to **stdout unchanged**, then one line per issue to **stderr**:

```
skipped: /home/user/xprompts/review.yml: mapping values are not allowed here (line 3)
```

stderr keeps the documented `sase xprompt list | jq` contract and any programmatic consumers intact while making the
failure visible in an interactive terminal.

### B4. `sase doctor` surfacing

Add a new check to `src/sase/doctor/checks_config.py` following the `config.model_xprompts` pattern:

- id `config.xprompt_definitions`, group `config`, title "XPrompt definitions".
- Runner activates the collector, calls `get_all_prompts()` (and `get_all_project_local_prompts()` so registered
  projects' `sase.yml` xprompts are validated too), and reports:
  - `OK` — `"N xprompt/workflow definition(s) loaded cleanly"`.
  - `WARN` — `"<M> xprompt definition file(s) skipped or degraded"` with `skipped: <file>: <error>` detail lines (capped
    at `_MAX_DETAIL_ROWS`), full issue list in `data`, and next_steps pointing at fixing the reported files and
    rerunning `sase doctor -C config.xprompt_definitions`.

This composes with part (a): an xprompt that fails to load then triggers the unresolved-reference warning at launch, and
doctor/list explain _why_ it is missing.

---

## Testing

Part A:

- New `tests/test_xprompt_unresolved_references.py` (unit tests for the scanner): unknown name flagged; known
  xprompt/workflow/local-frontmatter-xprompt not flagged; alias-resolved names not flagged; VCS refs (`#git:x`,
  `#cd:/x`, `#<project>:ref`), `#fork`/`#resume` not flagged; fenced blocks and disabled regions ignored; `#123` and
  mid-word `#` never match; dedupe and ordering; exception safety (expansion error → `()`).
- `launch_query` warning path: extend the existing query-handler launch tests to assert the warning prints and the
  launch still proceeds.
- `sase xprompt expand`: extend `tests/main/test_xprompt_handler.py` — warning on stderr, expanded text on stdout
  byte-identical to today.
- TUI: one test in the launch-action suite asserting the outcome carries findings and a warning toast is emitted (reuse
  existing launch-task test helpers).

Part B:

- New collector unit tests: inactive collector is a no-op; active collector records and dedupes.
- Loader instrumentation tests (extend `tests/test_workflow_loaders.py`, `tests/test_workflow_loader_step_imports.py`,
  `tests/test_xprompt_loader_parsing.py`): broken workflow YAML records an issue and still returns `None`; >1
  prompt_part validation error records; missing `use:` import records; bad markdown frontmatter records and the xprompt
  still loads with body fallback; broken project `sase.yml` records; skipped config entries record.
- `sase xprompt list`: extend `tests/main/test_xprompt_handler.py` — stdout is valid JSON, `skipped:` lines appear on
  stderr only when a broken definition exists.
- Doctor: extend `tests/doctor/test_checks_config.py` — OK with a clean tree, WARN with detail lines when a broken
  definition file is planted.

Run `just install` then `just check` before finishing (per repo instructions).

## Docs

- `docs/xprompt.md`: short troubleshooting subsection — unknown-reference warnings at launch, and `sase xprompt list` /
  `sase doctor -C config.xprompt_definitions` as the way to find broken definitions.
- No new CLI subcommands or options are added, so no CLI-docs/completion updates are triggered.

## Risks & edge cases

- **False-positive warnings on prose hashtags**: mitigated by warning-only semantics, fenced/disabled-region exclusion,
  and the reference grammar's leading-context rule; accepted per the audit ("a warning is enough").
- **`sase xprompt list` consumers**: stdout JSON is byte-for-byte unchanged; new lines go to stderr only.
- **Hot-path cost**: collector is contextvar-gated (no cost when inactive); scanner runs only at launch/expand
  boundaries with a `#` fast path; TUI scan runs in the existing tracked-task worker thread, never on the event loop.
- **Recording sites must not change load results**: every instrumentation point records and then preserves the current
  return value/fallback exactly; loader behavior tests above pin this.
- **Duplicate issues across repeated loader passes**: deduped in the collector on `(source, error)`.

## Acceptance criteria

1. `sase run "do X #reviewww"` prints a yellow warning naming `#reviewww` (with a did-you-mean suggestion when one
   exists) and still launches the agent.
2. `sase xprompt expand "#reviewww"` writes the literal text to stdout and the warning to stderr.
3. Submitting a prompt with an unknown reference from the `sase ace` prompt input shows a warning toast.
4. With a workflow YAML containing a syntax error in `xprompts/`, `sase xprompt list` prints a
   `skipped: <file>: <error>` line to stderr (stdout JSON unchanged) and `sase doctor` shows a WARN
   `config.xprompt_definitions` check with the same line; both are OK/silent on a clean tree.
5. `just check` passes.
