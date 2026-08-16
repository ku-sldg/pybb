#!/usr/bin/env bash
#
# demo_rocq.sh — the end-to-end demo workflow on the Rocq example, as an
# interactive wrapper around examples/temp_control_rocq.py.
#
# The outline this script walks (demo_workflow.docx, Rocq-only for now):
#
#   scene 1  clean baseline episode over every artifact class the example
#            has: model (blessed Props.v/Acceptance.v), contracts (decl
#            slices), verification (dune build + kernel assumptions
#            audit), with the rocq/dune tools measured-then-used.
#   scene 2  a spec edit drifts the model -> the episode escalates ->
#            YOU examine the diff (VSCode if available) and rule at the
#            prompt: [b]less the change as the new baseline, or [r]evert
#            to golden. Two selectable flavors: benign (a bound change;
#            proofs still hold) or breaking (a restatement that compiles
#            but refutes a seed proof). Blessing sanctions the SPEC only
#            (--provision --bless-model re-signs the model class; the
#            verification tier's tool-hash bundle is untouched), so the
#            breaking flavor blesses FIRST — spec-first — and the next
#            episode shows model/contracts clean with verification
#            refuting the not-yet-proved obligation, which proof repair
#            (--repair-proofs) then adapts.
#   scene 3  restore at two grains: --immutable-model (whole-file: model
#            files never drift — the failed hash appraisal IS the repair
#            order, no interaction) and --repair-granularity slice (only
#            the violated declaration is spliced back, by NAME — benign
#            drift elsewhere survives, and the model entry ends attested
#            clean via the contracts refinement).
#   scene 4  verification failure -> repair by selectable strategy:
#            portfolio (deterministic, keyless), llm (behind the
#            portfolio; dry-run without a key), or pause (out-of-band —
#            you repair, fresh measurement judges); with the failure-time
#            checklist and the archived signed evidence.
#   scene 5  baseline tamper -> the repair that must refuse, three beats:
#            a flipped byte of signed bundle evidence (signature refutes),
#            a hand-edited installed golden (anchor refutes, signature
#            silent), and LAUNDERING — the tampered spec re-provisioned
#            into a fully self-consistent contracts bundle, refuted by
#            the blessing's derivability check (slice goldens must be
#            extractable from the blessed signed bytes). Each stops
#            attestation before it starts; no KS can repair a baseline —
#            the only exit is the administrator's out-of-band re-bless.
#   scene 6  toolchain tamper -> a functionality-PRESERVING edit to the
#            rocq wrapper still refutes the measure-then-use tool hash;
#            every proof cell poisons fail-closed ('?'), and the honest
#            repair is the out-of-band pause rung: hash-only artifacts
#            are unrepairable from goldens by design, so YOU restore the
#            tool and fresh measurement re-establishes standing (a false
#            claim buys nothing but another look).
#   scene 7  audit tamper -> the audit file's RENDERING is hashed against
#            its blessed canonical bytes (measure-then-use) because its
#            sections bind to goals only through the file's structure.
#            Beat 1: a deleted Print Assumptions line. Beat 2: a query
#            SUBSTITUTED for a different closed constant — count right,
#            sections all Closed, output check fooled; only the byte
#            anchor refutes. Repair is the THIRD species: REGENERATION —
#            the file is a rendering of AM config, re-rendered and
#            re-attested.
#   scene 8  implementation tamper -> the ladder repairs the RIGHT
#            artifact: the impl is inverted (elaborates fine; the
#            blessed goals are genuinely FALSE of it), so proof repair
#            exhausts — the exhaustion IS the diagnosis — and the impl
#            rung re-derives the implementation from the blessed
#            statements alone (deterministic spec-guided engine, no
#            API keys; --llm would add the LLM behind it). The proofs
#            end untouched.
#
# Repair strategies beyond the portfolio (LLM synthesis, the --pause
# out-of-band rung) exist in the driver and become demo variants later:
# see --repair-strategy.
#
# Flags:
#   --no-vscode            never open VSCode; show the diff in the terminal
#   --repair-strategy S    scene 4's repair: portfolio (default; keyless) |
#                          llm (real with ANTHROPIC_API_KEY, dry-run
#                          without) | pause (out-of-band: you repair,
#                          measurement judges); prompted interactively
#                          when not given
#   --scenes "1 2 3 4 ..."  run a subset of scenes
#   --fast                 skip the press-Enter pauses (for testing)
#   --auto bless|revert    answer scene 2's ruling automatically (testing)
#   --drift benign|breaking  pick scene 2's spec change without prompting
#   --restore-tools        recovery: reinstall the canonical rocq wrapper
#                          (e.g. after an interrupted scene 6), verify its
#                          hash against the BLESSED tool golden, confirm
#                          readiness, and exit
#
# The demo is self-cleaning: whatever you rule in scene 2, the ORIGINAL
# spec and blessing are restored on exit (a real sanctioned change would
# simply stop before the cleanup).

set -u -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
DRIVER="$REPO/examples/temp_control_rocq.py"
PROPS="$REPO/targets/temp-control-rocq/TempControl/Props.v"
GOLDEN_PROPS="$REPO/golden${PROPS}"
EVIDENCE="$REPO/evidence"

