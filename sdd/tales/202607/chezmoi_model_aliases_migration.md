---
create_time: 2026-07-03 13:08:47
status: wip
prompt: sdd/prompts/202607/chezmoi_model_aliases_migration.md
---
# Plan: Migrate chezmoi `sase.yml` to the unified `model_aliases` shape

## Problem

Commit `8b0ff2c9f` ("feat!: unify model alias config") landed the unified `llm_provider.model_aliases` schema in the
sase repo: a single object with two subfields, `builtin` (role-override string map) and `custom` (user-defined aliases
with required `model`/`description`). The flat top-level `model_aliases` string map and the top-level
`custom_model_aliases` block were removed from the schema (`additionalProperties: false`, clean break — no runtime
compat shim).

The live user config is chezmoi-managed and still uses the **old flat shape**. Its source lives at
`home/dot_config/sase/sase.yml` in the chezmoi repo (`~/.local/share/chezmoi/`), applied verbatim (not a `.tmpl`
template) to `~/.config/sase/sase.yml`. Until it is migrated:

- The six role-override aliases stop resolving at runtime (launches fall back to defaults).
- `sase doctor -C config.model_aliases` flags every flat key as an unsupported legacy entry.
- The inline comments still direct users to the removed `custom_model_aliases` key, and the commented example still
  references it.

The sibling `sase_athena.yml` config in the same directory has no `model_aliases` block and needs no change.

## Current State (chezmoi source `home/dot_config/sase/sase.yml`, lines 93–113)

```yaml
llm_provider:
  default_effort: xhigh
  model_aliases:
    # Builtin alias overrides only. User-defined aliases belong under
    # custom_model_aliases so the Models panel and %model completion can show a
    # description.
    # Coder follow-ups: a Claude-authored plan hands coding to Codex and a
    # Codex-authored plan hands coding to Claude Opus (migrated from the retired
    # worker_models lane in epic sase-5d).
    claude_coder: gpt-5.5
    codex_coder: claude/opus
    # Remaining bead/epic role aliases are listed explicitly for readability;
    # each just tracks the default launch model (@default), the implicit default.
    coder: "@default"
    epic_creator: "@default"
    epic_lander: "@default"
    phase_worker: "claude/opus"
  # custom_model_aliases:
  #   blogger:
  #     model: claude/opus
  #     description: "Agents that draft and edit blog posts."
```

All six aliases (`claude_coder`, `codex_coder`, `coder`, `epic_creator`, `epic_lander`, `phase_worker`) are builtin-role
overrides, so all move under `builtin:`. No custom aliases are currently active (only a commented example).

## Target State

```yaml
llm_provider:
  default_effort: xhigh
  model_aliases:
    builtin:
      # Builtin alias overrides only. User-defined aliases belong under
      # model_aliases.custom so the Models panel and %model completion can show a
      # description.
      # Coder follow-ups: a Claude-authored plan hands coding to Codex and a
      # Codex-authored plan hands coding to Claude Opus (migrated from the retired
      # worker_models lane in epic sase-5d).
      claude_coder: gpt-5.5
      codex_coder: claude/opus
      # Remaining bead/epic role aliases are listed explicitly for readability;
      # each just tracks the default launch model (@default), the implicit default.
      coder: "@default"
      epic_creator: "@default"
      epic_lander: "@default"
      phase_worker: "claude/opus"
    # custom:
    #   blogger:
    #     model: claude/opus
    #     description: "Agents that draft and edit blog posts."
```

Changes vs. current:

1. Indent the entire flat body (comments + the six `key: value` overrides) one level under a new `builtin:` key.
2. Rewrite the lead comment reference `custom_model_aliases` → `model_aliases.custom`.
3. Replace the commented top-level `# custom_model_aliases:` example with a commented `# custom:` example nested at the
   same indent level as `builtin:` (values unchanged: `blogger` / `claude/opus` / description).

Value semantics are unchanged — this is purely a re-nesting plus comment refresh. The block stays outside both
`keep-sorted` regions in the file, so no sort ordering is affected.

## Implementation

Single-file edit in the chezmoi source repo (`~/.local/share/chezmoi/`):

- **`home/dot_config/sase/sase.yml`** — apply the re-nesting and comment updates shown in "Target State" above.

No changes to `sase_athena.yml`, no template logic, no chezmoi scripts.

## Verification

1. **YAML sanity** — parse the edited source file (e.g.
   `python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))"` on `home/dot_config/sase/sase.yml`) to confirm
   valid YAML and that `llm_provider.model_aliases` is now an object with a single `builtin` key holding the six
   aliases.
2. **Apply** — run `chezmoi diff` to confirm the only pending change targets `~/.config/sase/sase.yml`, then
   `chezmoi apply` (or apply just that file) to update the live config.
3. **Schema/doctor** — run `sase doctor -C config.model_aliases` against the applied config; it should now report clean
   (no legacy-flat-key or removed-`custom_model_aliases` findings). Optionally confirm one override resolves, e.g. that
   `claude_coder` maps to `gpt-5.5` via the Models panel (`,m`) or `%model` completion.

## Rollout Note

This is the deferred post-merge step called out in the `unified_model_aliases` plan's "Rollout Note". It should be
committed to the chezmoi repo (its own repository, separate from the sase repo) after `chezmoi apply` verifies clean.
