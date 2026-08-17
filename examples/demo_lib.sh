# demo_lib.sh — the shared shell harness for the interactive demo
# scripts (demo_isolette.sh; demo_rocq.sh predates it and still carries
# its own copy). Source it AFTER setting:
#
#   LOG_DIR    scratch dir for logs/snapshots (the sourcing script owns it)
#   PY         the venv python
#   FAST       1 = skip pauses and opt-in diffs (unattended)
#   NO_VSCODE  1 = never open VSCode; terminal diffs only
#
# Provides: banner, pause, run_logged, saw, expect, expect_absent,
# show_diff, offer_diff, offer_diff_json, has_tty.

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
LOG="$LOG_DIR/last_run.log"

# ── one demo at a time ──────────────────────────────────────────────────────
# Every demo tampers and restores the SAME live target tree, goldens,
# and fixtures: two concurrent runs corrupt each other's beats (one
# run's mid-scene restore lands inside the other's episode). The lock
# is shared across demo scripts. acquire_demo_lock arms a release trap;
# a script that later installs its own EXIT trap must call
# release_demo_lock from it.

acquire_demo_lock() {
  DEMO_LOCK="$REPO/.demo.lock"
  if ! mkdir "$DEMO_LOCK" 2>/dev/null; then
    local pid
    pid="$(cat "$DEMO_LOCK/pid" 2>/dev/null)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "DEMO ABORT: another demo run (pid $pid) holds $DEMO_LOCK." >&2
      echo "Concurrent demo runs tamper and restore the same live tree —" >&2
      echo "wait for it to finish (or kill it) and re-run." >&2
      exit 1
    fi
    echo "(stale demo lock from pid ${pid:-unknown} — taking over)"
  fi
  echo $$ > "$DEMO_LOCK/pid"
  trap release_demo_lock EXIT
}

release_demo_lock() { rm -rf "${DEMO_LOCK:-}" 2>/dev/null; }

banner() {
  echo
  echo "${BOLD}════════════════════════════════════════════════════════════════${RESET}"
  echo "${BOLD}  $1${RESET}"
  echo "${BOLD}════════════════════════════════════════════════════════════════${RESET}"
  [ $# -gt 1 ] && printf '%s\n' "${@:2}"
  echo
}

# prompt <text> — render a prompt so it is visible EVERYWHERE the
# paired `read </dev/tty` can run. Hard-won rules (each was a real
# invisible-prompt bug in some terminal/harness):
#   - as a COMPLETE line: line-buffered displays never render a
#     partial line, so a newline-less prompt is invisible there
#   - on STDOUT: `read -p` uses stderr (hidden by some harnesses),
#     and some UIs render the piped stdout stream but never show
#     direct /dev/tty writes — even while /dev/tty INPUT works
#   - ALSO to /dev/tty when stdout is not a terminal: a plain
#     `./demo.sh | tee log` would otherwise bury the prompt in the
#     pipe; skipped when stdout is a tty (no double print)
#   - without dim styling: ESC[2m is near-invisible on some themes
prompt() {
  printf '%s\n' "$1"
  if [ ! -t 1 ] && { : >/dev/tty; } 2>/dev/null; then
    printf '%s\n' "$1" >/dev/tty
  fi
}

pause() {
  [ "$FAST" = 1 ] && return 0
  has_tty || return 0
  prompt "-- press Enter to continue --"
  read -r _ </dev/tty
}

# run_logged <cwd> <cmd...> — echo, run from <cwd>, tee into $LOG.
# PYTHONUNBUFFERED: through the tee pipe python BLOCK-buffers, so a
# driver's output would sit invisible until process exit — the demo
# looks hung during every long measurement without it.
run_logged() {
  local cwd="$1"; shift
  echo "${DIM}\$ $*${RESET}"
  ( cd "$cwd" && PYTHONUNBUFFERED=1 "$@" ) 2>&1 | tee "$LOG"
}

saw() { grep -q "$1" "$LOG"; }

expect() {  # expect <pattern> <what went wrong>
  if ! saw "$1"; then
    echo
    echo "DEMO ABORT: expected '$1' in the last run — $2" >&2
    exit 1
  fi
}

expect_absent() {  # expect_absent <pattern> <what went wrong>
  if saw "$1"; then
    echo
    echo "DEMO ABORT: found '$1' in the last run — $2" >&2
    exit 1
  fi
}

has_tty() { { : </dev/tty; } 2>/dev/null; }

show_diff() {  # show_diff <golden-copy> <live-copy> — always shown
  if [ "$NO_VSCODE" = 0 ] && command -v code >/dev/null 2>&1; then
    echo "opening the diff in VSCode (golden vs proposed) ..."
    code --diff "$1" "$2"
  else
    echo "── golden vs proposed ─────────────────────────────────────────"
    diff -u "$1" "$2" || true
    echo "───────────────────────────────────────────────────────────────"
  fi
}

offer_diff() {  # offer_diff <left> <right> <label> — opt-in artifact diff
  [ "$FAST" = 1 ] && return 0
  has_tty || return 0
  local a=""
  echo
  prompt "${BOLD}[v]iew diff — $3 / Enter to continue: ${RESET}"
  read -r a </dev/tty
  case "$a" in
    v|V)
      # snapshot BOTH sides before returning: callers often restore the
      # live file on the very next line, and VSCode reads its files
      # asynchronously — diffing the live path would race the restore
      # and render an empty diff
      local snap
      snap="$(mktemp -d "$LOG_DIR/diff.XXXXXX")"
      mkdir -p "$snap/before" "$snap/after"
      cp "$1" "$snap/before/$(basename "$1")"
      cp "$2" "$snap/after/$(basename "$2")"
      if [ "$NO_VSCODE" = 0 ] && command -v code >/dev/null 2>&1; then
        code --diff "$snap/before/$(basename "$1")" "$snap/after/$(basename "$2")"
      else
        diff -u "$snap/before/$(basename "$1")" "$snap/after/$(basename "$2")" || true
      fi ;;
  esac
}

offer_diff_json() {  # offer_diff_json <left> <right> <label> — pretty-printed
  [ "$FAST" = 1 ] && return 0
  has_tty || return 0
  local pp
  pp="$(mktemp -d "$LOG_DIR/json.XXXXXX")"
  mkdir -p "$pp/before" "$pp/after"
  "$PY" -c "
import json, sys
for src, dst in ((sys.argv[1], sys.argv[2]), (sys.argv[3], sys.argv[4])):
    json.dump(json.load(open(src)), open(dst, 'w'), indent=1)
" "$1" "$pp/before/$(basename "$1")" "$2" "$pp/after/$(basename "$2")" \
    || return 0
  offer_diff "$pp/before/$(basename "$1")" "$pp/after/$(basename "$2")" "$3"
}