NO_VSCODE=0
RESTORE_TOOLS=0
STRATEGY=""
SCENES="1 2 3 4 5 6 7 8"
FAST=0
AUTO=""
DRIFT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --no-vscode) NO_VSCODE=1 ;;
    --repair-strategy) STRATEGY="$2"; shift ;;
    --scenes) SCENES="$2"; shift ;;
    --fast) FAST=1 ;;
    --auto) AUTO="$2"; shift ;;
    --drift) DRIFT="$2"; shift ;;
    --restore-tools) RESTORE_TOOLS=1 ;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

case "$STRATEGY" in
  ""|portfolio|llm|pause) ;;
  *) echo "--repair-strategy takes portfolio|llm|pause" >&2; exit 2 ;;
esac
case "$AUTO" in ""|bless|revert) ;; *) echo "--auto takes bless|revert" >&2; exit 2 ;; esac
case "$DRIFT" in ""|benign|breaking) ;; *) echo "--drift takes benign|breaking" >&2; exit 2 ;; esac

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/demo_rocq.XXXXXX")"
LOG="$LOG_DIR/last_run.log"

banner() {
  echo
  echo "${BOLD}════════════════════════════════════════════════════════════════${RESET}"
  echo "${BOLD}  $1${RESET}"
  echo "${BOLD}════════════════════════════════════════════════════════════════${RESET}"
  [ $# -gt 1 ] && printf '%s\n' "${@:2}"
  echo
}

pause() {
  [ "$FAST" = 1 ] && return 0
  read -r -p "${DIM}-- press Enter to continue --${RESET}" _ </dev/tty
}

run_driver() {
  echo "${DIM}\$ python examples/temp_control_rocq.py $*${RESET}"
  ( cd "$REPO" && "$PY" "$DRIVER" "$@" ) 2>&1 | tee "$LOG"
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

# ── recovery: reinstall the canonical rocq wrapper and prove it ─────────────
if [ "$RESTORE_TOOLS" = 1 ]; then
  WRAPPER="$HOME/Claude_workspace/bin/rocq"
  cat > "$WRAPPER" <<'WRAPEOF'
#!/usr/bin/env bash
# Workspace wrapper: rocq (the Rocq Prover, opam switch 5.2)
# (CVM child processes see this via CvmConfig.path_prepend).
# The opam bin dir is prepended so rocq's own subprocesses (coqc,
# coqdep, ...) resolve from the same pinned switch.
export PATH="$HOME/.opam/5.2/bin:$PATH"
exec "$HOME/.opam/5.2/bin/rocq" "$@"
WRAPEOF
  chmod +x "$WRAPPER"
  echo "reinstalled the canonical wrapper at $WRAPPER"
  ( cd "$REPO" && "$PY" - "$WRAPPER" <<'PYEOF'
import base64, hashlib, json, sys
digest = base64.b64encode(
    hashlib.sha256(open(sys.argv[1], "rb").read()).digest()).decode()
args = json.load(open(
    "tests/fixtures/temp_control_rocq_verification/asp_args.json"))
golden = next(a["golden_b64"] for a in args["hashfile"].values()
              if a.get("filepath", "").endswith("Claude_workspace/bin/rocq"))
if digest == golden:
    print("restored wrapper matches the BLESSED tool golden")
else:
    raise SystemExit(
        "restored wrapper does NOT match the blessed tool golden —\n"
        "the blessed baseline expects different content; if the wrapper\n"
        "legitimately changed, re-bless the tools:\n"
        "    python examples/temp_control_rocq.py --provision --bless-tools")
PYEOF
  ) || exit 1
  run_driver --ready
  expect "readiness: PASS" "readiness must pass after the tool restore"
  echo "${BOLD}toolchain restored and proven — readiness passes.${RESET}"
  exit 0
fi

# ── self-cleaning: restore the original spec + proofs + blessing on exit ────
PROOFS="$REPO/targets/temp-control-rocq/TempControl/Proofs.v"
PRISTINE="$LOG_DIR/Props.v.pristine"
PROOFS_PRISTINE="$LOG_DIR/Proofs.v.pristine"
MODEL_BUNDLE="$REPO/golden/_bundles/temp_control_rocq_model/provision_bundle.json"
MODEL_ARGS="$REPO/tests/fixtures/temp_control_rocq_model/asp_args.json"
BUNDLE_PRISTINE="$LOG_DIR/model_bundle.pristine"
ARGS_PRISTINE="$LOG_DIR/model_asp_args.pristine"
IMPL_FILE="$REPO/targets/temp-control-rocq/TempControl/Impl.v"
IMPL_SCENE8="$LOG_DIR/Impl.v.scene8"
ROCQ_WRAPPER="$HOME/Claude_workspace/bin/rocq"
WRAPPER_PRISTINE="$LOG_DIR/rocq_wrapper.pristine"
AUDIT_FILE="$REPO/targets/temp-control-rocq/Assumptions.v"
AUDIT_PRISTINE="$LOG_DIR/assumptions.pristine"
cp "$PROPS" "$PRISTINE"
cp "$PROOFS" "$PROOFS_PRISTINE"
BLESSED_DURING_DEMO=0
LAUNDERED_DURING_DEMO=0

cleanup() {
  local status=$?
  if ! cmp -s "$PRISTINE" "$PROPS"; then
    cp "$PRISTINE" "$PROPS"
    echo
    echo "cleanup: restored the original $(basename "$PROPS")"
  fi
  if ! cmp -s "$PROOFS_PRISTINE" "$PROOFS"; then
    cp "$PROOFS_PRISTINE" "$PROOFS"
    echo "cleanup: restored the original $(basename "$PROOFS")"
  fi
  for pair in "$BUNDLE_PRISTINE:$MODEL_BUNDLE" "$ARGS_PRISTINE:$MODEL_ARGS" \
              "$WRAPPER_PRISTINE:$ROCQ_WRAPPER" \
              "$IMPL_SCENE8:$IMPL_FILE" \
              "$AUDIT_PRISTINE:$AUDIT_FILE"; do
    save="${pair%%:*}"; live="${pair##*:}"
    if [ -f "$save" ] && ! cmp -s "$save" "$live"; then
      cp "$save" "$live"
      echo "cleanup: restored $(basename "$live") (scene tamper)"
    fi
  done
  if [ "$LAUNDERED_DURING_DEMO" = 1 ]; then
    echo "cleanup: re-provisioning derivable goldens (scene 5 laundering)"
    ( cd "$REPO" && "$PY" "$DRIVER" --provision ) >"$LOG_DIR/cleanup_provision.log" 2>&1 \
      || echo "cleanup: re-provisioning FAILED — see $LOG_DIR/cleanup_provision.log" >&2
  fi
  if [ "$BLESSED_DURING_DEMO" = 1 ]; then
    echo "cleanup: re-blessing the ORIGINAL baseline (the demo blessing was a prop)"
    ( cd "$REPO" && "$PY" "$DRIVER" --provision --bless-model ) >"$LOG_DIR/cleanup.log" 2>&1 \
      || echo "cleanup: re-provisioning FAILED — see $LOG_DIR/cleanup.log" >&2
    echo "note: provisioning refreshes bundle signatures/timestamps under"
    echo "      tests/fixtures/temp_control_rocq_* — 'git checkout' them if unwanted."
  fi
  exit $status
}
trap cleanup EXIT

in_scenes() { case " $SCENES " in *" $1 "*) return 0 ;; *) return 1 ;; esac }

