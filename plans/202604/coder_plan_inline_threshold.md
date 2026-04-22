---
create_time: 2026-04-22 16:48:37
status: done
---

# Gate the `@` plan-file prefix on plan length

## Problem

Coder agents are hitting "Prompt is too long" errors with meaningful frequency. The coder prompt is built in
`src/sase/axe/run_agent_exec_plan.py:409-414` as:

```python
state.current_prompt = (
    f"{model_prefix}{resume_prefix}{vcs_prefix}"
    f"@{plan_data['plan_file']}\n\n"
    "The above plan has been reviewed and approved. "
    f"Implement it now.{coder_extra}\n{embedded_refs}"
)
```

The leading `@` tells the agent runtime to inline the full plan file content into the initial user message. For small
plans this is convenient — the coder sees the plan immediately. For large plans (and for plans combined with heavy
dynamic-memory / tier-1 memory expansion) the inlined content blows past the model's prompt budget.

## Goal

Only inline the plan via `@` when the plan file is at most N lines. When the plan is larger, mention the path but let
the coder `Read` the file as a tool call. Users can override the threshold in `sase.yml`.

Explicitly out of scope: changing how the planner writes plans, truncating plans, or changing the coder xprompt.

## Data → default threshold

Line counts for the 175 plan files in `~/.sase/plans/` created in the last 14 days:

| Percentile | Lines |
| ---------- | ----- |
| 50th       | ~70   |
| 75th       | ~100  |
| 90th       | ~200  |
| 95th       | ~280  |
| Max        | 847   |

Only three plans exceed 300 lines (`commit_resume.md` at 470, `repeat_agents_as_entries.md` at 814, `commit_resume_1.md`
at 847) — a natural gap between typical and outlier sizes. **Default: `300` lines.** This preserves `@` convenience for
~98% of real plans while catching the outliers most likely to trigger prompt-too-long errors. Users who want a tighter
budget (e.g. when combined with large dynamic memory context) can lower it to 200; users who care less can raise it.

## Design

### Config field

Add under the existing `axe:` section in `src/sase/default_config.yml`:

```yaml
axe:
  # ... existing fields ...
  coder_plan_inline_max_lines: 300
```

Name rationale: the field is specific to the coder prompt and the `@` inline mechanism. Placing it under `axe` matches
where other agent-execution knobs live (`max_agent_runners`, `zombie_timeout_seconds`). Zero or a negative value
disables `@` inlining entirely (always reference-by-path).

### Prompt construction

In `handle_plan_marker()` (around line 409), branch on whether the plan file has at most `coder_plan_inline_max_lines`
lines:

- **At or below threshold**: current behavior —
  `@{plan_file}\n\nThe above plan has been reviewed and approved. Implement it now.`
- **Above threshold**: drop the `@`, mention the path, and instruct the coder to read it:
  `The plan at {plan_file} has been reviewed and approved. Read it and implement it now.`

The `model_prefix`, `resume_prefix`, `vcs_prefix`, `coder_extra`, and `embedded_refs` wrappers are unchanged in both
branches.

Line counting: `len(Path(plan_file).read_text(encoding="utf-8").splitlines())`. If the read fails for any reason
(missing file, encoding error), fall back to the `@` form — the existing behavior — rather than introducing a new
failure mode. Log a warning in that case.

### Config plumbing

Follow the existing `AxeConfig` pattern in `src/sase/axe/config.py`:

1. Add `coder_plan_inline_max_lines: int = 300` to the `AxeConfig` dataclass.
2. Read `axe_data.get("coder_plan_inline_max_lines", 300)` in `load_axe_config()` and pass it into the constructor.
3. In `handle_plan_marker()`, call `load_axe_config()` once at the point of use (after the plan is approved) and read
   `.coder_plan_inline_max_lines`. Matches the project's dict-then-dataclass pattern; no need to thread the config
   through function arguments.

### Schema

Add a property to `config/sase.schema.json` under `axe.properties`:

```json
"coder_plan_inline_max_lines": {
  "type": "integer",
  "description": "Maximum plan-file line count for which the coder prompt inlines the plan with `@{path}`. Larger plans are referenced by path instead, to avoid \"Prompt is too long\" errors. Set to 0 to always reference by path.",
  "default": 300
}
```

## Phases

