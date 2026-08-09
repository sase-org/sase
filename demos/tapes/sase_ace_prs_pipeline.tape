Output demos/out/sase_ace_prs_pipeline.mp4
Output demos/out/sase_ace_prs_pipeline.gif

Require bash
Require ttyd
Require ffmpeg
Require sase

Set Shell "bash"
Set FontFamily "Fira Code"
Set FontSize 20
Set Width 1920
Set Height 1080
Set Padding 20
Set LineHeight 1.2
Set Theme "GitHub Dark"
Set TypingSpeed 75ms
Set Framerate 30
Set CursorBlink false
Set WaitTimeout 15s

Env COLORTERM "truecolor"
Env TERM "xterm-256color"

Hide
Type "repo_root=$PWD"
Enter
Type "export PATH=$repo_root/.venv/bin:$PATH"
Enter
Type "unset FORCE_COLOR NO_COLOR"
Enter
Type "export SASE_ACE_RELEASE_VERSION_TITLE=1"
Enter
Type "rm -rf /tmp/sase-ace-demo.jsaIeSv0"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.jsaIeSv0)"
Enter
Type "echo '+nova OR %s' > $SASE_HOME/last_query.txt"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 --tab artifacts -x"
Hide
Enter
Wait+Screen /PRs/
Wait+Screen /Patch: 1\/5/
Wait+Screen /group: by project/
Wait+Screen /nova_prompt_input/
Wait+Screen /DESCRIPTION:/
Wait+Screen /STITCHES:/
Wait+Screen /HOOKS:/
Wait+Screen /PASSED/
Show
Sleep 2.5s

Type ">"
Sleep 500ms
Type "a"
Wait+Screen /nova_cli_refresh/
Wait+Screen /PARENT:/
Wait+Screen /STATUS: WIP/
Sleep 1.8s

Type "<"
Wait+Screen /nova_prompt_input/
Wait+Screen /STATUS: Ready/
Wait+Screen /TIMESTAMPS:/
Sleep 1.8s

Type "j"
Wait+Screen /nova_parser_edges/
Wait+Screen /STATUS: Draft/
Wait+Screen /PASSED/
Sleep 1.4s

Type "j"
Wait+Screen /nova_cli_refresh/
Wait+Screen /STATUS: WIP/
Sleep 1.4s

Type "j"
Wait+Screen /nova_release_notes/
Wait+Screen /STATUS: Mailed/
Wait+Screen /STITCHES:/
Wait+Screen /CHAT:/
Sleep 1.6s

Type "j"
Wait+Screen /nova_seed_cleanup/
Wait+Screen /STATUS: Submitted/
Wait+Screen /TIMESTAMPS:/
Sleep 1.8s

Type "k"
Wait+Screen /nova_release_notes/
Wait+Screen /STATUS: Mailed/
Sleep 1.4s

Type "o"
Wait+Screen /group: by date/
Sleep 1.4s
Type "o"
Wait+Screen /group: by status/
Wait+Screen /Mailed/
Wait+Screen /Ready/
Wait+Screen /Submitted/
Sleep 2s

Type "H"
Wait+Screen /group: by status/
Wait+Screen /1 PR/
Sleep 1.8s

Type "L"
Wait+Screen /nova_release_notes/
Wait+Screen /nova_prompt_input/
Sleep 2s

Hide
Type "q"
Sleep 700ms
Type "exit"
Enter