edit_spec() {  # edit_spec <sed-expr> <description>
  local before="$LOG_DIR/Props.v.before_edit"
  cp "$PROPS" "$before"
  sed -i '' -E "$1" "$PROPS"
  if cmp -s "$before" "$PROPS"; then
    echo "DEMO ABORT: the scripted spec edit matched nothing ($2)" >&2
    exit 1
  fi
  echo "applied spec edit: $2"
  ( cd "$REPO" && diff -u "$before" "$PROPS" ) | sed -n '4,20p'
}

show_diff() {  # show_diff <golden-copy> <live-copy>
  if [ "$NO_VSCODE" = 0 ] && command -v code >/dev/null 2>&1; then
    echo "opening the diff in VSCode (golden vs proposed) ..."
    code --diff "$1" "$2"
  else
    echo "── golden vs proposed ─────────────────────────────────────────"
    diff -u "$1" "$2" || true
    echo "───────────────────────────────────────────────────────────────"
  fi
}

has_tty() { { : </dev/tty; } 2>/dev/null; }

offer_diff() {  # offer_diff <left> <right> <label> — opt-in artifact diff
  [ "$FAST" = 1 ] && return 0
  has_tty || return 0
  local a=""
  echo
  read -r -p "${BOLD}[v]iew diff — $3 / Enter to continue: ${RESET}" a </dev/tty
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

# ── setup: provision-if-missing, then the readiness gate ───────────────────
banner "SETUP — readiness (provision the golden baseline if missing)"
if [ ! -f "$REPO/golden/_bundles/temp_control_rocq_model/provision_bundle.json" ]; then
  echo "no blessed baseline found — bootstrap provisioning (bless_lint gated)"
  run_driver --provision
fi
run_driver --ready
expect "readiness: PASS" "readiness must pass before the demo starts"
pause

if in_scenes 1; then
  banner "SCENE 1 — clean baseline episode" \
    "Artifact classes measured: model (blessed spec, signed), contracts" \
    "(decl-named slices), verification (dune build + the kernel's" \
    "assumptions audit), tools measured-then-used inside the term."
  run_driver
  expect "all attested components intact" "the baseline episode must be clean"
  echo
  echo "${BOLD}the goals checklist over the clean baseline:${RESET}"
  run_driver --status
  expect "✓" "every goal must check off over the clean baseline"
  expect_absent "✗" "a refuted goal on the clean baseline means the demo started dirty"
  expect_absent "?" "an unjudged goal on the clean baseline means the demo started dirty"
  pause
fi

apply_breaking_edit() {
  local before="$LOG_DIR/Props.v.before_edit"
  cp "$PROPS" "$before"
  "$PY" - <<'EOF'
from pathlib import Path
import os
p = Path(os.environ["DEMO_PROPS"])
text = p.read_text()
helper = '''(* The command relation: f commands c in the given situation. *)
Definition commands (f : Step) (t : Z) (sp : SetPoint)
                    (l c : FanCmd) : Prop :=
  f t sp l = c.

'''
text = text.replace("(* Goal: currentTemp above the band commands the fan On. *)",
                    helper + "(* Goal: currentTemp above the band commands"
                             " the fan On. *)")
text = text.replace("    high sp < temp -> f temp sp latest = On.",
                    "    high sp < temp -> commands f temp sp latest On.")
p.write_text(text)
EOF
  if cmp -s "$before" "$PROPS"; then
    echo "DEMO ABORT: the breaking spec edit matched nothing" >&2
    exit 1
  fi
  echo "applied spec edit: fanOn_when_hot_prop restated through a new"
  echo "  'commands' relation (the model elaborates; the seed proof will not)"
  ( cd "$REPO" && diff -u "$before" "$PROPS" ) | sed -n '4,26p'
}

if in_scenes 2; then
  banner "SCENE 2 — spec drift: escalate, examine, bless or revert" \
    "A model edit drifts the blessed spec. The episode detects it, names" \
    "the changed declaration, and ESCALATES — the demo (not the episode)" \
    "then asks for your ruling. Two flavors: a benign bound change, or a" \
    "restatement that compiles but leaves the seed proof unprovable —" \
    "blessing THAT one drives the proof-repair workflow."
  if [ -n "$DRIFT" ]; then
    drift="$DRIFT"; echo "(--drift) spec change: $drift"
  else
    echo "Choose the spec drift to demonstrate:"
    echo "  [1] benign    — widen the physical ceiling 110 -> 115"
    echo "                  (existing proofs still prove the new spec)"
    echo "  [2] breaking  — restate fanOn_when_hot_prop through a new"
    echo "                  'commands' relation (the model compiles; the"
    echo "                  seed proof breaks -> proof repair after bless)"
    pick=""
    if has_tty; then
      read -r -p "${BOLD}drift [1/2]: ${RESET}" pick </dev/tty
    fi
    case "$pick" in 2|breaking) drift="breaking" ;; *) drift="benign" ;; esac
  fi
  echo
  if [ "$drift" = "benign" ]; then
    edit_spec 's/high sp <= 110/high sp <= 115/' "SetPoint_valid ceiling 110 -> 115"
  else
    DEMO_PROPS="$PROPS" apply_breaking_edit
  fi
  PROPOSED="$LOG_DIR/Props.v.proposed"
  cp "$PROPS" "$PROPOSED"
  run_driver
  expect "user intervention required" "the drifted episode must escalate"
  expect "failed attestation results" \
    "the failed contract attestation detail must display"
  expect "— modified" "the changed contract must be annotated as modified"
  if [ "$drift" = "breaking" ]; then
    expect "moved (content unchanged)" \
      "shifted-but-unchanged slices must be told apart from the real change"
  fi
  echo
  echo "${BOLD}The episode escalated (and quarantined the live tree back to golden).${RESET}"
  echo "Your ruling on the proposed spec change:"
  show_diff "$GOLDEN_PROPS" "$PROPOSED"
  if [ -n "$AUTO" ]; then
    answer="$AUTO"; echo "(--auto) ruling: $answer"
  else
    answer=""
    if has_tty; then
      read -r -p "${BOLD}[b]less as the new baseline / [r]evert to golden: ${RESET}" answer </dev/tty
    fi
  fi
  case "$answer" in
    b|bless)
      echo
      echo "re-applying the change and RE-BLESSING (the sanctioning act) ..."
      echo "Blessing sanctions the SPEC — whether the proofs currently verify"
      echo "is the episode's question, not the blessing's."
      cp "$PROPOSED" "$PROPS"
      run_driver --provision --bless-model
      BLESSED_DURING_DEMO=1
      echo
      echo "fresh episode against the NEW baseline:"
      run_driver
      if [ "$drift" = "breaking" ]; then
        expect "all attested components intact" \
          "model and contracts must attest clean against the new blessing"
        expect "user intervention required" \
          "verification must refute the not-yet-proved blessed obligation"
        echo
        echo "${BOLD}The spec is blessed; the proofs have not caught up.${RESET}"
        echo "Model and contracts attest clean against the NEW baseline, but"
        echo "verification refutes: the seed proof no longer proves the blessed"
        echo "obligation. The workflow now repairs the proofs (portfolio),"
        echo "judged by fresh measurement:"
        cp "$PROOFS" "$LOG_DIR/Proofs.v.prerepair"
        run_driver --repair-proofs --keep
        expect "repaired and re-attested clean in-session" \
          "proof repair must adapt the proofs to the blessed model"
        offer_diff "$LOG_DIR/Proofs.v.prerepair" "$PROOFS" \
          "the machine-adapted proof (seed vs what the portfolio wrote)"
        echo
        echo "confirming with a fresh episode:"
        run_driver
      fi
      expect "all attested components intact" \
        "the blessed change must attest clean against the new baseline"
      ;;
    *)
      echo
      echo "reverted: the escalation already restored the live tree to golden;"
      echo "confirming with a fresh episode:"
      run_driver
      expect "all attested components intact" "the reverted tree must attest clean"
      ;;
  esac
  echo
  echo "${BOLD}the goals checklist after the ruling:${RESET}"
  run_driver --status
  expect "✓" "every goal must check off after the ruling settles"
  expect_absent "✗" "no goal may stay refuted after the ruling settles"
  expect_absent "?" "no goal may stay unjudged after the ruling settles"
  pause
