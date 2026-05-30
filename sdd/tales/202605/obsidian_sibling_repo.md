---
create_time: 2026-05-30 15:44:14
status: done
prompt: sdd/prompts/202605/obsidian_sibling_repo.md
---
# Plan: Add Obsidian Vault as a Static SASE Sibling Repo

## Context

The global SASE configuration source is managed by chezmoi at
`/home/bryan/.local/share/chezmoi/home/dot_config/sase/sase.yml`. The live `~/.config/sase/sase.yml` currently matches
that source file.

That config already has a static sibling repo entry for the chezmoi repository:

```yaml
sibling_repos:
  - name: chezmoi
    path: ~/.local/share/chezmoi
    description: Chezmoi-managed dotfiles and global SASE configuration source.
    workspace:
      strategy: none
```

SASE supports two sibling workspace strategies, `suffix` and `none`. The `none` strategy resolves the sibling
`workspace_dir` to the configured primary path for every launched workspace, which is the right behavior for shared
personal checkouts such as dotfiles and notes.

The audited Obsidian memory says `~/bob/` is the Obsidian vault. Local inspection confirms that `/home/bryan/bob` is a
Git repo with remote `bbugyi200/bob.git`.

## Design

Add a second static sibling repo entry directly next to the existing `chezmoi` entry:

```yaml
- name: obsidian
  path: ~/bob
  description: Obsidian/Bob notes vault and Git-backed Markdown knowledge base.
  workspace:
    strategy: none
```

Use `obsidian` as the SASE alias because it is the prompt-facing concept and will produce clear environment variables
such as `SASE_SIBLING_REPO_OBSIDIAN_DIR`. The path preserves the actual vault location and Git checkout name.

Do not change SASE snippets or Lua snippets. The local `home/dot_config/sase/AGENTS.md` snippet-sync rule only applies
to snippet definitions in `sase.yml`; this change only adds a sibling repository entry.

Refresh generated SASE memory so future agents see both configured static siblings in `home/memory/short/sase.md`. The
current file only lists `chezmoi`, and `sase memory init --check` already reports that generated memory needs an update.

## Implementation Steps

1. Patch `home/dot_config/sase/sase.yml` in the chezmoi repo to add the `obsidian` sibling entry immediately after the
   `chezmoi` sibling entry.
2. Refresh `home/memory/short/sase.md` using the SASE memory generator, or apply the equivalent rendered change if the
   generator tries to make unrelated changes.
3. Apply the updated SASE config to the live home directory with a targeted `chezmoi apply ~/.config/sase/sase.yml` so
   running SASE sees the new sibling without waiting for a later full chezmoi apply.
4. Inspect the chezmoi diff to confirm the only intended source changes are the SASE config and generated short memory.

## Verification

Run targeted checks:

- `sase memory init --check` from `/home/bryan/.local/share/chezmoi/home` after the memory refresh, expecting no memory
  drift.
- `sase config show` after the targeted `chezmoi apply`, expecting a `sibling_repos` entry with `name: obsidian`,
  `path: ~/bob`, and `workspace.strategy: none`.
- A resolver-level check, if useful, confirming the resolved Obsidian sibling uses `/home/bryan/bob` for both primary
  and workspace paths.

Do not treat full `sase validate` as the acceptance gate for this small config change. It currently fails before any
edits because the chezmoi home tree has unrelated generated SDD README drift and no `home/sdd` directory.

Run `just check` from the chezmoi repo if the local toolchain is available; if it fails for unrelated environment
reasons, report that separately from the targeted SASE verification.
