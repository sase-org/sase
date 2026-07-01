---
create_time: 2026-07-01 08:23:39
status: done
prompt: sdd/prompts/202607/minimal_diff_model_alias_edits.md
---
# Plan: Minimal-Diff Model Alias Edits from the Models Panel

## Problem

When a user edits (or resets) a model alias from the `sase ace` **Models** panel — e.g. `set @claude_coder → opus` — the
"Edit Model Alias" preview modal shows, and the write produces, a diff that is far larger than the one line that
actually changed. Unrelated regions of the config file are reflowed: block sequences get re-indented, wrapped folded
scalars get collapsed onto one line, and flow-mapping spacing is stripped. The user wants the write (and its preview
diff) to touch **only** the alias line being edited, leaving every other byte of the file untouched.

Screenshot of the symptom: `set @claude_coder → opus` yields a diff whose first hunk rewrites the unrelated
`github_orgs:` and `linked_repos:` blocks from `  - item` to `- item`.

## Root Cause

The Models panel delegates the write to the shared config-edit machinery:

- Modal → `plan_alias_edit()` (`src/sase/ace/tui/modals/models_panel_edit_helpers.py`) → `plan_config_edit()`
  (`src/sase/config/edit.py`).
- The Rust core (`config_plan_edit` binding) only computes a **logical** write plan (which file, which dotted key path,
  set-vs-unset, and the new value). It does **no** serialization.
- The YAML text is produced entirely in Python by `set_key()` / `unset_key()` in `src/sase/config/edit.py`. Both do a
  **full round-trip**: load the whole document with `ruamel.yaml`, mutate the in-memory tree, and re-dump the **entire**
  document.

Even though `ruamel.yaml` is a "round-trip" loader, re-dumping the whole document re-emits every node and normalizes
formatting globally. This is inherent to the load→mutate→dump approach — it can never be truly minimal.

### Reproduction (authoritative)

Applying a single `llm_provider.model_aliases.claude_coder: opus` edit to the real `sase.yml` via the current code
produces **26 changed lines**, with three distinct classes of collateral reflow:

1. **Sequence indentation** — `github_orgs:` / `linked_repos:` items change from `  - item` to `- item`.
2. **Folded/long scalars collapsed** — multi-line wrapped values (e.g. `logp:`, `content:`) get pulled onto a single
   line (interacts with the `width = 4096` setting).
3. **Flow-mapping spacing stripped** — `{ type: line, default: "feature" }` becomes `{type: line, default: "feature"}`.

### Why the "obvious" one-line fix is insufficient

A tempting fix is to add indentation settings to the `ruamel.yaml` handler
(`sequence_indent=4, sequence_dash_offset=2`). Reproduction shows this only fixes class (1): the same edit still reflows
**12 lines** because classes (2) and (3) are independent of indentation. Any approach that re-dumps the whole document
remains non-minimal. This mitigation is worth keeping as a _fallback_ hardening, but it does not solve the user's
problem on its own.

## Design

Replace the whole-document round-trip with a **surgical, position-based text edit** for the common cases, keeping the
round-trip only as a correctness fallback. This mirrors the pattern already established in this codebase for minimal
config edits: `insert_xprompt_into_config()` in `src/sase/xprompt/config_yaml.py` (tested by
`tests/xprompt/test_config_yaml_minimal_edits.py`) preserves everything byte-for-byte except the single entry it
touches.

The change lives in `src/sase/config/edit.py`, at the `set_key()` / `unset_key()` layer. Because both the Models-panel
alias edit **and** the general Config Center flow through `_apply_to_text()` → `set_key`/`unset_key`, fixing it here
makes every scalar config edit minimal, not just alias edits.

### Locating nodes without re-dumping

`ruamel.yaml` exposes line/column metadata after a load: for a `CommentedMap`, `parent.lc.data[key]` returns
`[key_line, key_col, value_line, value_col]` (0-indexed). This lets us locate the exact value span of an existing scalar
leaf, and the insertion point for a new key, and then splice the **original** text ourselves — never re-emitting
untouched lines.

### `set_key(text, key_path, value)` — new behavior

1. Load `text` with `ruamel.yaml` **only to navigate and read positions** (never to dump).
2. Walk `key_path[:-1]` through nested mappings.
3. Dispatch:
   - **Leaf exists as a single-line plain scalar** → replace only the value token on its line. Compute the value-span
     end by scanning from the value start column: for a quoted scalar, find the matching close quote; for a plain
     scalar, stop at the first ` #` (inline comment) or end of line, trimming trailing spaces. Everything before the
     value, the trailing inline comment, and all other lines stay byte-identical.
   - **Leaf missing, parent mapping exists** → insert exactly one line `"<child_indent><leaf>: <serialized_value>"`.
     Derive `child_indent` from an existing sibling key, else parent-key indent + 2. Insert after the parent's last
     existing child (order preserved). Only a line is added; nothing else changes.
   - **An ancestor mapping is missing** → append the minimal nested chain (`parent:` lines + leaf) under the deepest
     existing ancestor, or at end-of-file if none exists. Only added lines.