fi

if in_scenes 3; then
  banner "SCENE 3 — restore, at two grains" \
    "Beat 1, --immutable-model: the per-session ruling for automated" \
    "pipelines — model files must never drift; the failed hash appraisal" \
    "IS the repair order, whole-file restore + in-session re-attest, no" \
    "interaction. Beat 2, --repair-granularity slice: the repair unit is" \
    "the MEASUREMENT unit — only the violated declaration is spliced" \
    "back, and benign drift elsewhere in the file survives."
  edit_spec 's/50 <= low sp/45 <= low sp/' "SetPoint_valid floor 50 -> 45"
  run_driver --immutable-model
  expect "repaired and re-attested clean in-session" \
    "immutable-model must restore and re-attest in one session"
  if cmp -s "$GOLDEN_PROPS" "$PROPS"; then
    echo "${BOLD}live spec is byte-identical to golden again.${RESET}"
  else
    echo "DEMO ABORT: live spec still differs from golden" >&2; exit 1
  fi
  echo
  echo "${BOLD}the goals checklist over the restored tree:${RESET}"
  run_driver --status
  expect "✓" "every goal must check off over the restored tree"
  expect_absent "✗" "no goal may stay refuted over the restored tree"
  expect_absent "?" "no goal may stay unjudged over the restored tree"
  pause

  echo
  echo "${BOLD}beat 2 — slice granularity: the repair unit is the measurement unit${RESET}"
  echo "A benign note lands OUTSIDE every declaration, and one blessed"
  echo "slice is corrupted. Whole-file restore would clobber the note;"
  echo "slice restore splices ONLY the violated declaration (located by"
  echo "NAME — insertion-robust). The proof it worked is in the summary:"
  echo "episode 2's model entry passes VIA the contracts refinement —"
  echo "the model hash still failed (the note survived!), and every"
  echo "declaration was intact."
  printf '\n(* engineering note: candidate sensor swap under review *)\n' >> "$PROPS"
  run_driver --tamper --repair --repair-granularity slice
  expect "repair:slice: restored 1 block(s) from golden" \
    "the slice rung must restore exactly the violated declaration"
  expect "temp_control_rocq:model: all attested components intact (temp_control_rocq_contracts passed)" \
    "the model entry must pass VIA contracts — the surviving note is why"
  expect "repaired and re-attested clean in-session" \
    "the spliced declaration must re-attest in one session"
  echo
  echo "(the driver's exit self-clean then restored the note too — demo policy)"
  pause
