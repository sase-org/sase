---
create_time: 2026-06-27 11:42:41
status: done
prompt: sdd/prompts/202606/jinja_diagnostics_known_vars.md
---
# Fix: Jinja2 prompt diagnostics falsely flag built-ins and frontmatter inputs

## Problem

The live Jinja2 diagnostics on the ACE TUI prompt input widget report legitimate variables as "unknown variables". In
the reported case a multi-agent prompt that uses `{{ wait_chats }}` (a runtime built-in) and `{{ topic }}` (an `input:`
declared in the prompt's frontmatter) shows both as undefined, surfacing the `⟨jinja ! var⟩` chip and the "jinja
diagnostics → unknown variables: topic, wait_chats" panel even though both resolve correctly at launch time.

(A third used variable in the same prompt, `reference_query`, is _not_ flagged only because it sits inside a fenced code
block, which the inspector masks out — confirming the diagnostic is otherwise flagging everything that is not `root`.)

## Root cause

The diagnostics path computes "known" variables from far too narrow a set.

- `src/sase/ace/tui/widgets/_jinja_diagnostics.py` calls `jinja_inspect.inspect_template(text)` with **no** `known`
  argument.
- `inspect_template` (in `src/sase/xprompt/jinja_inspect.py`) therefore falls back to `known_toplevel_context()`.
- `known_toplevel_context()` returns only `RESERVED_GLOBAL_NAMES`, which is `frozenset({"root"})`
  (`src/sase/xprompt/_jinja.py`).

So every top-level Jinja variable other than `root` is reported as unknown. Two whole categories of legitimate variables
are missing from the known set:

1. **Built-in runtime variables** — injected per agent run by `_build_named_args` in `src/sase/axe/run_agent_exec.py`:
   `cl_name`, `workspace_num`, `n`, `N` (repeat iterations), `wait_chats`, and `agents` (the `AGENTS_CONTEXT_KEY`
   namespace from `src/sase/agent/output_variable_context.py`). These are constructed dynamically at launch and have no
   static representation the linter can see.

2. **Frontmatter-declared `input:` arguments** — e.g. `topic`. At launch these are resolved into the render context by
   `render_prompt_with_inputs` (`src/sase/agent/prompt_inputs.py`), which substitutes supplied/defaulted values into the
   body before agents fan out. They are genuinely defined, but the diagnostics never consult the prompt's frontmatter,
   so it cannot know about them.

Both categories therefore resolve fine at runtime but are falsely flagged in the editor.

## Why this is the right layer (Rust core boundary)

Top-level prompt unknown-variable diagnostics are Python/TUI only. The shared Rust core (`sase-core`) implements xprompt
**frontmatter field** validation and editor completion, but has no `find_undeclared_variables`-style top-level body
linting (verified: no `unknown_variable` / `undeclared` / `wait_chats` logic in `crates/sase_core`). The Neovim editor
relies on the Rust core for frontmatter validation, not for body unknown-variable linting.

The source of truth for these names is already Python: the runtime injects them in `_build_named_args`, and
`RESERVED_GLOBAL_NAMES` / `jinja_inspect` already live in Python. There is no cross-frontend behavior to keep in parity,
so this fix stays in Python with **no `sase-core` changes**.

## Design

Keep `known_toplevel_context()` meaning "reserved globals" (it backs both completion and the local-xprompt
input-inference feature, whose behavior we do not want to change). Add the two missing categories specifically on the
diagnostics path.

### 1. Static registry of built-in runtime names

Add a new constant next to `RESERVED_GLOBAL_NAMES` in `src/sase/xprompt/_jinja.py`, e.g.:

```
BUILTIN_RUNTIME_NAMES = frozenset({
    "cl_name", "workspace_num", "n", "N", "wait_chats", "agents",
})
```

Document it as the static mirror of the names injected by `_build_named_args` plus `AGENTS_CONTEXT_KEY`, so the drift
risk is explicit. Keep it _separate_ from `RESERVED_GLOBAL_NAMES` so the existing "globals are a subset of
`RESERVED_GLOBAL_NAMES`" invariant for `get_global_template_vars()` stays intact. (The internal
`__sase_workflow_inherited_vcs_tag` arg is double-underscore and not user-typeable, so it is intentionally excluded.)

