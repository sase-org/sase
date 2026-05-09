---
keywords: [chezmoi, plugin, sase-github, sase-telegram, sase-nvim, sase-core, dotfile]
---

# External Repos

## Chezmoi Repo

Some files associated with this project live in the ~/.local/share/chezmoi/ directory. If you modify files in this repo,
make sure to run `just check` (in the chezmoi repo) before terminating / replying to the user. Chezmoi files related to
sase that I know about:

- The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
  directory.

IMPORTANT: After committing to this repo, you MUST run the `chezmoi apply --force` command. Otherwise, the changes to
the chezmoi files will not be applied to the system (i.e. copied to their proper locations).

## Plugin Repos

- The ../sase-github directory is a git repository that contains the maintained plugin for GitHub VCS and workspace
  providers.
- The ../sase-telegram directory is a git repository that contains a plugin for Telegram integration (implemented using
  chops).
- The ../sase-nvim directory is a git repository that contains a plugin for Neovim integration (ex: for project spec
  file syntax highlighting).
- The ../sase-core directory is the Rust core backend repository for shared backend/domain behavior.

IMPORTANT: You can edit files in these repos if necessary. Just make sure to run the `just check` command in each plugin
repo that you've modified before terminating / replying to the user.