fi

if in_scenes 4; then
  banner "SCENE 4 — verification failure -> repair (selectable strategy)" \
    "A verification failure, repaired by the strategy of your choice:" \
    "the deterministic tactic portfolio (no keys needed), the LLM engine" \
    "behind the portfolio, or the out-of-band pause rung — YOU repair," \
    "fresh measurement judges. Standing never comes from the repair's" \
    "own claim."
  if [ -z "$STRATEGY" ]; then
    if [ "$FAST" = 1 ]; then
      STRATEGY="portfolio"
    else
      echo "Choose the repair strategy:"
      echo "  [1] portfolio — deterministic tactic search (default; no API keys)"
      echo "  [2] llm       — LLM engine behind the portfolio (real calls with"
      echo "                  ANTHROPIC_API_KEY set; keyless dry-run otherwise)"
      echo "  [3] pause     — out-of-band: the episode blocks while YOU repair"
      pick=""
      if has_tty; then
        read -r -p "${BOLD}strategy [1/2/3]: ${RESET}" pick </dev/tty
      fi
      case "$pick" in
        2|llm) STRATEGY="llm" ;;
        3|pause) STRATEGY="pause" ;;
        *) STRATEGY="portfolio" ;;
      esac
    fi
  fi
  echo "repair strategy: $STRATEGY"
  echo

  case "$STRATEGY" in
    portfolio|llm)
      echo "${BOLD}A seed proof is corrupted (wrong tactic, statement untouched).${RESET}"
      echo "First the goals checklist over the BROKEN tree — the failing"
      echo "contract refuted with its diagnostic, every OTHER proof judged"
      echo "from its own derived isolation variant:"
      PROOFS_SCENE4="$LOG_DIR/Proofs.v.scene4"
      cp "$PROOFS" "$PROOFS_SCENE4"
      ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, 'examples')
