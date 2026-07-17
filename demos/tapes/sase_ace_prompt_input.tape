Output demos/out/sase_ace_prompt_input.mp4
Output demos/out/sase_ace_prompt_input.gif

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
Type "rm -rf /tmp/sase-ace-demo.pIn4Qw2c"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.pIn4Qw2c)"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 -x"
Hide
Enter
Wait+Screen /Agents/
Wait+Screen /nova--review/
Wait+Screen /nova--plan-1/
Show
Sleep 2s

Space
Wait+Screen /history/
Sleep 1s

Type "+nov"
Wait+Screen /#git:nova/
Sleep 800ms
Ctrl+L
Wait+Screen /#git:nova/
Sleep 800ms

Type "Add parser coverage with "
Type "#add_te"
Wait+Screen /add_tests/
Sleep 800ms
Ctrl+L
Wait+Screen /file_path/
Sleep 800ms
Type "src/nova/par"
Ctrl+T
Wait+Screen /parser.py/
Sleep 800ms
Ctrl+L
Sleep 600ms
Type " "
Sleep 600ms

Type "and inspect @docs/rel"
Ctrl+T
Wait+Screen /release_checklist.md/
Sleep 800ms
Ctrl+L
Sleep 1s

Escape
Sleep 500ms
Type "g-"
Wait+Screen /Prompt.*2 agents/
Sleep 1s
Type "Check the CLI help path after the parser changes."
Sleep 800ms

Enter
Wait+Screen /Launch all/
Sleep 2.5s
Escape
Sleep 2s

Hide
Ctrl+C
Sleep 700ms
Ctrl+C
Sleep 700ms
Type "q"
Sleep 4s
Type "exit"
Enter
