Output demos/out/sase_ace_prompt_history_stash.mp4
Output demos/out/sase_ace_prompt_history_stash.gif

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
Type "rm -rf /tmp/sase-ace-demo.Sx5eykRn"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.Sx5eykRn)"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 0 --tab agents -x"
Hide
Enter
Wait+Screen /Agents/
Wait+Screen /nova--code/
Show
Sleep 2s

Space
Wait+Screen /Type prompt/
Sleep 1s

Ctrl+K
Wait+Screen /Select Prompt from History/
Wait+Screen /History/
Wait+Screen /Inspect command fixtures/
Sleep 1.2s

Ctrl+N
Sleep 600ms
Ctrl+N
Wait+Screen /renderer summary output/
Sleep 1.2s

Ctrl+X
Wait+Screen /Draft a risky renderer/
Sleep 1s

Type "fixtures"
Wait+Screen /tests\/fixtures\/commands.txt/
Sleep 1.4s

Tab
Wait+Screen /Inspect command fixtures/
Sleep 800ms
Type " Include renderer parity notes."
Wait+Screen /renderer parity notes/
Sleep 1.2s

Ctrl+S
Wait+Screen /Stashed prompt/
Sleep 1.2s

Space
Wait+Screen /Type prompt/
Sleep 700ms
Ctrl+S
Wait+Screen /Stashed prompts \(1\)/
Wait+Screen /Inspect command fixtures/
Sleep 1.5s

Enter
Wait+Screen /Restored prompt/
Wait+Screen /renderer parity notes/
Sleep 1.5s

Escape
Sleep 600ms
Hide
Ctrl+C
Sleep 700ms
Type "q"
Sleep 4s
Type "exit"
Enter