import temp_control_rocq as t, rocq_workflow as rw
rw._break_proof(t.CONFIG)" )
      run_driver --status
      expect "✗" "the checklist must display the failing contract"
      expect "isolated: proof intact" \
        "the isolation variants must judge the intact proofs individually"
      offer_diff "$PROOFS_SCENE4" "$PROOFS" \
        "the corrupted proof (seed vs the wrong tactic)"
      cp "$PROOFS_SCENE4" "$PROOFS"
      pause
      echo
      if [ "$STRATEGY" = "llm" ]; then
        LLM_FLAGS="--llm anthropic"
        if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
          LLM_FLAGS="$LLM_FLAGS --llm-dry-run"
          echo "${BOLD}no ANTHROPIC_API_KEY in the environment — the LLM engine runs${RESET}"
          echo "${BOLD}as a DRY-RUN (prompts recorded, spend predicted, no calls);${RESET}"
          echo "${BOLD}the portfolio ahead of it on the ladder still does the proving:${RESET}"
        else
          echo "${BOLD}the engine ladder: portfolio first, the LLM on whatever remains:${RESET}"
        fi
        # shellcheck disable=SC2086
        run_driver --break-proof --keep $LLM_FLAGS
      else
        echo "${BOLD}now the repair arc — the same proof broken, then re-proved:${RESET}"
        run_driver --break-proof --keep
      fi
      expect "repaired and re-attested clean in-session" \
        "the repair must end in good standing"
      offer_diff "$PROOFS_SCENE4" "$PROOFS" \
        "the machine-repaired proof (seed vs what the engine wrote)"
      cp "$PROOFS_SCENE4" "$PROOFS"
      ;;
    pause)
      echo "${BOLD}One proof is Admitted — the build stays green (this is Rocq),${RESET}"
      echo "${BOLD}the kernel's assumptions audit refutes the goal by name, and the${RESET}"
      echo "${BOLD}episode BLOCKS on the out-of-band pause rung: no engine, no${RESET}"
      echo "${BOLD}restore — the repair is yours, and only fresh measurement can${RESET}"
      echo "${BOLD}re-establish standing.${RESET}"
      if [ "$FAST" = 1 ]; then
        echo "(unattended: answering [s]kip — the decline path, escalation follows)"
        printf 's\n' | run_driver --tamper-admitted --pause
        expect "user intervention required" \
          "declining the operator gate must fall through to escalation"
        expect "Restored pristine" \
          "the tamper arc must restore the pristine proofs on exit"
      else
        echo
        echo "when the work order appears, repair in ANOTHER terminal:"
        echo "    cd $REPO && git checkout -- targets/temp-control-rocq/TempControl/Proofs.v"
        echo "then answer [r]e-attest. (Answer [s]kip to see the escalation path.)"
        run_driver --tamper-admitted --pause
        if saw "repaired and re-attested clean in-session"; then
          echo "${BOLD}your repair stood — judged by measurement, not by your word.${RESET}"
        else
          expect "user intervention required" \
            "skip must fall through to escalation"
          echo "${BOLD}declined — the episode escalated rather than trust a claim.${RESET}"
        fi
      fi
      ;;
  esac
  echo
  echo "${BOLD}The signed evidence of the re-measurement (NOT a re-blessing):${RESET}"
  latest_evidence="$(ls -t "$EVIDENCE" 2>/dev/null | head -1)"
  [ -n "$latest_evidence" ] && ls "$EVIDENCE/$latest_evidence" | sed "s|^|  evidence/$latest_evidence/|"
  pause
fi

if in_scenes 5; then
  banner "SCENE 5 — baseline tamper: the repair that must refuse" \
    "Now the TRUST STATE itself is attacked — the live tree stays" \
    "pristine throughout. Readiness re-appraises the signed provisioning" \
    "record (appraisal-only CVM run: sig_appr verifies the bundle," \
    "goldenbytes anchors the installed goldens to the signed evidence)" \
    "and refuses to START attestation. No knowledge source can repair a" \
    "baseline — the ready entry's failure chain is empty BY DESIGN," \
    "provisioning is unreachable from failure handling — so the only" \
    "exit is the administrator's out-of-band re-bless."
  cp "$MODEL_BUNDLE" "$BUNDLE_PRISTINE"
  cp "$MODEL_ARGS" "$ARGS_PRISTINE"
  # scene-ENTRY spec capture: beat 3 must restore to the spec the
  # CURRENT blessing covers — which is not the demo-start pristine if
  # scene 2 blessed a change earlier in this same run
  SCENE5_PROPS="$LOG_DIR/Props.v.scene5"
  cp "$PROPS" "$SCENE5_PROPS"

  echo "${BOLD}beat 1 — tamper the signed record: flip ONE byte of stored evidence${RESET}"
  "$PY" - "$MODEL_BUNDLE" <<'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
raw = d[0][0]["RawEv"]
i = max(range(1, len(raw)), key=lambda k: len(raw[k]))  # largest payload; never slot 0, the signature
s = raw[i]
raw[i] = s[:10] + ("A" if s[10] != "A" else "B") + s[11:]
json.dump(d, open(path, "w"))
print(f"flipped one character of RawEv slot {i} in the model bundle")
PYEOF
  run_driver
  expect "bundle signature verification FAILED" \
    "a tampered bundle byte must break the signature"
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  offer_diff_json "$BUNDLE_PRISTINE" "$MODEL_BUNDLE" \
    "one flipped byte of signed evidence (pristine vs tampered bundle)"
  cp "$BUNDLE_PRISTINE" "$MODEL_BUNDLE"
  echo
  echo "${BOLD}the record itself was not authentic — restored; now the other side:${RESET}"
  pause

  echo "${BOLD}beat 2 — tamper the installation: hand-edit one installed golden${RESET}"
  "$PY" - "$MODEL_ARGS" <<'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