4. Serialize the new scalar (`str` / `int` / `float` / `bool` / `None`) to canonical YAML scalar text with correct
   quoting. Optionally preserve the existing quote character when replacing a string value.
5. If the target/value is not something the surgical path can confidently handle (value node is a block scalar or
   multi-line, target is inside a flow collection or a sequence, or the new value is a mapping/list replacing a scalar),
   **decline** and fall back (see below).

### `unset_key(text, key_path)` — new behavior

Locate the leaf's full line span (key line through the last line of its value block, including its inline comment —
matching the current "removes the inline comment too" behavior) and delete exactly those lines. Missing path / empty
document remain a no-op. Decline to the fallback for ambiguous spans.

### Fallback (safety)

`set_key` / `unset_key` become thin dispatchers:

```
result = <surgical attempt>            # returns None when it declines
return result if result is not None else <existing ruamel round-trip>
```

Retain today's round-trip implementations verbatim as the fallback, and additionally harden the shared `ruamel.yaml`
handler with indentation-preserving settings so that even the fallback path minimizes collateral (fixes reflow class (1)
when the round-trip is used).

### Safety net (never write wrong bytes)

After producing surgical text, re-parse it and verify:

- it is valid YAML, and
- the effective value at `key_path` equals the intended value (for `set`) or is absent (for `unset`), and
- the parsed document equals the parsed original with only that one key changed (guards against accidental edits
  elsewhere).

If any check fails, discard the surgical result and use the round-trip fallback. Worst case we regress to today's
larger-but-correct diff; we never emit corrupt or semantically wrong YAML.

### Preview comes along for free

The modal's diff is `_unified_diff(current_text, new_text)` and `apply_config_edit()` writes `plan.new_text` verbatim.
Because `new_text` is now minimal, the previewed "Diff" section shrinks automatically and the previewed bytes still
exactly equal the written bytes. No separate preview change is needed.

## Scope / Boundary

- **Python only.** Serialization is deliberately Python-side (see the `src/sase/config/edit.py` module docstring); the
  Rust core only produces the logical write plan and is not involved in the reflow. No Rust/`sase-core` change is
  required. (The core-boundary rule was considered: the text serializer is presentation/format glue that already lives
  in Python by design, and the logical decision layer stays in Rust.)
- Benefits both the Models-panel alias edit and the general Config Center, since they share `set_key`/`unset_key`.

## Testing

Preserve all existing invariants in `tests/test_config_edit.py`:

- `set_key` preserves comments, key order, and quoting; creates intermediate mappings from empty text.
- `unset_key` removes the key and its inline comment; missing path is a no-op.
- `apply_config_edit` writes exactly the previewed text.

Add unit tests asserting **exact minimal diffs**:

- Setting a nested scalar in a document that contains indented sequences and wrapped folded scalars changes **only** the
  target line (assert the sequence/folded lines are byte-identical and the unified-diff hunk/line count is exactly the
  one change).
- Setting a brand-new alias under an existing `model_aliases` map inserts exactly one line.
- Creating `llm_provider.model_aliases.<x>` when the section is absent adds only new lines and touches nothing else.
- `unset` removes only the target line(s).
- Fallback path: a declined value shape still yields correct round-trip output.
- Safety net: a crafted case where the surgical edit would be wrong is caught and falls back.

Regenerate the two affected PNG visual snapshots — `test_ace_png_snapshots_models_panel_edit.py` and
`test_ace_png_snapshots_config_center_edit.py` — with `--sase-update-visual-snapshots`, since the previewed "Diff"
section now renders far fewer lines. Review the new goldens to confirm they show the minimal diff.

## Validation

Run `just install` first (ephemeral workspace), then `just check`. Given known environment constraints (the full test
suite can be SIGTERM-killed in the sandbox, and there are pre-existing unrelated `llm_provider` failures), rely on
targeted runs plus the static gates: `tests/test_config_edit.py`, `tests/test_models_panel_edit.py`,
`tests/xprompt/test_config_yaml_minimal_edits.py`, and the two visual snapshot modules above.

## Acceptance Criteria

- Editing `@claude_coder → opus` on the real-world `sase.yml` shape produces a diff touching only the `claude_coder:`
  line — no `github_orgs` / `linked_repos` / folded-scalar / flow-spacing reflow.
- Resetting an alias removes only that alias's line(s).
- The Models-panel "Edit Model Alias" preview shows that same minimal diff, and the written file matches the preview
  byte-for-byte.
- All existing config-edit invariants still hold; complex/edge edits fall back safely and never corrupt the file.
