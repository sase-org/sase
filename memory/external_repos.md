## External Repos

### Chezmoi Repo

Some files associated with this project live in the ~/.local/share/chezmoi/ directory. If you modify files in this repo,
make sure to run `just check` (in the chezmoi repo) before terminating / replying to the user. Chezmoi files related to
sase that I know about:

- The sase.yml files that I use to configure sase can be found in the ~/.local/share/chezmoi/home/dot_config/sase/
  directory.

IMPORTANT: After committing to this repo, you MUST run the `chezmoi apply` command. Otherwise, the changes to the
chezmoi files will not be applied to the system (i.e. copied to their proper locations).

### Plugin Repos

- The ../sase-github and ../sase-google directories are git repositories that contain plugins for GitHub and Mercurial
  VCS providers, respectively.
- The ../sase-telegram directory is a git repository that contains a plugin for Telegram integration (implemented using
  chops).
- The ../sase-nvim directory is a git repository that contains a plugin for Neovim integration (ex: for project spec
  file syntax highlighting).

IMPORTANT: You can edit files in these repos if necessary. Just make sure to run the `just check` command in each plugin
repo that you've modified before terminating / replying to the user.