t = d["readfile"]["temp_control_rocq_model_props_targ"]
g = t["golden_b64"]
t["golden_b64"] = g[:10] + ("A" if g[10] != "A" else "B") + g[11:]
json.dump(d, open(path, "w"), indent=2)
print("flipped one character of the INSTALLED golden for Props.v")
PYEOF
  run_driver
  expect "Blessed-content appraisal failed" \
    "an edited installed golden must fail the anchor to the signed evidence"
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  expect_absent "signature verification FAILED" \
    "the bundle is authentic in this beat — only the anchor may refute"
  offer_diff_json "$ARGS_PRISTINE" "$MODEL_ARGS" \
    "one hand-edited installed golden (pristine vs tampered asp_args)"
  cp "$ARGS_PRISTINE" "$MODEL_ARGS"
  echo
  echo "${BOLD}restored — now the smarter adversary:${RESET}"
  pause

  echo "${BOLD}beat 3 — laundering: tamper the spec, re-provision it into the goldens${RESET}"
  echo "The live spec is edited, then an ORDINARY re-provision re-derives"
  echo "and RE-SIGNS the contracts baseline from the tampered tree. The"
  echo "laundered bundle is fully self-consistent — signature valid,"
  echo "anchors matching: every check from beats 1 and 2 passes. But the"
  echo "BLESSING cannot be laundered: ordinary provisioning refuses to"
  echo "touch the model class, and readiness re-derives every contract"
  echo "slice from the blessed SIGNED bytes:"
  LAUNDERED_DURING_DEMO=1
  sed -i '' 's/50 <= low sp/45 <= low sp/' "$PROPS"
  if cmp -s "$SCENE5_PROPS" "$PROPS"; then
    echo "DEMO ABORT: the laundering spec edit matched nothing" >&2
    exit 1
  fi
  echo "(edited SetPoint_valid floor 50 -> 45 in the live spec)"
  run_driver --provision
  expect "goldens provisioned" "the laundering pass must provision"
  run_driver
  expect "slice golden not extractable from blessed content" \
    "the derivability anchor must refute the laundered slice"
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  expect_absent "signature verification FAILED" \
    "the laundered bundle is self-consistent — only lineage refutes"
  offer_diff "$SCENE5_PROPS" "$PROPS" \
    "what the administrator signed vs the laundered live spec"
  echo
  echo "restoring the spec and re-provisioning derivable goldens:"
  cp "$SCENE5_PROPS" "$PROPS"
  run_driver --provision
  LAUNDERED_DURING_DEMO=0
  echo
  echo "${BOLD}One gate, three attributed refusals: record integrity (signature),${RESET}"
  echo "${BOLD}installation consistency (anchor), semantic lineage (derivability)${RESET}"
  echo "${BOLD}— the blessing is the root that laundering cannot reach. The only${RESET}"
  echo "${BOLD}sanctioned exit is the administrator's re-bless; verify_baseline.py${RESET}"
  echo "${BOLD}is the operator's audit view. Restored — confirming readiness:${RESET}"
  run_driver --ready
  expect "readiness: PASS" "the restored baseline must verify again"
  pause
fi

if in_scenes 6; then
  banner "SCENE 6 — toolchain tamper: measure-then-use catches the tool" \
    "The rocq WRAPPER is edited — functionality preserved (a comment" \
    "line), so every build and audit still runs and looks fine. The" \
    "verification term hashes the toolchain IN THE SAME TERM, before" \
    "using it: the tool hash refutes, and every proof cell poisons to" \
    "'?' fail-closed — whether the change was benign is precisely what" \
    "an unblessed tool cannot be trusted to answer. Readiness still" \
    "PASSES: the stored record is coherent; it is the LIVE tool that" \
    "drifted. Hash-only artifacts are unrepairable from goldens by" \
    "design — the repair is out-of-band, judged by fresh measurement."
  cp "$ROCQ_WRAPPER" "$WRAPPER_PRISTINE"
  printf '# drifted: innocuous-looking edit\n' >> "$ROCQ_WRAPPER"
  echo "appended one comment line to $ROCQ_WRAPPER"
  echo
  echo "${BOLD}the goals checklist under an unblessed tool — everything poisons:${RESET}"
  run_driver --status
  expect "toolchain measurement failed" \
    "the tool-hash failure must poison the checklist"
  expect "?" "poisoned cells must read unknown, never presumed proved"
  expect_absent "✗" "no goal may be REFUTED by a tool drift — only unjudged"
  offer_diff "$WRAPPER_PRISTINE" "$ROCQ_WRAPPER" \
    "the functionality-preserving wrapper edit (one comment line)"
  pause
  echo
  if [ "$FAST" = 1 ]; then
    echo "(unattended: answering [s]kip — the decline path, escalation follows)"
    printf 's\n' | run_driver --pause
    expect "user intervention required" \
      "declining the operator gate must fall through to escalation"
    cp "$WRAPPER_PRISTINE" "$ROCQ_WRAPPER"
    echo
    echo "${BOLD}wrapper restored out-of-band; fresh measurement re-establishes standing:${RESET}"
    run_driver
    expect "all attested components intact" \
      "the restored toolchain must attest clean"
  else
    echo "${BOLD}the episode blocks on the pause rung. Repair in ANOTHER terminal:${RESET}"
    echo "    cp $WRAPPER_PRISTINE $ROCQ_WRAPPER"
    echo "  (or: ./examples/demo_rocq.sh --restore-tools)"
    echo "then answer [r]e-attest. (A claim WITHOUT the repair just buys"
    echo "another failing measurement — try it.)"
    echo "if you get stuck or abort mid-scene, the same --restore-tools flag"
    echo "recovers the toolchain afterwards."
    run_driver --pause
    if saw "repaired and re-attested clean in-session"; then
      echo "${BOLD}your repair stood — judged by measurement, not by your word.${RESET}"
    else
      expect "user intervention required" "skip must fall through to escalation"
      cp "$WRAPPER_PRISTINE" "$ROCQ_WRAPPER"
      echo "${BOLD}declined — escalated; wrapper restored by the demo.${RESET}"
    fi
  fi
  pause
fi