### Phase 1 — Config field

Files:

- `src/sase/default_config.yml` — add `coder_plan_inline_max_lines: 300` under `axe:`.
- `src/sase/axe/config.py` — add `coder_plan_inline_max_lines: int = 300` to `AxeConfig`; read and pass through in
  `load_axe_config()`.
- `config/sase.schema.json` — add the new property under `axe.properties`.

### Phase 2 — Prompt branching

Files:

- `src/sase/axe/run_agent_exec_plan.py`:
  - Import `load_axe_config` (lazy-import inside `handle_plan_marker` to keep module import side-effects minimal and
    match the existing local-import style used for `has_model_directive` a few lines above).
  - Before the `state.current_prompt = (...)` assignment at line 409, compute `plan_body` (either
    `f"@{plan_file}\n\nThe above plan has been reviewed and approved. Implement it now."` or
    `f"The plan at {plan_file} has been reviewed and approved. Read it and implement it now."`).
  - Use a small helper (e.g. `_build_coder_plan_body(plan_file, max_lines)`) defined in this module so it is directly
    unit-testable without mocking the whole `handle_plan_marker` pipeline.
  - `state.current_prompt` becomes
    `f"{model_prefix}{resume_prefix}{vcs_prefix}{plan_body}{coder_extra}\n{embedded_refs}"`.

### Phase 3 — Tests

Files:

- `tests/test_axe_run_agent_exec_plan.py` — add a new test class or add tests to the existing `handle_plan_marker` test
  class. Reuse the existing `patch_handle_plan_marker_side_effects` fixture (line 126) and the `make_plan_ctx_state`
  helper.
  - `test_coder_prompt_inlines_small_plan`: write a 50-line plan, assert `state.current_prompt` contains
    `f"@{plan_file}"`.
  - `test_coder_prompt_references_large_plan_by_path`: write a 500-line plan, assert `state.current_prompt` does NOT
    contain `@{plan_file}`, does contain `The plan at {plan_file}`, and contains the "Read it" instruction.
  - `test_coder_prompt_respects_config_override`: monkeypatch `load_axe_config` to return an `AxeConfig` with
    `coder_plan_inline_max_lines=10`, write a 20-line plan, assert the prompt references by path.
  - `test_coder_prompt_falls_back_to_inline_on_read_error`: delete the plan file between write and call (or point at a
    non-existent path), assert the prompt uses `@{plan_file}` (graceful fallback).
  - Unit tests for `_build_coder_plan_body(plan_file, max_lines)` covering the three branches directly (small / large /
    read-error) without going through `handle_plan_marker`.

### Phase 4 — Verification

- `just check` (install + lint + type + tests).
- Manual smoke: create a small-plan agent and a large-plan agent (either by authoring a synthetic large plan or setting
  `coder_plan_inline_max_lines: 5` in the local `sase.yml`), launch a coder in each, confirm:
  - Small plan: coder's opening message shows the inlined plan body.
  - Large plan: coder's opening message references the path and the coder issues a `Read` on the plan file before
    acting.

## Risks / open questions

1. **Embedded workflow refs at the end of the prompt** (`#propose`, `#gh`, etc.) are appended after the plan body. These
   already work with both a raw path and an `@` path at the top of the prompt, so no change needed.
2. **VCS prefix** (`vcs_prefix`) comes before the plan body. Unchanged.
3. **Coder extra instructions** (`coder_extra`) are appended after `Implement it now.` — they continue to follow the
   body sentence in both branches.
4. **Resume behavior** (`SASE_CODER_INHERIT_PLANNER_CHAT=1`): when the coder inherits the planner's transcript, the plan
   is already in the inherited chat history. Inlining via `@` at the top is therefore partly redundant; the large-plan
   branch is strictly better in that mode. No special casing required — the threshold check fires regardless.
5. **Coder's ability to resolve the path**: plan files live at an absolute path in `~/.sase/plans/`. The coder agent has
   Read access to that directory (this is already how `#resume` and related flows pick up plan files). No
   agent-permission change needed.
6. **Schema default vs. dataclass default drift**: keep both at `300`. Adding a comment in `default_config.yml` ("# keep
   in sync with AxeConfig default") is not necessary — the Python default is only hit if the YAML layer is entirely
   absent, which `default_config.yml` prevents.
