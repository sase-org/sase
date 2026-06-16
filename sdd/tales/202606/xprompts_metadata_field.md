---
create_time: 2026-06-16 14:07:59
status: done
prompt: sdd/prompts/202606/xprompts_metadata_field.md
---
# Plan: Replace "Embedded Workflows" with a redesigned "Xprompts" field

## Goal

On the **Agents** tab of the `sase ace` TUI, the agent metadata panel currently shows an `Embedded Workflows:` field.
That field is limited in two ways:

1. **It only lists `.yml` xprompt _workflows_.** The `.md` xprompt _parts_ the user actually referenced in the prompt
   (e.g. `#review_checklist`) are invisible.
2. **It renders as one cramped comma-joined line** (`Embedded Workflows: propose(note=blah), cl`) with no distinction
   between kinds and no visual structure.

Replace it with a new **`Xprompts:`** field that:

- Shows **every** xprompt referenced in the prompt — both `.md` parts _and_ `.yml` workflows.
- Is **redesigned** into a small, beautiful, structured mini-section that fits the panel's existing visual language (the
  `▸ LANE`, glyph-prefixed rows, dim detail-summary vocabulary already used by the AGENT CONTEXT / SKILLS / Artifacts
  sections).

I am leading the design; the rendering described below is the proposed look.

## Background: why the current field is incomplete (the data model)

There are two distinct kinds of `#name` references, expanded by two separate mechanisms:

| Kind                | Catalog               | Expanded by                                                      | Persisted today?                |
| ------------------- | --------------------- | ---------------------------------------------------------------- | ------------------------------- |
| `.md` **part**      | `get_all_xprompts()`  | `process_xprompt_references()` (`src/sase/xprompt/processor.py`) | **No**                          |
| `.yml` **workflow** | `get_all_workflows()` | embedded-workflow expanders                                      | Yes → `embedded_workflows.json` |

`embedded_workflows.json` (and per-step `embedded_workflows_{step}.json`) is written in two places:

- `src/sase/xprompt/workflow_executor_steps_embedded_expand.py:350-370` — the `WorkflowExecutor` path, which covers
  **plain `sase run`** (run as an anonymous single-step workflow) and **multi-step workflows**.
- `src/sase/main/query_handler/_embedded_workflows.py:189-193` (`expand_embedded_workflows_in_query`) — covers
  **mentor**, **crs**, and **fix-hook** agents.

The TUI field reads it via `load_embedded_workflows()` in `src/sase/ace/tui/widgets/prompt_panel/_helpers.py:210`,
surfaced through the precomputed `_DetailHeaderSummary` and rendered at `_agent_display_parts.py:408-415`.

The `.md` parts are never written to disk — they vanish after `process_xprompt_references()` expands them inline. That
is the gap.

### Capture strategy: scan the raw prompt (not a runtime trace)

The cleanest way to capture **all** xprompts uniformly is to scan the raw (pre-expansion) prompt for `#name` references
using the canonical lexical matcher `iter_xprompt_references()` (`src/sase/xprompt/_parsing_references.py:176`). It
returns `XPromptReference` objects that already expose `.name`, `.raw`, position, and a `.parse_arguments()` method
handling every arg syntax (paren / colon / `+` / shorthand / backtick / `$(cmd)`). Resolving each name against
`get_all_xprompts()` ∪ `get_all_workflows()` classifies it as **part** vs **workflow** and discards non-xprompt `#refs`
(VCS tags like `#gh:sase`, stray prose hashes).

This is preferred over threading an `ExpansionTrace` through the deep call stacks because:

- One small helper, fed a raw prompt string, covers both kinds in a single pass.
- It reuses the exact same parser the expanders use, so detection stays consistent.
- It records **top-level** references — the xprompts the user actually wrote — which is the intuitive meaning of
  "xprompts used in the prompt" (nested xprompts referenced _inside_ another xprompt's body remain an internal detail,
  matching how `embedded_workflows.json` already records only the directly-referenced workflows).

The helper resolves xprompt aliases and skips fenced code blocks and disabled (`%xprompts_enabled:false`) regions
internally, so it is correct regardless of which caller invokes it.

### Rust core boundary

This stays **Python-only**, deliberately and consistently: xprompt expansion is implemented entirely in Python
(`src/sase/xprompt/`), and the existing equivalent artifact (`embedded_workflows.json`) is already Python-written and
Python-read. The sibling Rust core (`../sase-core`) only carries read-only xprompt LSP/catalog tooling and a wire field
for scan results — it does not perform expansion. No `sase-core` change is required.

## Design: the new "Xprompts:" rendering

The field lives where the old one did (in the metadata block, just after the `Workflow:` row), but renders as a compact
titled list — mirroring the existing `Artifacts:` and `▸ LANE` patterns so it feels native:

```
Xprompts: 2 workflows · 1 part
  ⚙ #propose  note=blah
  ⚙ #cl
  ❖ #review_checklist
```

Design rules:

- **Header line** — `Xprompts:` in the standard field-label style (`bold #87D7FF`), followed by a dim summary built with
  the existing `count_phrase()` helper. Show the kind breakdown only when meaningful: `2 workflows · 1 part`, or just
  `1 part` / `3 workflows` when homogeneous.
- **One row per xprompt**, indented two spaces, kind distinguished by glyph **and** color (chosen to not collide with
  sibling glyphs `◇` memory, `◆` skill, `•` artifact, `↳` reason):
  - **Workflow** → gear glyph `⚙`, name in warm amber (`bold #FFAF5F`) — signals "runs steps".
  - **Part** → `❖` glyph, name in cyan (`bold #87D7FF`) — signals "inline snippet".
