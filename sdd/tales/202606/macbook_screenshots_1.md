---
create_time: 2026-06-14 19:23:26
status: done
prompt: sdd/prompts/202606/macbook_screenshots_1.md
---
# Plan: MacBook Screenshot Bridge for SASE Prompts

## Objective

Add a small screenshot bridge that lets Bryan capture a selected area on the MacBook, upload the image to Apollo, and
then reference the most recent uploaded screenshots from SASE prompts on Athena with `#sshot` or `#sshot:<n>`.

The design uses Apollo only as the shared rendezvous host. The MacBook never needs to SSH directly into Athena, and
Athena only needs to fetch files from Apollo when a prompt asks for a screenshot.

## Current Context

- Chezmoi source is `/home/bryan/.local/share/chezmoi/home`.
- Chezmoi executable scripts under `home/bin/executable_*` are installed on PATH without the `executable_` prefix.
- `home/bin/executable_macscrot` already exists, but it is currently an `osascript` script that prompts for a filename
  and saves to `~/org/img/<name>.png`.
- Hammerspoon config lives at `home/dot_hammerspoon/init.lua`.
- Global user xprompts live in `home/dot_xprompts`; `home/dot_xprompts/sshot.yml` will become `~/.xprompts/sshot.yml`.
- SASE workflows support hidden `bash` steps with typed outputs followed by a `prompt_part` step.
- SASE prompt preprocessing already understands `@path` file references, so the screenshot workflow should expand to an
  `@<local-image-path>` reference rather than only prose.

## Implementation

### 1. Replace `macscrot` with a Bash capture-and-upload script

Rewrite `/home/bryan/.local/share/chezmoi/home/bin/executable_macscrot` as a Bash script.

Behavior:

- Create `~/tmp/screenshots` if it does not exist.
- Generate a timestamped `.png` path such as `~/tmp/screenshots/20260614_191530.png`.
- Run macOS native interactive capture with `/usr/sbin/screencapture -i -t png <path>`.
- Treat cancel or an empty output file as a clean failure and remove any empty file.
- Ensure the same directory exists on Apollo with `ssh apollo 'mkdir -p ~/tmp/screenshots'`.
- Copy the screenshot to Apollo at `~/tmp/screenshots/<same-basename>.png` with `scp -p`.
- Print the local and remote paths on success so Hammerspoon callbacks and manual runs are debuggable.

Keep the script name as `macscrot` rather than adding a new command, because that command already exists in Bryan's
dotfiles and matches the current screenshot intent.

### 2. Add a Hammerspoon screenshot hotkey

Update `/home/bryan/.local/share/chezmoi/home/dot_hammerspoon/init.lua` with a new binding:

```lua
hs.hotkey.bind({ "ctrl", "alt", "shift" }, "s", nil, function()
  -- run ~/bin/macscrot asynchronously
end)
```

Use `hs.task.new("/bin/bash", ..., { "-l", "-c", "$HOME/bin/macscrot" })` so Hammerspoon does not block while the user
selects the screenshot region. If practical, add a short success/failure notification from the task callback using the
script stdout/stderr.

### 3. Add the global `#sshot` xprompt workflow

Add `/home/bryan/.local/share/chezmoi/home/dot_xprompts/sshot.yml`.

Workflow shape:

- Input `n`, type `int`, default `1`.
- Hidden `bash` step `fetch`:
  - Validate that `n >= 1`.
  - Ask Apollo for the `n`th most recent supported image in `~/tmp/screenshots`, sorted newest first.
  - Supported suffixes should include at least `.png`, `.jpg`, `.jpeg`, `.webp`, and `.gif`.
  - Copy the selected Apollo file into Athena's `~/tmp/screenshots/<basename>`.
  - Emit `local_path=<absolute-local-path>` as a typed `path` output.
- `prompt_part` step:
  - Expand to `@{{ fetch.local_path }}` so a prompt containing `#sshot` becomes a concrete image file reference.

This keeps the user-facing behavior simple:

- `#sshot` fetches the most recent screenshot.
- `#sshot:2` fetches the second most recent screenshot.

### 4. Make the xprompt available on Athena

After adding the chezmoi source file, run a targeted apply for only the new xprompt target:

```bash
chezmoi apply ~/.xprompts/sshot.yml
```

Do not globally apply all chezmoi changes, because the chezmoi repo currently has unrelated dirty generated skill files
that should not be touched as part of this task.

The MacBook-side script and Hammerspoon source changes can be picked up on the MacBook through the normal chezmoi apply
flow there.

## Validation

Run static checks that do not require a macOS GUI:

- `bash -n /home/bryan/.local/share/chezmoi/home/bin/executable_macscrot`
- YAML parse/load check for `home/dot_xprompts/sshot.yml` through SASE's workflow loader, or an equivalent Python YAML
  parse if the loader is not convenient.
- `luac -p /home/bryan/.local/share/chezmoi/home/dot_hammerspoon/init.lua` if `luac` is installed.

Run integration checks where available:

- On Athena, verify `#sshot` is discoverable after the targeted chezmoi apply.
- If Apollo already has screenshots, run the fetch step or a minimal `ssh apollo` listing smoke test.
- On the MacBook, manually press `ctrl+alt+shift+s`, capture a region, and confirm the same basename exists under
  `~/tmp/screenshots` locally and on Apollo.

## Risks and Mitigations

- If the MacBook user cancels the screenshot UI, the script should exit nonzero without uploading a stale or empty file.
- If Apollo has no screenshots, `#sshot` should fail with a clear message rather than expanding to an invalid path.
- If a filename contains spaces, `scp` quoting becomes harder. The script-generated timestamp names will not contain
  spaces, so the workflow can assume bridge-created screenshots are space-free.
- Apollo selection depends on Unix tooling on Apollo. Use conservative shell commands and keep the remote command scoped
  to `~/tmp/screenshots`.
