---
plan: sdd/tales/202606/prompt_ctrl_r_recursive_finder.md
---
 The prompt input widget already has support for the `<ctrl+t>` keymap for file path completion (among other things). Can you help me add support for a new `<ctrl+r>` keymap that supports user-filtered (as they type), recursive (on the directory that was to the left of the user's cursor when they pressed `<ctrl+r>`) file path completion?

- The `<ctrl+r>` keymap should also be supported when the `<ctrl+t>` keymap's completion window is still open. In that case, we run the same completion directory target that we would have if the selected entry was the directory to the left of the user's cursor.
- When the user presses `<enter>` the selected directory/file path should be expanded where the cursor was.
- Make sure we support the `<ctrl+n/p>` keymaps for navigating the file paths.
- These directory/file paths should be shown in a large new TUI panel. I want you to lead the design on this one. Just make sure it looks beautiful!

Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: File scope

> How should the recursive <ctrl+r> finder decide which files to list under the target directory?

- [x] **Git-aware (recommended)** — In a git repo, list tracked + untracked-but-not-ignored files (respects .gitignore). Outside git, fall back to a filesystem walk that skips dotdirs and heavy dirs (node_modules, __pycache__, target, .venv). Fast and clutter-free.
- [ ] **Plain walk, skip dotdirs** — Always filesystem-walk; skip directories starting with . only. Ignores .gitignore (may show node_modules, build artifacts).
- [ ] **List everything** — Walk and show every file and directory with no exclusions at all.

#### Q2: Match style

> How should the as-you-type filter match against the recursive file paths?

- [x] **Fuzzy subsequence (recommended)** — fzf/Telescope-style: characters match in order anywhere in the relative path, ranked by match quality (consecutive runs, word/segment-boundary, filename hits score higher). Best UX for deep trees.
- [ ] **Substring match** — Simple case-insensitive substring of the typed text against the relative path. Predictable but weaker for deep trees.

%xprompts_enabled:true