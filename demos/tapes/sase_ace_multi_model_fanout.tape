Output demos/out/sase_ace_multi_model_fanout.mp4
Output demos/out/sase_ace_multi_model_fanout.gif

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
Set TypingSpeed 55ms
Set Framerate 30
Set CursorBlink false
Set WaitTimeout 40s

Env COLORTERM "truecolor"
Env TERM "xterm-256color"

Hide
Type "repo_root=$PWD"
Enter
Type "export PATH=$repo_root/.venv-demos/bin:$PATH"
Enter
Type "unset FORCE_COLOR NO_COLOR"
Enter
Type "unset SASE_AGENT SASE_AGENT_NAME SASE_AGENT_CL_NAME SASE_AGENT_PROJECT_FILE SASE_AGENT_TIMESTAMP SASE_AGENT_ROOT_TIMESTAMP SASE_AGENT_CHAT_PATH SASE_ARTIFACTS_DIR SASE_BEAD_ID SASE_ACTIVE_PROJECT_DIR"
Enter
Type "unset SASE_GH_PRE_ALLOCATED SASE_GH_WORKSPACE_DIR SASE_GH_WORKSPACE_NUM SASE_CHOP_LUMBERJACK SASE_CHOP_NAME SASE_CHOP_RUN_ID SASE_INTERNAL_AGENT_NAME_BYPASS"
Enter
Type "export SASE_ACE_RELEASE_VERSION_TITLE=1"
Enter
Type "rm -rf /tmp/sase-ace-demo.mFan0Ut5"
Enter
Type "eval $(./demos/scripts/seed_sase_ace_demo /tmp/sase-ace-demo.mFan0Ut5)"
Enter
Type "unset FAKEY_SCENARIO"
Enter
Type "export FAKEY_DELAY=300"
Enter
Type "export FAKEY_REPLY='Demo agent completed.'"
Enter
Type "export SASE_LLM_EXEC_PROVIDER=fakey"
Enter
Type "export FAKEY_STATE_DIR=$SASE_DEMO_ROOT/fakey-state"
Enter
Type "sase agent index rebuild --json >/dev/null"
Enter
Type "cd $SASE_DEMO_GITHUB_WORKSPACE"
Enter
Type "clear"
Enter
Show

Type "sase ace --refresh-interval 1 --tab agents -x"
Hide
Enter
Wait+Screen /Agents/
Wait+Screen /nova--code/
Show
Sleep 1s

Space
Wait+Screen /Type prompt/
Sleep 500ms

Type "#gh:acme/nova "
Wait+Screen /#gh:acme\/nova/
Sleep 600ms
Type "%{"
Sleep 500ms
Type "%m:opus | "
Sleep 500ms
Type "%m:@gpt53 | "
Sleep 500ms
Type "%m:@pro31h} "
Sleep 600ms
Type "Harden the command parser against malformed input and add regression tests."
Sleep 1200ms

Enter
Wait+Screen /0\.cld/
Wait+Screen /0\.cdx/
Wait+Screen /0\.agy/
Sleep 5s

Type "k"
Type "x"
Wait+Screen /Kill Agent/
Sleep 900ms
Type "y"
Wait+Screen /Killed/
Sleep 700ms

Type "k"
Type "x"
Wait+Screen /Kill Agent/
Sleep 600ms
Type "y"
Sleep 900ms

Type "k"
Type "x"
Wait+Screen /Kill Agent/
Sleep 600ms
Type "y"
Wait+Screen /Killed/
Sleep 3s

Hide
Type "q"
Sleep 1s
Type "exit"
Enter