Expose it through the inspector, e.g. `jinja_inspect.builtin_runtime_names()`, and add it to
`src/sase/xprompt/__init__.py` exports for symmetry.

### 2. Per-prompt known set on the diagnostics path

In `_jinja_diagnostics.py`, build the known set from three sources and pass it explicitly to
`inspect_template(text, known=...)`:

- `jinja_inspect.known_toplevel_context()` (reserved globals — `root`)
- `jinja_inspect.builtin_runtime_names()` (the new built-ins)
- the prompt's frontmatter `input:` names

For frontmatter input names, cover both prompt-stack shapes:

- **Multi-agent / lifted frontmatter** (the reported case): read `bar._stack.frontmatter_model.inputs` via
  `_find_prompt_bar()` and collect `arg.name`. `frontmatter_model` already parses the raw stack frontmatter into a
  `PromptFrontmatter`.
- **Single-pane history-loaded prompt** (frontmatter kept inline in the pane body, stack frontmatter empty): when the
  diagnosed `text` begins with a `---` block, parse it with `PromptFrontmatter.parse(text)` and collect its input names
  too.

This keeps the computation self-contained and correct regardless of how the bar was seeded. Guard defensively (bar may
be `None`; parsing tolerates partial input and returns an empty model).

### 3. (Optional, consistency) completion candidates

`jinja_completion._candidates_for_prefix` offers variable completions from `known_toplevel_context()`. Optionally also
surface `builtin_runtime_names()` there so the editor _suggests_ `wait_chats`, `cl_name`, etc. (it is purely additive
and low-risk). Frontmatter inputs are dynamic and out of scope for completion in this change. This step can be dropped
if we want the tightest possible fix; the diagnostics fix does not depend on it.

### Deliberately unchanged

- `known_toplevel_context()` stays globals-only, so `infer_local_xprompt_inputs` (`_local_xprompt_conversion.py`) keeps
  inferring non-global variables as inputs exactly as today. (Whether built-ins should be excluded from local-xprompt
  input inference is a separate semantic question and is out of scope.)

## Test plan

- **Unit** (`tests/test_xprompt_jinja_inspect.py` or a sibling):
  - `builtin_runtime_names()` contains the documented set.
  - `inspect_template("{{ wait_chats }}", known=known_toplevel_context() | builtin_runtime_names())` yields no unknowns;
    a genuine typo still does.
- **TUI diagnostics** (`tests/ace/tui/widgets/test_prompt_jinja.py` style):
  - Prompt bar whose stack frontmatter declares `input: topic`, body uses `{{ topic }}` and `{{ wait_chats }}` → no
    `⟨jinja ! var⟩`, panel hidden, `_jinja_unknown_spans` empty.
  - Same body with an undeclared `{{ definitely_unknown }}` → still flagged (regression guard so the linter is not
    neutered).
  - Single-pane inline-frontmatter prompt (`---\ninput:\n  topic: line\n---\n {{ topic }}`) → `topic` not flagged.
- **Visual**: run `just test-visual`. The two jinja snapshots (`test_prompt_jinja_valid_png_snapshot`,
  `test_prompt_jinja_invalid_png_snapshot`) use only `{{ root }}` and a syntax error with no frontmatter, so they should
  be unaffected; confirm no golden drift.

## Files touched

- `src/sase/xprompt/_jinja.py` — add `BUILTIN_RUNTIME_NAMES`.
- `src/sase/xprompt/jinja_inspect.py` — add `builtin_runtime_names()`.
- `src/sase/xprompt/__init__.py` — export the new helper.
- `src/sase/ace/tui/widgets/_jinja_diagnostics.py` — compute and pass the per-prompt known set (built-ins + frontmatter
  inputs).
- `src/sase/ace/tui/widgets/jinja_completion.py` — optional built-in candidates.
- Tests as above.

No `sase-core` changes.

## Validation

Run `just install` first (ephemeral workspace), then `just check` and `just test-visual`. Note: pre-existing unrelated
failures may appear (`llm_provider` `invoke_agent` cases from the dev env's `default_effort`, and the `sase validate`
memory-freshness gate); these are not introduced by this change.