if in_scenes 7; then
  banner "SCENE 7 — audit tamper: the rendering is anchored to config" \
    "The audit file asks the questions; its sections bind to goals only" \
    "through the file's structure — so the RENDERING itself is hashed" \
    "against its blessed canonical bytes, measure-then-use, before any" \
    "section is trusted. Two attacks, one anchor. The repair is the" \
    "third species — neither restore nor synthesis: the file is a" \
    "rendering of AM config, so the rung re-renders it and re-attests."
  cp "$AUDIT_FILE" "$AUDIT_PRISTINE"

  echo "${BOLD}beat 1 — deletion: one Print Assumptions line removed${RESET}"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, 'examples')
import temp_control_rocq as t, rocq_workflow as rw
rw.tamper_audit(t.CONFIG)" )
  echo
  echo "${BOLD}the goals checklist — every cell poisons on the byte anchor:${RESET}"
  run_driver --status
  expect "diverged from its canonical rendering" \
    "the audit-file hash must refute the tampered rendering"
  expect "?" "poisoned cells must read unknown, never presumed proved"
  expect_absent "✗" "a tampered rendering refutes nothing — it unjudges everything"
  offer_diff "$AUDIT_PRISTINE" "$AUDIT_FILE" \
    "the deleted audit query (canonical vs tampered rendering)"
  cp "$AUDIT_PRISTINE" "$AUDIT_FILE"
  echo
  echo "the appraiser's section count remains as DEPTH beneath the hash:"
  echo "it still catches config-vs-blessing drift (goals added without"
  echo "re-rendering and re-blessing)."
  echo
  echo "${BOLD}the repair arc — tamper, regenerate from config, re-attest:${RESET}"
  run_driver --tamper-audit
  expect "regenerated Assumptions.v from config" \
    "the regeneration rung must re-render the audit from config"
  expect "repaired and re-attested clean in-session" \
    "the regenerated audit must re-attest in one session"
  pause

  echo
  echo "${BOLD}beat 2 — substitution: the attack the byte anchor exists for${RESET}"
  echo "One query is swapped for a DIFFERENT closed constant: the section"
  echo "count stays right, every section still reads 'Closed under the"
  echo "global context' — Print Assumptions never echoes its query, so"
  echo "the output check alone is fooled. Only the rendering's hash"
  echo "refutes. First, see how innocent the tamper looks:"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, 'examples')
import temp_control_rocq as t, rocq_workflow as rw
rw.tamper_audit_subst(t.CONFIG)" )
  offer_diff "$AUDIT_PRISTINE" "$AUDIT_FILE" \
    "the substituted audit query (canonical vs tampered rendering)"
  cp "$AUDIT_PRISTINE" "$AUDIT_FILE"
  echo
  run_driver --tamper-audit-subst
  expect "Substituted 'Print Assumptions" \
    "the substitution tamper must apply"
  expect "regenerated Assumptions.v from config" \
    "the regeneration rung must re-render the audit from config"
  expect "repaired and re-attested clean in-session" \
    "the regenerated audit must re-attest in one session"
  pause
fi

if in_scenes 8; then
  banner "SCENE 8 — implementation tamper: the ladder repairs the RIGHT artifact" \
    "The implementation's hot response is inverted. It elaborates fine —" \
    "but the blessed goals are genuinely FALSE of it, so NO proof can" \
    "repair this. The chain runs proofs first; their exhaustion is the" \
    "DIAGNOSIS that the implementation is the artifact at fault, and the" \
    "ladder hands off: the impl rung re-derives the implementation from" \
    "the blessed statements ALONE (deterministic spec-guided engine —" \
    "no API keys), the seed proofs prove again, and the restarted" \
    "episode re-attests. The proofs end byte-untouched: the ladder" \
    "repaired the right artifact."
  SCENE8_PROOFS="$LOG_DIR/Proofs.v.scene8"
  cp "$PROOFS" "$SCENE8_PROOFS"
  cp "$IMPL_FILE" "$IMPL_SCENE8"
  sed 's/then On/then Off/' "$IMPL_SCENE8" > "$LOG_DIR/Impl.v.tampered"
  offer_diff "$IMPL_SCENE8" "$LOG_DIR/Impl.v.tampered" \
    "the behavior inversion the arc is about to apply"
  run_driver --tamper-impl --keep
  expect "Tampered implementation" "the behavior tamper must apply"
  expect "handing to 'synthesis:rocq-impl'" \
    "proof exhaustion must hand off to the implementation rung"
  expect "implemented (RocqSpecGuidedImplEngine)" \
    "the spec-guided engine must re-derive the implementation"
  expect "repaired and re-attested clean in-session" \
    "the re-derived implementation must re-attest in one session"
  if cmp -s "$SCENE8_PROOFS" "$PROOFS"; then
    echo "${BOLD}proofs byte-untouched — the ladder repaired the right artifact.${RESET}"
  else
    echo "DEMO ABORT: the proofs changed during an implementation repair" >&2
    exit 1
  fi
  cp "$IMPL_SCENE8" "$IMPL_FILE"
  pause
fi

banner "DEMO COMPLETE" \
  "postponed, by design: episode-triggering monitor (external scheduler)," \
  "wall-clock repair timeouts, the executable artifact class, LLM and" \
  "pause repair-strategy variants, Rocq --check/--promote (the bless in" \
  "scene 2 is the provision-bootstrap form until promote lands), and a" \
  "hashes-only --bless-tools term (tool blessing independent of tree" \
  "state; today it runs the woven tier and must see a verifying tree)."
