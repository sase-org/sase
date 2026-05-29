---
create_time: 2026-05-29 16:36:51
status: done
prompt: sdd/prompts/202605/amd_home_agents.md
---
# Manage Home AGENTS.md With AMD

## Context

The current AMD implementation already supports `amd_h1_title` in bundled defaults, the public config schema, and
project-local `sase.yml` files. The important missing piece is scope: `sase amd init` only reads `<root>/sase.yml`, so a
user-level `~/.config/sase/sase.yml` or `sase_*.yml` overlay cannot opt the home-level `~/AGENTS.md` or chezmoi source
equivalent into full AMD management.

The existing behavior that ignores global `amd_h1_title` for ordinary project roots is correct and should be preserved.
That default prevents accidentally replacing a project's custom `AGENTS.md` with generated AMD content.

The active home source of truth is the chezmoi source tree at:

- `~/.local/share/chezmoi/home/AGENTS.md`
- `~/.local/share/chezmoi/home/memory/...`
- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`

There is an unrelated dirty chezmoi change in `home/dot_hammerspoon/init.lua`; this plan must not touch or revert it.

## Plan

1. Update AMD title resolution

   Add a small scoped title-loading path in `src/sase/amd/init.py`:
   - Keep project-local `<root>/sase.yml` as the only source for project roots.
   - Treat `Path.home()` as the live home root and `sase.config.core.CHEZMOI_HOME` as the chezmoi home source root.
   - For those home roots only, allow the merged user SASE config's `amd_h1_title` to provide the title.
   - Include `~/.config/sase/sase_*.yml` overlays in that merged user config, because the requested source file is
     `sase_athena.yml`.
   - When running against the chezmoi source root, prefer reading user config from the chezmoi source files under
     `dot_config/sase/` so freshly edited source config works before or independent of `chezmoi apply`.
   - Validate the value with the same semantics as today: `string` or `null`, trim whitespace, and reject empty strings.

2. Preserve conservative project behavior

   Adjust tests around `tests/main/test_amd_init.py` so they prove:
   - A global/user `amd_h1_title` still does not manage an ordinary project `AGENTS.md`.
   - The live home root can be managed from user config.
   - The chezmoi source root can be managed from source-side `dot_config/sase/sase_*.yml`.
   - A project-local `sase.yml` still opts that project in and takes precedence for that project.

3. Extend memory-init integration only if needed

   `sase memory init` currently enables AMD sync for the project root but not the home root. The user's requested
   verification command is `sase amd init`, so this is not strictly required for the first deliverable. If the helper
   refactor makes it cheap and low-risk, add focused coverage so home AMD sync can be reused by memory init later; do
   not widen behavior beyond the home/chezmoi scope.

4. Migrate Obsidian memory in chezmoi

   In the chezmoi source tree:
   - Move `home/memory/short/obsidian.md` to `home/memory/long/obsidian.md`.
   - Add frontmatter with a useful `description` and keywords such as `Obsidian`, `bob`, `notes`, `ob`, and
     `obsidian-headless` so it can appear as dynamic long-term memory.
   - Expand the body to state:
     - `~/bob/` is the Obsidian vault and "my notes" generally refers to it.
     - This machine uses `obsidian-headless` through the `ob` command to support Obsidian Sync.
     - The previous zorg migration exists as context, but Bryan has fully switched to Obsidian and does not use zorg
       anymore.
     - New `~/bob/` Markdown notes should include a `parent` frontmatter field that links to another Markdown file in
       `~/bob/`.

5. Update user config source

   Add:

   ```yaml
   amd_h1_title: "athena - Bryan Bugyi's Home Server"
   ```

   to `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml`.

6. Regenerate home `AGENTS.md`

   Run `sase amd init` from the chezmoi home source root, verify that:
   - `home/AGENTS.md` is fully AMD-managed with the requested H1.
   - The Tier 1 short-memory list no longer includes `obsidian.md`.
   - The Tier 3 long-memory list includes `memory/long/obsidian.md`.
   - Provider shims in the same root point to `@AGENTS.md`.

7. Validate

   Run focused tests first:

   ```bash
   pytest tests/main/test_amd_init.py tests/main/test_init_memory_handler.py tests/main/test_init_memory_chezmoi.py tests/test_config_schema.py
   ```

   Because the SASE repo will have code changes, run the repository-required validation:

   ```bash
   just install
   just check
   ```

   For the chezmoi repo, run a syntax/config smoke check at minimum:

   ```bash
   python - <<'PY'
   from pathlib import Path
   import yaml
   for path in [
       Path.home() / ".local/share/chezmoi/home/dot_config/sase/sase_athena.yml",
       Path.home() / ".local/share/chezmoi/home/memory/long/obsidian.md",
   ]:
       text = path.read_text(encoding="utf-8")
       if path.suffix in {".yml", ".yaml"}:
           yaml.safe_load(text)
   PY
   ```

   If time allows and the chezmoi repo's local tooling is not blocked by unrelated changes, run its `just check` as a
   secondary validation. Do not commit unless explicitly asked.