- **The name is `#`-prefixed** (`#propose`) so it reads exactly as typed in the prompt — instantly recognizable.
- **Arguments** render after the name in a dim style: named as `k=v`, positional as bare values, joined by `, `. Long
  values are truncated via the existing `truncate_display()` helper so each entry stays on one line. No args → name
  only.
- **Order & dedupe** — preserve first-seen order; collapse exact `(name, args)` duplicates (showing `#cl` twice conveys
  nothing).
- **Empty** — when no xprompts were used, omit the field entirely (current behavior).
- Rendered **only on the full/debounced path** via `_DetailHeaderSummary`, never on the cheap `j/k` path (no disk read
  in the hot path) — matching the existing field's contract.

## Implementation outline

### A. Capture (run-time) — new artifact `xprompts.json`

1. **New module `src/sase/xprompt/used_xprompts.py`:**
   - `collect_used_xprompts(raw_prompt) -> list[dict]`: resolve aliases, scan with `iter_xprompt_references`, skip
     fenced/disabled regions, resolve each name against both catalogs, classify (`kind`), parse args, dedupe. Each
     record: `{"name", "kind": "workflow"|"part", "positional": [...], "named": {...}, "tags": [...]}` (workflow
     precedence on name collision, matching expansion semantics).
   - `write_used_xprompts(artifacts_dir, raw_prompt, step_name=None)`: collect, then write the shared `xprompts.json`
     and (when `step_name` given) `xprompts_{step_name}.json`, mirroring exactly how `embedded_workflows.json` is
     written so the TUI loader's "step-specific first, fall back to shared" logic works identically.

2. **Wire into the two execution models (the same two places that write `embedded_workflows.json`):**
   - `src/sase/xprompt/workflow_executor_steps_prompt.py:_execute_prompt_step` — call
     `write_used_xprompts(self.artifacts_dir, step_prompt, step.name)` using the pre-expansion `step_prompt` (line ~186,
     after VCS-tag inheritance). Covers plain `sase run` + workflows.
   - `src/sase/main/query_handler/_embedded_workflows.py:expand_embedded_workflows_in_query` — capture the original
     query at entry and call `write_used_xprompts(artifacts_dir, raw_query)`. Covers mentor / crs / fix-hook.

   `embedded_workflows.json` continues to be written **unchanged** — it has other consumers
   (`run_agent_exec_plan_artifacts.get_embedded_workflow_refs` rollover logic; the per-step boxed workflow view in
   `_workflow_data.py` / `_workflow_steps.py`). We only **add** the new artifact and only change the metadata **field**.

### B. Render (TUI)

3. **New loader `load_xprompts_used(agent)` in `_helpers.py`** — mirrors `load_embedded_workflows` but reads
   `xprompts_{step}.json` / `xprompts.json`.
4. **New `src/sase/ace/tui/widgets/prompt_panel/_agent_xprompts.py`** with
   `append_agent_xprompts_section(text, xprompts_used)` implementing the design above (reusing `count_phrase` /
   `truncate_display`).
5. **Update `_agent_display_parts.py`**: replace the `embedded_workflows` field on `_DetailHeaderSummary` with
   `xprompts_used`, populate it in `build_detail_header_summary`, and replace the `Embedded Workflows:` block in
   `build_header_text` with a call to the new section renderer (still gated on `not cheap and summary is not None`).
6. **Remove the now-dead `load_embedded_workflows` / `format_embedded_workflows`** from `_helpers.py` and
   `prompt_panel/__init__.py` (only the field used them).

### C. Tests & validation

7. **Unit tests** for `collect_used_xprompts` / `write_used_xprompts`: parts, workflows, mixed, named/positional args,
   dedupe, fenced-block & disabled-region skipping, unknown-name filtering, shared + per-step file output.
8. **Widget tests**: replace the `Embedded Workflows` tests in `tests/test_ace_tui_widgets.py` and the cheap-path
   assertion in `tests/ace/tui/widgets/test_agent_display_header_only.py` (which patches `load_embedded_workflows`) with
   `Xprompts` / `load_xprompts_used` equivalents.
9. **Visual PNG snapshot**: enrich the `_zoom_agent` fixture in `tests/ace/tui/visual/test_ace_png_snapshots_agents.py`
   with an `artifacts_dir` containing a sample `xprompts.json` (a couple of workflows + a part) so the existing
   `agents_metadata_zoom_modal_120x40` golden showcases the new section, then regenerate the golden with
   `--sase-update-visual-snapshots` and eyeball it.
10. Run `just install` then `just check` and `just test-visual`.

## Out of scope / non-changes

- `embedded_workflows.json` format and its existing consumers — untouched.
- The boxed per-step embedded-workflow view in the workflow/Output panel — untouched.
- CLI options, keymaps, `default_config.yml`, help modal — none affected (this is a passive display field, not an
  option).
- `sdd/prompts/*` historical mockups mentioning "Embedded Workflows" — left as-is (history).
- `sase-core` — no changes (rationale above).

## Risks & mitigations

- **Lexical-matcher divergence**: `iter_xprompt_references` vs the processor's regex could differ on exotic edge cases.
  Mitigation: it is the shared canonical matcher used by the workflow expander, and catalog membership filters noise;
  covered by unit tests.
- **Coverage parity**: both `embedded_workflows.json` write sites get a paired `write_used_xprompts` call, so every
  agent path that showed the old field shows the new one.
- **Hot-path performance**: capture happens at agent launch (not TUI render); the field is populated only on the
  debounced full path via `_DetailHeaderSummary`, never on `j/k`.
