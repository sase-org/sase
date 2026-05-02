---
create_time: 2026-04-02 11:39:14
status: done
prompt: sdd/prompts/202604/tmux_empty_cls.md
---

# Plan: Support `t` (tmux) keymap on CLs tab with empty results

## Problem

When no ChangeSpecs match the current query on the CLs tab, pressing `t` does nothing because `_open_tmux_for_workspace`
returns early at the `if not self.changespecs: return` guard. However, if the user has a single `project:<project>`
filter in their query, we know which project they want — so we can open a tmux window pointing at that project's
workspace directory (without any branch checkout).

## Design

### Core behavior

- When `t` is pressed with no matching CLs, extract `project:` filters from the parsed query.
- If there is exactly one `project:` filter, resolve the workspace directory for that project and open a tmux window.
- Skip the VCS checkout step entirely (no branch/CL name available).
- The tmux session naming follows the existing convention: `<project>` for workspace 1, `<project>_<N>` otherwise.

### Implementation

#### Phase 1: Add a query utility to extract project filters

Add a `get_sole_project_filter` function to `src/sase/ace/query/evaluator.py` (and export it from `__init__.py`). This
function walks the parsed query AST and collects all `PropertyMatch` nodes with `key == "project"`. It returns the
project name string if there is exactly one such filter (not negated), otherwise `None`.

The function must handle:

- Top-level `PropertyMatch(key="project")`
- `PropertyMatch` nested inside `AndExpr` operands (common: `project:foo status:wip`)
- `PropertyMatch` inside `NotExpr` — these should NOT count (negated project filter)
- `OrExpr` — project filters inside OR branches should not count as "sole"

#### Phase 2: Modify `_open_tmux_for_workspace` to handle empty CLs

In `src/sase/ace/tui/actions/workspace.py`, change the early return at `if not self.changespecs` to instead:

1. Call `get_sole_project_filter(self.parsed_query)` to extract the project name.
2. If `None`, return early (no single project to target).
3. Resolve the workspace directory using `get_workspace_directory(project_name, workspace_num)`.
4. Skip the VCS checkout step (no `changespec.name` to resolve a branch for).
5. Open/switch to the tmux window as normal.

The tmux session naming and window creation/selection logic remains the same. The only difference is the absence of the
checkout step.

#### Phase 3: Update the footer to show the `t` keymap when applicable

In `src/sase/ace/tui/widgets/keybinding_footer.py`, the `show_empty()` method currently only shows the "edit query"
binding. Extend it to accept an optional `project_name` parameter. When provided, also show the `t` (tmux) binding in
the empty footer, so the user knows it's available.

The caller in `src/sase/ace/tui/actions/changespec.py` (around line 466-478) needs to compute whether there's a sole
project filter and pass it through.

#### Phase 4: Tests

Add tests in a new or existing test file:

- `get_sole_project_filter` returns the project name for `project:foo`, `project:foo status:wip`, `+foo %w`.
- Returns `None` for no project filter, multiple project filters (`project:a project:b`), negated (`!project:foo`), and
  project filters inside OR branches.
