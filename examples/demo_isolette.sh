#!/usr/bin/env bash
#
# demo_isolette.sh — the end-to-end demo workflow on the SysMLv2 -> Rust
# isolette (the INSPECTA seL4/Microkit exemplar), as an interactive
# wrapper around examples/isolette_rust.py --frontend sysml. The scene
# outline mirrors examples/demo_rocq.sh on the Rocq example.
#
#   scene 1  clean baseline episode over every artifact class the
#            example has: files (13 whole-file hashes: SysML packages +
#            contract-bearing Rust), contracts (67 report slices, l2),
#            verification (cargo-verus over 7 crates, always-run), the
#            verus toolchain hashed measure-then-use in the same term,
#            and the blessed props baseline verified at readiness.
#   scene 2  implementation tamper -> the ladder repairs the RIGHT
#            artifact: a PRE-GENERATED DUMMY BAD IMPLEMENTATION replaces
#            the developer-owned compute logic wholesale (heat ON in
#            INIT and FAILED modes, NORMAL responses inverted). It
#            compiles fine; the blessed contracts are genuinely FALSE of
#            it. The diagnosis rung finds every contract slice
#            byte-identical to golden — the exhaustion IS the diagnosis
#            — and hands to the impl rung (crate-scoped restore,
#            standing in for a spec-guided engine). The model and the
#            contract slices end untouched.
#   scene 3  a spec edit drifts the model -> the episode escalates ->
#            YOU examine the diff (VSCode if available) and rule at the
#            prompt: [b]less the change as the new baseline, or
#            [r]evert to golden. Three drift flavors: benign (an
#            equivalent restatement in Regulate.sysml), breaking
#            (REQ_MHS_1 flipped), and range (the Table A-12 upper-alarm
#            ceiling widened 102 -> 103 in the shared GUMBO library —
#            guarantee and assume move together, so a bless survives
#            the catch-up and re-proves). Blessing is SPEC-FIRST
#            (--provision --bless-props re-signs the props class; no
#            codegen), so the blessed model attests clean while the
#            generated realization has not caught up — the catch-up is
#            the SANCTIONED pipeline (--promote: tool gate -> real
#            SysML codegen -> gold -> re-bless). Promotion NEVER
#            verifies: blessing is authority, and whether the impl
#            proves against the blessed spec is the following episode's
#            honest measurement. Two selectable flavors: benign (a
#            semantically equivalent restatement; the regenerated
#            contracts still PROVE, episode green) or breaking
#            (REQ_MHS_1's initialize guarantee flipped Off -> Onn —
#            codegen accepts it, gold MOVES, and the episode reports the
#            Verus tier RED because the implementation cannot honor the
#            blessed spec; walk back or fix the impl).
#   scene 4  restore at two grains: --immutable-model (the failed hash
#            appraisal IS the repair order — whole-file restore +
#            in-session re-attest, no interaction) and
#            --repair-granularity slice (only the violated contract
#            slice is spliced back by CONTENT ALIGNMENT — a benign note
#            elsewhere in the same file survives, and the files entry
#            ends attested clean via the l2 refinement).
#   scene 5  verification failure -> repair by selectable strategy: the
#            implementation drifts in its DEVELOPER-OWNED region, so
#            integrity attests clean at finer granularity (every
#            contract slice intact) while the always-run verus tier
#            refutes the crate — the generated contracts are genuinely
#            false of the drifted behavior. Strategies: restore (the
#            failing crate's hashed files from golden, judged by fresh
#            measurement in-session) or pause (out-of-band: YOU repair,
#            measurement judges).
#   scene 6  baseline tamper -> the repair that must refuse, three
#            beats: a flipped byte of signed bundle evidence (signature
#            refutes), a hand-edited installed golden (anchor refutes,
#            signature silent), and LAUNDERING — a tampered spec
#            re-provisioned into fully self-consistent measurement
#            baselines, refuted by the props blessing's derivability
#            check. Each stops attestation before it starts; the only
#            exit is the administrator's out-of-band re-bless.
#   scene 7  toolchain tamper -> a functionality-PRESERVING edit to the
#            cargo-verus wrapper still refutes the measure-then-use
#            tool hash; every proof cell poisons fail-closed ('?'), and
#            the honest repair is the out-of-band pause rung.
#   scene 8  report tamper -> the rendering is anchored: the attestation
#            report is the AUTHORITY every protocol dir is derived from
#            — targets bind to contracts only through its structure —
#            so the report itself is hashed measure-then-use as its own
#            always-run entry. Beat 1: a deleted slice. Beat 2: a slice
#            span SUBSTITUTED for a different contract's — counts right,
#            structure plausible, only the byte anchor refutes. Repair
#            is the REGENERATION species: the report is a rendering of
#            the model through the measured codegen toolchain, so the
#            rung re-emits it (tool gate first) and re-attests.
#   scene 9  proof cheat -> two beats. Beat 1 (ADMIT): assume(false)
#            admits a verified contract in a bridge file; files/contracts
#            green, cargo-verus reports the same success — the proof is
#            hollow. Beat 2 (SMUGGLE): an external_body broadcast proof
#            fn with 'ensures false' planted in the shared GUMBO_Library.
#            It verifies clean on its own and is inert until a
#            'broadcast use' pulls it in, so it changes NO proof outcome.
#            Both sites are byte-anchored by the gensrc tier now, so two
#            detectors refuse together: the byte anchor says SOMETHING
#            changed, the cheat scan (assume/admit/external_body/axiom/
#            broadcast/uninterp counts vs an exact golden) says WHAT
#            KIND — a proof ESCAPE — and the ladder's diagnosis rung
#            correlates them. The cheat scan alone guards the promote
#            boundary, where gold legitimately moves and byte-blessing
#            would bless whatever codegen emitted. No repair rung:
#            escalates.
#   scene 10 the hollow SYSTEM proof -> two attacks on sys_nominal_proof
#            (the compositional proof crate) that add no escape
#            construct (cheat scan silent) AND change no verification
#            outcome (Verus tier silent — it judges correctness, not
#            surface size). Beat 1 SHRINK: drop a proof module -> the
#            smaller crate still verifies (0 errors). Beat 2 SWAP: drop
#            a real VC + add a trivial one. Both leave every
#            verification green; ONLY the whole-file sysproof hash
#            refuses. Bytes anchor what a proof outcome cannot.
#   scene 11 the stale dependency cache -> a verdict that never looked:
#            the verus tier's 8 primary crates genuinely re-verify every
#            run, but the foundation crates (data, GUMBO_Library) are
#            consumed as cargo DEPENDENCIES, and cargo's dep freshness
#            is mtime-gated. A spec predicate in GUMBO_Library is
#            flipped SEMANTICALLY (no construct-count change) with the
#            file's mtime preserved nanosecond-exact: the cheat scan
#            counts no new escape and the warm cache serves the STALE
#            pre-tamper artifact. Beat 1, the horror: the TIERS
#            DISAGREE — the gensrc byte anchor refuses while the Verus
#            tier sits green over a system proof that is FALSE of the
#            live bytes ('verification succeeded' is a verdict about
#            bytes the verifier last LOOKED at); the stale-green gate
#            doubles as a regression canary for the pinned toolchain's
#            cache behavior. Beat 2 adds the dependency-freshness guard
#            (--fresh-deps: content-hash the dep sources against a
#            seeded record, bump mtimes on drift): the dep re-verifies
#            from the live bytes and sys_nominal_proof honestly refutes
#            (8 VCs) — the verdicts agree again. No repair rung: the
#            refusal escalates; the driver's restore is mtime-aware
#            both ways (coherent caches after beat 1, an honest rebuild
#            after beat 2).
#   scene 12 the unverified foundation -> bytes under the proof tower:
#            beat 1 inverts the heat command inside the unsafe FFI glue
#            (unsafe_put_heat_control) — plain unverified Rust behind an
#            external_body boundary Verus never reads. Every proof
#            passes, the cheat scan counts no new escape, no
#            report-named file moved: ONLY the gensrc byte anchor
#            refuses, and its diagnosis rung classifies the drift
#            (cheat counts CLEAN — a semantic edit no construct scan
#            can see), which is exactly why the ladder never rescues on
#            a clean cheat scan. Beat 2 repairs by REGENERATION (scene
#            8's species): tool gate -> real codegen re-emits the
#            generated sources from the blessed model -> the restarted
#            episode re-attests, judged by fresh measurement.
#   scene 13 implementation drift: benign, re-verified -> a
#            semantically equivalent rewrite of the developer-owned
#            NORMAL-mode guard, OUTSIDE every marker block. Slices and
#            marker blocks stay byte-identical; only the whole-file
#            hash moves; the files entry passes via the l2 refinement
#            and the confirmation chain RE-VERIFIES the rewrite — the
#            benign change survives, no restore.
#   scene 14 contract drift: breaking, restored -> the model is
#            untouched, but the generated REQ_MHS_2 ensures is WEAKENED
#            and the impl inverted to match: cargo-verus SUCCEEDS (self-
#            consistent), yet the contract has drifted from the blessed
#            model. The report emits no slice for compute_cases
#            realizations, so the drift lands between l2 slices — but
#            the l1b MARKER tier measures every contract-block byte,
#            refuses, and its repair rung splices the golden contract
#            back. The restored TRUE contract then refutes the inverted
#            impl: the scene ends on that exposed Verus refusal (the
#            implementation repair is scene 2's ladder).
#
# Flags:
#   --no-vscode            never open VSCode; show diffs in the terminal
#   --repair-strategy S    scene 5's repair: restore (default; from
#                          golden, keyless) | pause (out-of-band: you
#                          repair, measurement judges); prompted
#                          interactively when not given
#   --scenes "1 2 3 ..."   run a subset of scenes
#   --drift benign|breaking|range  pick scene 3's spec change without prompting
#   --auto bless|revert    answer scene 3's ruling automatically (testing;
#                          unattended runs with no tty default to revert)
#   --fast                 skip the press-Enter pauses (for testing)
#   --restore-tools        recovery: reinstall the canonical cargo-verus
#                          wrapper (e.g. after an interrupted scene 7),
#                          verify its hash against the BLESSED tool
#                          golden, confirm readiness, and exit
#
# The demo is self-cleaning: tampered targets, bundles, and goldens are
# restored on exit (measurement targets additionally self-clean at the
# end of every driver run).

set -u -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
DRIVER="$REPO/examples/isolette_rust.py"

REGULATE="$REPO/targets/isolette-microkit/sysml/Regulate.sysml"
GOLDEN_REGULATE="$REPO/golden$REGULATE"
GUMBO_SYSML="$REPO/targets/isolette-microkit/sysml/GUMBO_Library.sysml"
GOLDEN_GUMBO_SYSML="$REPO/golden$GUMBO_SYSML"
GUMBO_LIB_RS="$REPO/targets/isolette-microkit/hamr/microkit/crates/GUMBO_Library/src/lib.rs"
REPORT="$REPO/targets/isolette-microkit/hamr/microkit/attestation/sysml_attestation_report.json"
MHS_APP="$REPO/targets/isolette-microkit/hamr/microkit/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs"
GOLDEN_MHS_APP="$REPO/golden$MHS_APP"
MHS_API="$REPO/targets/isolette-microkit/hamr/microkit/crates/thermostat_rt_mhs_mhs/src/bridge/thermostat_rt_mhs_mhs_api.rs"
PROPS_BUNDLE="$REPO/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json"
PROPS_ARGS="$REPO/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json"
VERUS_ARGS_FIXTURE="$REPO/tests/fixtures/isolette_sysmlv2_rust_verus/asp_args.json"
VERUS_WRAPPER="$HOME/Claude_workspace/bin/cargo-verus"
EVIDENCE="$REPO/evidence"

NO_VSCODE=0
RESTORE_TOOLS=0
STRATEGY=""
SCENES="1 2 3 4 5 6 7 8 9 10 11 12 13 14"
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
    -h|--help) sed -n '2,156p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

case "$STRATEGY" in
  ""|restore|pause) ;;
  *) echo "--repair-strategy takes restore|pause" >&2; exit 2 ;;
esac
case "$AUTO" in ""|bless|revert) ;; *) echo "--auto takes bless|revert" >&2; exit 2 ;; esac
case "$DRIFT" in ""|benign|breaking|range) ;; *) echo "--drift takes benign|breaking|range" >&2; exit 2 ;; esac

LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/demo_isolette.XXXXXX")"
# shellcheck source=demo_lib.sh
. "$REPO/examples/demo_lib.sh"
acquire_demo_lock

run_driver() {
  run_logged "$REPO" "$PY" "$DRIVER" --frontend sysml "$@"
}

# the slow beats print nothing while the CVM churns — say so up front,
# or a healthy run reads as a hang
note_slow() { echo "${DIM}(measurements running — first output can take ~30-60s)${RESET}"; }

# ── recovery: reinstall the canonical cargo-verus wrapper and prove it ──────
if [ "$RESTORE_TOOLS" = 1 ]; then
  # KEEP IN SYNC WITH scripts/install.sh (wrappers step): the installed
  # wrapper must be byte-identical to this heredoc or the hash gate fails.
  cat > "$VERUS_WRAPPER" <<'WRAPEOF'
#!/usr/bin/env bash
# Workspace wrapper: cargo-verus with the Verus distribution and cargo on PATH
# (CVM child processes see this via CvmConfig.path_prepend).
export PATH="$HOME/Claude_workspace/verus-dist:$HOME/.cargo/bin:$PATH"
exec "$HOME/Claude_workspace/verus-dist/cargo-verus" "$@"
WRAPEOF
  chmod +x "$VERUS_WRAPPER"
  echo "reinstalled the canonical wrapper at $VERUS_WRAPPER"
  ( cd "$REPO" && "$PY" - "$VERUS_WRAPPER" "$VERUS_ARGS_FIXTURE" <<'PYEOF'
import base64, hashlib, json, sys
digest = base64.b64encode(
    hashlib.sha256(open(sys.argv[1], "rb").read()).digest()).decode()
args = json.load(open(sys.argv[2]))
golden = next(a["golden_b64"] for a in args["hashfile"].values()
              if a.get("filepath", "").endswith("Claude_workspace/bin/cargo-verus"))
if digest == golden:
    print("restored wrapper matches the BLESSED tool golden")
else:
    raise SystemExit(
        "restored wrapper does NOT match the blessed tool golden —\n"
        "the blessed baseline expects different content; if the wrapper\n"
        "legitimately changed, re-provision the tool baselines:\n"
        "    python examples/isolette_rust.py --frontend sysml --provision")
PYEOF
  ) || exit 1
  run_driver --ready
  expect "readiness: PASS" "readiness must pass after the tool restore"
  echo "${BOLD}toolchain restored and proven — readiness passes.${RESET}"
  exit 0
fi

# ── self-cleaning: restore tampered artifacts on exit ───────────────────────
REGULATE_PRISTINE="$LOG_DIR/Regulate.sysml.pristine"
GUMBO_SYSML_PRISTINE="$LOG_DIR/GUMBO_Library.sysml.pristine"
MHS_PRISTINE="$LOG_DIR/mhs_app.rs.pristine"
BUNDLE_PRISTINE="$LOG_DIR/props_bundle.pristine"
ARGS_PRISTINE="$LOG_DIR/props_asp_args.pristine"
WRAPPER_PRISTINE="$LOG_DIR/cargo_verus_wrapper.pristine"
cp "$REGULATE" "$REGULATE_PRISTINE"
cp "$GUMBO_SYSML" "$GUMBO_SYSML_PRISTINE"
cp "$MHS_APP" "$MHS_PRISTINE"
cp "$PROPS_BUNDLE" "$BUNDLE_PRISTINE"
cp "$PROPS_ARGS" "$ARGS_PRISTINE"
cp "$VERUS_WRAPPER" "$WRAPPER_PRISTINE"
LAUNDERED_DURING_DEMO=0
BLESSED_DURING_DEMO=0

cleanup() {
  local status=$?
  # file-level restores FIRST: a scene-3 re-bless below re-derives the
  # props fixtures/bundles fresh, and must not be stomped afterwards
  for pair in "$REGULATE_PRISTINE:$REGULATE" "$GUMBO_SYSML_PRISTINE:$GUMBO_SYSML" \
              "$MHS_PRISTINE:$MHS_APP" \
              "$BUNDLE_PRISTINE:$PROPS_BUNDLE" "$ARGS_PRISTINE:$PROPS_ARGS" \
              "$WRAPPER_PRISTINE:$VERUS_WRAPPER"; do
    save="${pair%%:*}"; live="${pair##*:}"
    if [ "$BLESSED_DURING_DEMO" = 1 ]; then
      case "$live" in "$PROPS_BUNDLE"|"$PROPS_ARGS") continue ;; esac
    fi
    if [ -f "$save" ] && ! cmp -s "$save" "$live"; then
      cp "$save" "$live"
      echo "cleanup: restored $(basename "$live") (scene tamper)"
    fi
  done
  if [ "$BLESSED_DURING_DEMO" = 1 ]; then
    echo
    echo "cleanup: restoring the isolette target tree and re-blessing the"
    echo "         ORIGINAL baseline (the demo blessing was a prop)"
    ( cd "$REPO" && git checkout -- targets/isolette-microkit ) \
      || echo "cleanup: git checkout FAILED — restore targets/isolette-microkit by hand" >&2
    ( cd "$REPO" && "$PY" "$DRIVER" --frontend sysml --provision --bless-props ) \
      >"$LOG_DIR/cleanup_bless.log" 2>&1 \
      || echo "cleanup: re-blessing FAILED — see $LOG_DIR/cleanup_bless.log" >&2
    echo "note: provisioning refreshes bundle signatures/timestamps under"
    echo "      tests/fixtures/isolette_sysmlv2_rust_* — 'git checkout' them if unwanted."
  fi
  if [ "$LAUNDERED_DURING_DEMO" = 1 ]; then
    echo "cleanup: re-provisioning derivable goldens (scene 6 laundering)"
    ( cd "$REPO" && "$PY" "$DRIVER" --frontend sysml --provision ) \
      >"$LOG_DIR/cleanup_provision.log" 2>&1 \
      || echo "cleanup: re-provisioning FAILED — see $LOG_DIR/cleanup_provision.log" >&2
    echo "note: provisioning refreshes bundle signatures/timestamps under"
    echo "      tests/fixtures/isolette_sysmlv2_rust_* — 'git checkout' them if unwanted."
  fi
  # scene 11's freshness sidecar is session state, never persisted
  rm -f "$REPO/.dep_freshness.json"
  release_demo_lock
  exit $status
}
trap cleanup EXIT

in_scenes() { case " $SCENES " in *" $1 "*) return 0 ;; *) return 1 ;; esac }

edit_spec() {  # edit_spec <sed-expr> <description> [file (default Regulate.sysml)]
  local file="${3:-$REGULATE}"
  local before="$LOG_DIR/$(basename "$file").before_edit"
  cp "$file" "$before"
  sed_i -E "$1" "$file"
  if cmp -s "$before" "$file"; then
    echo "DEMO ABORT: the scripted spec edit matched nothing ($2)" >&2
    exit 1
  fi
  echo "applied spec edit: $2"
  ( cd "$REPO" && diff -u "$before" "$file" ) | sed -n '4,20p'
}

# ── setup: provision-if-missing, then the readiness gate ───────────────────
banner "SETUP — readiness (provision the golden baseline if missing)" \
  "The readiness gate: protocol configuration checks plus verification" \
  "of every SIGNED golden baseline (l1a hashes, l2 slices, the blessed" \
  "props model files, the verus tool hashes) before any attestation."
if [ ! -f "$REPO/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json" ] \
   || [ ! -f "$REPO/golden/_bundles/isolette_sysmlv2_rust_report/provision_bundle.json" ]; then
  echo "no blessed baseline (or no report baseline) found — bootstrap provisioning"
  run_driver --provision
fi
note_slow
run_driver --ready
expect "readiness: PASS" "readiness must pass before the demo starts"
pause
if in_scenes 1; then
  banner "SCENE 1 — clean baseline episode" \
    "Artifact classes measured: files (13 whole-file hashes: SysML" \
    "packages + contract-bearing Rust), contracts (67 report slices)," \
    "verification (cargo-verus over 7 crates, ALWAYS-RUN — the Rocq" \
    "example's three-entry shape), the report RENDERING every protocol" \
    "is derived from, and the verus toolchain hashed measure-then-use" \
    "inside the same term."
  note_slow
  run_driver --verify
  expect "isolette_sysmlv2_rust:files: all attested components intact" \
    "the files entry must attest clean on the baseline"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the verification entry must attest clean on the baseline"
  expect "isolette_sysmlv2_rust:gensrc: all attested components intact" \
    "the generated-source byte anchor must attest clean on the baseline"
  expect "isolette_sysmlv2_rust:report: all attested components intact" \
    "the report rendering must attest clean on the baseline"
  echo
  echo "${BOLD}the per-crate proof checklist over the clean baseline:${RESET}"
  run_driver --ready --status
  expect "readiness: PASS" "the checklist run must verify the baselines"
  expect "✓" "every crate must check off over the clean baseline"
  expect_absent "✗" "a refuted crate on the clean baseline means the demo started dirty"
  expect_absent "?" "an unjudged crate on the clean baseline means the demo started dirty"
  pause
fi
if in_scenes 2; then
  banner "SCENE 2 — implementation tamper: the ladder repairs the RIGHT artifact" \
    "A PRE-GENERATED DUMMY BAD IMPLEMENTATION replaces the" \
    "developer-owned compute logic wholesale: heat ON in INIT and" \
    "FAILED modes, both NORMAL responses inverted. It compiles fine —" \
    "but the blessed contracts are genuinely FALSE of it, so NO" \
    "contract-side repair can help. The ladder diagnoses before it" \
    "repairs: every contract slice of the failing crate is" \
    "byte-identical to golden — the exhaustion IS the diagnosis that" \
    "the implementation is the artifact at fault — and the impl rung" \
    "repairs it (crate-scoped restore from golden, standing in for a" \
    "spec-guided Rust engine). The model and the contract slices end" \
    "untouched."
  SCENE8_MHS="$LOG_DIR/mhs_app.rs.scene8"
  cp "$MHS_APP" "$SCENE8_MHS"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
from pathlib import Path
Path(sys.argv[1]).write_text(ex.dummy_bad_impl_text(ex.MHS_APP.read_text()))
" "$LOG_DIR/mhs_app.rs.tampered" )
  offer_diff "$SCENE8_MHS" "$LOG_DIR/mhs_app.rs.tampered" \
    "the behavior inversion the arc is about to apply (dummy bad impl)"
  run_driver --tamper-impl-full --verify --repair-impl
  expect "DUMMY BAD IMPL" "the dummy bad implementation must apply"
  expect "the IMPLEMENTATION is the artifact at fault" \
    "the diagnosis rung must attribute the fault to the implementation"
  expect "repair:whole-file:crate: restored 1 file(s) from golden" \
    "the impl rung must repair exactly the failing crate"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the repaired implementation must prove again"
  expect "repaired and re-attested clean in-session" \
    "the repaired implementation must re-attest in one session"
  if cmp -s "$SCENE8_MHS" "$MHS_APP"; then
    echo "${BOLD}implementation byte-identical to the pre-tamper tree, and the${RESET}"
    echo "${BOLD}model was never flagged — the ladder repaired the right artifact.${RESET}"
  else
    echo "DEMO ABORT: the implementation file did not return to its pre-tamper bytes" >&2
    exit 1
  fi
  pause
fi
if in_scenes 3; then
  banner "SCENE 3 — spec drift: escalate, examine, bless or revert" \
    "A model edit drifts a blessed GUMBO contract. The episode detects" \
    "it, names the changed slices, and ESCALATES — the demo (not the" \
    "episode) then asks for your ruling. Blessing is SPEC-FIRST:" \
    "--provision --bless-props re-signs the props class over the new" \
    "spec, no codegen — whether the generated realization has caught" \
    "up is the SANCTIONED PIPELINE's job (--promote: tool gate -> real" \
    "SysML codegen -> gold -> re-bless). Promotion NEVER verifies —" \
    "the episode after it reports the Verus tier honestly (RED for a" \
    "blessed-but-unmet spec)."
  if ! ( cd "$REPO" && git diff --quiet -- targets/isolette-microkit ); then
    echo "DEMO ABORT: targets/isolette-microkit has uncommitted changes —" >&2
    echo "scene 3's codegen catch-up restores via git checkout" >&2
    exit 1
  fi
  if [ -n "$DRIFT" ]; then
    drift="$DRIFT"; echo "(--drift) spec change: $drift"
  else
    echo "Choose the spec drift to demonstrate:"
    echo "  [1] benign    — restate the lower_is_lower_temp guarantee"
    echo "                  (x <= y  ->  y >= x: semantically equivalent;"
    echo "                  the regenerated contracts still PROVE)"
    echo "  [2] breaking  — flip REQ_MHS_1's initialize guarantee Off ->"
    echo "                  Onn: the model now demands heat ON during"
    echo "                  initialization, which the implementation"
    echo "                  refuses to prove -> the catch-up's proof"
    echo "                  gate must REFUSE"
    echo "  [3] range     — widen the Table A-12 upper-alarm ceiling"
    echo "                  102 -> 103 in the SHARED library constant:"
    echo "                  guarantee and assume move together, so the"
    echo "                  regenerated contracts still PROVE"
    pick=""
    if has_tty; then
      prompt "${BOLD}drift [1/2/3]: ${RESET}"
      read -r pick </dev/tty
    fi
    case "$pick" in 2|breaking) drift="breaking" ;; 3|range) drift="range" ;; *) drift="benign" ;; esac
  fi
  echo
  DRIFT_FILE="$REGULATE"
  if [ "$drift" = "benign" ]; then
    edit_spec 's/lower_desired_temp\.degrees <= upper_desired_temp\.degrees;/upper_desired_temp.degrees >= lower_desired_temp.degrees;/' \
      "lower_is_lower_temp restated (x <= y -> y >= x)"
  elif [ "$drift" = "range" ]; then
    # the Table A-12 alarm ranges live as named constants in the SHARED
    # GUMBO library; widening the ceiling there moves the operator
    # interface's guarantee and the monitor's assumes TOGETHER
    DRIFT_FILE="$GUMBO_SYSML"
    edit_spec 's/def UpperAlarmTemp_upper\(\): Base_Types::Integer_32 := 102\[s32\];/def UpperAlarmTemp_upper(): Base_Types::Integer_32 := 103[s32];/' \
      "Table A-12 upper-alarm ceiling widened (102 -> 103) in the shared library" \
      "$GUMBO_SYSML"
  else
    # anchored to the initialize guarantee: the compute-case copies of
    # this clause carry a leading 'guarantee' keyword, this one does not
    edit_spec 's/^( +)heat_control == Isolette_Data_Model::On_Off\.Off;/\1heat_control == Isolette_Data_Model::On_Off.Onn;/' \
      "REQ_MHS_1 initialize guarantee flipped (Off -> Onn)"
  fi
  GOLDEN_DRIFT_FILE="$REPO/golden$DRIFT_FILE"
  PROPOSED="$LOG_DIR/$(basename "$DRIFT_FILE").proposed"
  cp "$DRIFT_FILE" "$PROPOSED"
  run_driver
  expect "user intervention required" "the drifted episode must escalate"
  expect "failing components (isolette_sysmlv2_rust_l2)" \
    "the l2 refinement must name the changed contract slices"
  echo
  echo "${BOLD}The episode escalated (and quarantined the live tree back to golden).${RESET}"
  echo "Your ruling on the proposed spec change:"
  show_diff "$GOLDEN_DRIFT_FILE" "$PROPOSED"
  if [ -n "$AUTO" ]; then
    answer="$AUTO"; echo "(--auto) ruling: $answer"
  else
    answer=""
    if has_tty; then
      prompt "${BOLD}[b]less as the new baseline / [r]evert to golden: ${RESET}"
      read -r answer </dev/tty
    fi
  fi
  case "$answer" in
    b|bless)
      echo
      echo "re-applying the change and RE-BLESSING (the sanctioning act) ..."
      echo "Blessing sanctions the SPEC — whether the generated realization"
      echo "still proves is the pipeline's question, not the blessing's."
      cp "$PROPOSED" "$DRIFT_FILE"
      run_driver --provision --bless-props
      expect "5 blessed model files" "the props class must be re-signed"
      BLESSED_DURING_DEMO=1
      echo
      echo "fresh episode against the NEW baseline:"
      run_driver --verify
      expect "isolette_sysmlv2_rust:files: all attested components intact" \
        "the blessed change must attest clean against the new baseline"
      expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
        "the OLD realization must still prove — the spec moved first"
      echo
      echo "${BOLD}The spec is blessed; the generated realization has not caught up${RESET}"
      echo "${BOLD}(the contracts inside the crates still render the OLD statements).${RESET}"
      echo "${BOLD}The catch-up is the sanctioned pipeline — real codegen. It NEVER${RESET}"
      echo "${BOLD}verifies: blessing is authority, and whether the implementation${RESET}"
      echo "${BOLD}proves against the blessed spec is the episode's honest measurement,${RESET}"
      echo "${BOLD}not a precondition of gold moving:${RESET}"
      cp "$MHS_APP" "$LOG_DIR/mhs_app.rs.precodegen"
      cp "$GUMBO_LIB_RS" "$LOG_DIR/gumbo_lib.rs.precodegen"
      run_driver --promote
      expect "targets regenerated" "promote must move gold — no verification gate"
      if [ "$drift" != "breaking" ]; then
        expect "all attested components intact" \
          "the promoted baseline attests clean — the realization meets the \
blessed change"
        if [ "$drift" = "range" ]; then
          offer_diff "$LOG_DIR/gumbo_lib.rs.precodegen" "$GUMBO_LIB_RS" \
            "the regenerated shared-library constant (guarantee and assume moved together)"
        else
          offer_diff "$LOG_DIR/mhs_app.rs.precodegen" "$MHS_APP" \
            "the machine-regenerated contract (what codegen re-spliced into the developer-owned file)"
        fi
        echo
        echo "${BOLD}the checklist against the promoted baseline:${RESET}"
        run_driver --ready --status
        expect "readiness: PASS" "the promoted baseline must verify"
        expect_absent "✗" "no crate may stay refuted after the catch-up"
        expect_absent "?" "no crate may stay unjudged after the catch-up"
      else
        # promotion moved gold WITHOUT verifying; the episode that follows
        # measures the new baseline and reports the Verus tier RED
        expect "confirmation failed (isolette_sysmlv2_rust_verus)" \
          "the episode must report the Verus tier RED against the new baseline"
        expect "thermostat_rt_mhs_mhs_verus_targ" \
          "the RED tier must name the crate that cannot honor the spec"
        echo
        echo "${BOLD}Gold MOVED — the spec is blessed and the baseline is the new${RESET}"
        echo "${BOLD}spec — but the implementation cannot honor it: it initializes${RESET}"
        echo "${BOLD}the heat control Off where the flipped REQ_MHS_1 now demands On,${RESET}"
        echo "${BOLD}so the Verus tier attests RED (both the mhs crate and the${RESET}"
        echo "${BOLD}system proof that composes it). This is the HONEST state: you${RESET}"
        echo "${BOLD}blessed a spec your implementation does not yet meet. The exits${RESET}"
        echo "${BOLD}are an implementation fix (the ladder scene 2 demonstrated) or${RESET}"
        echo "${BOLD}the administrator walking the sanction back. The demo walks it${RESET}"
        echo "${BOLD}back — restoring the tree and re-blessing the original spec:${RESET}"
        ( cd "$REPO" && git checkout -- targets/isolette-microkit )
        run_driver --provision --bless-props
        BLESSED_DURING_DEMO=0
        run_driver --verify
        expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
          "the walked-back baseline must attest clean"
      fi
      ;;
    *)
      echo
      echo "reverted: the escalation already restored the live tree to golden;"
      echo "confirming with a fresh episode:"
      run_driver
      expect "all attested components intact" "the reverted tree must attest clean"
      ;;
  esac
  pause
fi
if in_scenes 4; then
  banner "SCENE 4 — restore, at two grains" \
    "Beat 1, --immutable-model: the ruling for automated pipelines —" \
    "measured files must never drift; the failed hash appraisal IS the" \
    "repair order, whole-file restore + in-session re-attest, no" \
    "interaction. Beat 2, --repair-granularity slice: the repair unit" \
    "is the MEASUREMENT unit — only the violated contract slice is" \
    "spliced back (located by CONTENT ALIGNMENT, insertion-robust)," \
    "and benign drift elsewhere in the file survives."
  echo "${BOLD}beat 1 — a GUMBO guarantee drifts in Regulate.sysml${RESET}"
  # two alternates: the pristine spec carries 'x <= y'; after scene 3's
  # benign bless the OPERATIVE spec carries the restated 'y >= x' — the
  # drift must land either way (operative state, never demo-start state)
  edit_spec 's/lower_desired_temp\.degrees <= upper_desired_temp\.degrees;/lower_desired_temp.degrees < upper_desired_temp.degrees;/; s/upper_desired_temp\.degrees >= lower_desired_temp\.degrees;/upper_desired_temp.degrees > lower_desired_temp.degrees;/' \
    "lower_is_lower_temp guarantee tightened (a strictness change)"
  echo
  echo "AM detection names the changed contract (position-independently,"
  echo "in the model language):"
  run_driver --check
  expect "model contracts changed" "detection must name the changed contract"
  echo
  run_driver --immutable-model
  expect "repaired and re-attested clean in-session" \
    "immutable-model must restore and re-attest in one session"
  if cmp -s "$GOLDEN_REGULATE" "$REGULATE"; then
    echo "${BOLD}live spec is byte-identical to golden again.${RESET}"
  else
    echo "DEMO ABORT: live spec still differs from golden" >&2; exit 1
  fi
  pause

  echo
  echo "${BOLD}beat 2 — slice granularity: the repair unit is the measurement unit${RESET}"
  echo "A benign note lands OUTSIDE every measured slice of a"
  echo "contract-bearing Rust file, and one blessed contract slice in"
  echo "the SAME file is corrupted. Whole-file restore would clobber"
  echo "the note; slice restore splices ONLY the violated block. The"
  echo "proof it worked is in the summary: episode 2's files entry"
  echo "passes VIA the l2 contracts refinement — the file hash still"
  echo "failed (the note survived!), and every slice was intact."
  run_driver --tamper-verus --tamper-note --repair-granularity slice
  expect "repair:slice: restored 1 block(s) from golden" \
    "the slice rung must restore exactly the violated slice"
  expect "isolette_sysmlv2_rust:files: all attested components intact (isolette_sysmlv2_rust_l2 passed)" \
    "the files entry must pass VIA the contracts refinement — the surviving note is why"
  expect "repaired and re-attested clean in-session" \
    "the spliced slice must re-attest in one session"
  echo
  echo "(the driver's exit self-clean then restored the note too — demo policy)"
  pause
fi
if in_scenes 5; then
  banner "SCENE 5 — verification failure -> repair (selectable strategy)" \
    "The implementation drifts in its DEVELOPER-OWNED region — the" \
    "INSPECTA exemplar's own seeded bug: in NORMAL mode below the" \
    "lower bound, command Off instead of On. Every contract slice is" \
    "intact, so integrity attests clean at finer granularity; the" \
    "ALWAYS-RUN verus tier refutes the crate — the generated contracts" \
    "are genuinely false of the drifted behavior. Repair by strategy:" \
    "restore (failing crate's files from golden) or pause (YOU repair," \
    "fresh measurement judges). Standing never comes from the repair's" \
    "own claim."
  if [ -z "$STRATEGY" ]; then
    if [ "$FAST" = 1 ]; then
      STRATEGY="restore"
    else
      echo "Choose the repair strategy:"
      echo "  [1] restore — the failing crate's hashed files from golden"
      echo "                (default; automatic, keyless)"
      echo "  [2] pause   — out-of-band: the episode blocks while YOU repair"
      pick=""
      if has_tty; then
        prompt "${BOLD}strategy [1/2]: ${RESET}"
        read -r pick </dev/tty
      fi
      case "$pick" in
        2|pause) STRATEGY="pause" ;;
        *) STRATEGY="restore" ;;
      esac
    fi
  fi
  echo "repair strategy: $STRATEGY"
  echo
  # scene-ENTRY capture: the status-beat restore must return to the
  # OPERATIVE file (a scene-3 benign promote re-spliced its requires
  # clause), never the demo-start pristine
  SCENE5_MHS="$LOG_DIR/mhs_app.rs.scene5"
  cp "$MHS_APP" "$SCENE5_MHS"

  echo "${BOLD}first, the checklist over the BROKEN tree — the failing crate${RESET}"
  echo "${BOLD}refuted with its diagnostic, every other crate judged from its${RESET}"
  echo "${BOLD}own cargo-verus component:${RESET}"
  run_driver --tamper-impl --status
  expect "✗" "the checklist must display the failing crate"
  expect "thermostat_rt_mhs_mhs" "the failing crate must be named"
  offer_diff "$SCENE5_MHS" "$MHS_APP" \
    "the seeded behavior bug (pristine vs drifted developer region)"
  cp "$SCENE5_MHS" "$MHS_APP"
  pause
  echo
  case "$STRATEGY" in
    restore)
      echo "${BOLD}the repair arc — drift, attribution, crate restore, fresh${RESET}"
      echo "${BOLD}measurement, all in one session:${RESET}"
      run_driver --tamper-impl --verify --restore-crates
      expect "restored 1 file(s) from golden" \
        "the crate rung must restore the failing crate's files"
      expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
        "the verification entry must end repaired and clean"
      expect "repaired and re-attested clean in-session" \
        "the repair must end in good standing"
      ;;
    pause)
      echo "${BOLD}The episode BLOCKS on the out-of-band pause rung: no engine, no${RESET}"
      echo "${BOLD}restore — the repair is yours, and only fresh measurement can${RESET}"
      echo "${BOLD}re-establish standing.${RESET}"
      if [ "$FAST" = 1 ]; then
        echo "(unattended: answering [s]kip — the decline path, escalation follows)"
        printf 's\n' | run_driver --tamper-impl --verify --pause
        expect "user intervention required" \
          "declining the operator gate must fall through to escalation"
      else
        echo
        echo "when the work order appears, repair in ANOTHER terminal:"
        echo "    cd $REPO && git checkout -- ${MHS_APP#"$REPO"/}"
        echo "then answer [r]e-attest. (Answer [s]kip to see the escalation path.)"
        run_driver --tamper-impl --verify --pause
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
if in_scenes 6; then
  banner "SCENE 6 — baseline tamper: the repair that must refuse" \
    "Now the TRUST STATE itself is attacked — the live tree stays" \
    "pristine throughout. Readiness re-appraises the signed" \
    "provisioning record and refuses to START attestation. No" \
    "knowledge source can repair a baseline — the ready entry's" \
    "failure chain is empty BY DESIGN, provisioning is unreachable" \
    "from failure handling — so the only exit is the administrator's" \
    "out-of-band re-bless."
  # scene-ENTRY captures — every beat must restore to the OPERATIVE
  # state (a scene-3 bless changed the blessing for the rest of the
  # run): the spec the CURRENT blessing covers, and the CURRENT signed
  # bundle + installed goldens (the demo-start pristines would revert
  # the blessing under a promoted baseline)
  SCENE6_SPEC="$LOG_DIR/Regulate.sysml.scene6"
  SCENE6_BUNDLE="$LOG_DIR/props_bundle.scene6"
  SCENE6_ARGS="$LOG_DIR/props_asp_args.scene6"
  cp "$REGULATE" "$SCENE6_SPEC"
  cp "$PROPS_BUNDLE" "$SCENE6_BUNDLE"
  cp "$PROPS_ARGS" "$SCENE6_ARGS"

  echo "${BOLD}beat 1 — tamper the signed record: flip ONE byte of stored evidence${RESET}"
  "$PY" - "$PROPS_BUNDLE" <<'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
raw = d[0][0]["RawEv"]
i = max(range(1, len(raw)), key=lambda k: len(raw[k]))  # largest payload; never slot 0, the signature
s = raw[i]
raw[i] = s[:10] + ("A" if s[10] != "A" else "B") + s[11:]
json.dump(d, open(path, "w"))
print(f"flipped one character of RawEv slot {i} in the props bundle")
PYEOF
  run_driver
  expect "bundle signature verification FAILED" \
    "a tampered bundle byte must break the signature"
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  offer_diff_json "$SCENE6_BUNDLE" "$PROPS_BUNDLE" \
    "one flipped byte of signed evidence (pristine vs tampered bundle)"
  cp "$SCENE6_BUNDLE" "$PROPS_BUNDLE"
  echo
  echo "${BOLD}the record itself was not authentic — restored; now the other side:${RESET}"
  pause

  echo "${BOLD}beat 2 — tamper the installation: hand-edit one installed golden${RESET}"
  "$PY" - "$PROPS_ARGS" <<'PYEOF'
import json, sys
path = sys.argv[1]
d = json.load(open(path))
t = next(a for a in d["readfile"].values()
         if a["filepath"].endswith("Regulate.sysml"))
g = t["golden_b64"]
t["golden_b64"] = g[:10] + ("A" if g[10] != "A" else "B") + g[11:]
json.dump(d, open(path, "w"), indent=2)
print("flipped one character of the INSTALLED golden for Regulate.sysml")
PYEOF
  run_driver
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  expect_absent "signature verification FAILED" \
    "the bundle is authentic in this beat — only the anchor may refute"
  offer_diff_json "$SCENE6_ARGS" "$PROPS_ARGS" \
    "one hand-edited installed golden (pristine vs tampered asp_args)"
  cp "$SCENE6_ARGS" "$PROPS_ARGS"
  echo
  echo "${BOLD}restored — now the smarter adversary:${RESET}"
  pause

  echo "${BOLD}beat 3 — laundering: tamper the spec, re-provision it into the goldens${RESET}"
  echo "The live spec is edited, then an ORDINARY re-provision re-derives"
  echo "and RE-SIGNS the measurement baselines from the tampered tree."
  echo "The laundered bundles are fully self-consistent — signatures"
  echo "valid, anchors matching: every check from beats 1 and 2 passes."
  echo "But the BLESSING cannot be laundered: ordinary provisioning"
  echo "refuses to touch the props class, and readiness re-derives every"
  echo "hash and slice golden from the blessed SIGNED bytes:"
  LAUNDERED_DURING_DEMO=1
  # same two alternates as scene 4: the edit must land on the OPERATIVE
  # spec whether or not scene 3 blessed the restatement
  edit_spec 's/lower_desired_temp\.degrees <= upper_desired_temp\.degrees;/lower_desired_temp.degrees < upper_desired_temp.degrees;/; s/upper_desired_temp\.degrees >= lower_desired_temp\.degrees;/upper_desired_temp.degrees > lower_desired_temp.degrees;/' \
    "lower_is_lower_temp guarantee tightened (the laundered change)"
  run_driver --provision
  expect "goldens provisioned" "the laundering pass must provision"
  run_driver
  expect "not derivable from blessed content" \
    "the derivability anchor must refute the laundered goldens"
  expect "attestation never started" \
    "a refused baseline must stop attestation before it starts"
  expect_absent "signature verification FAILED" \
    "the laundered bundles are self-consistent — only lineage refutes"
  offer_diff "$SCENE6_SPEC" "$REGULATE" \
    "what the administrator signed vs the laundered live spec"
  echo
  echo "restoring the spec and re-provisioning derivable goldens:"
  cp "$SCENE6_SPEC" "$REGULATE"
  run_driver --provision
  LAUNDERED_DURING_DEMO=0
  echo
  echo "${BOLD}One gate, three attributed refusals: record integrity (signature),${RESET}"
  echo "${BOLD}installation consistency (anchor), semantic lineage (derivability)${RESET}"
  echo "${BOLD}— the blessing is the root that laundering cannot reach. The only${RESET}"
  echo "${BOLD}sanctioned exit is the administrator's re-bless. Confirming:${RESET}"
  run_driver --ready
  expect "readiness: PASS" "the restored baseline must verify again"
  pause
fi
if in_scenes 7; then
  banner "SCENE 7 — toolchain tamper: measure-then-use catches the tool" \
    "The cargo-verus WRAPPER is edited — functionality preserved (a" \
    "comment line), so every verification still runs and looks fine." \
    "The verus term hashes the toolchain IN THE SAME TERM, before" \
    "using it: the tool hash refutes, and every proof cell poisons to" \
    "'?' fail-closed — whether the change was benign is precisely what" \
    "an unblessed tool cannot be trusted to answer. Readiness still" \
    "PASSES: the stored record is coherent; it is the LIVE tool that" \
    "drifted. Hash-only artifacts are unrepairable from goldens by" \
    "design — the repair is out-of-band, judged by fresh measurement."
  printf '# drifted: innocuous-looking edit\n' >> "$VERUS_WRAPPER"
  echo "appended one comment line to $VERUS_WRAPPER"
  echo
  echo "${BOLD}the proof checklist under an unblessed tool — everything poisons:${RESET}"
  run_driver --ready --status
  expect "readiness: PASS" \
    "readiness must still pass — the stored record is coherent"
  expect "toolchain measurement failed" \
    "the tool-hash failure must poison the checklist"
  expect "?" "poisoned cells must read unknown, never presumed proved"
  expect_absent "✗" "no crate may be REFUTED by a tool drift — only unjudged"
  offer_diff "$WRAPPER_PRISTINE" "$VERUS_WRAPPER" \
    "the functionality-preserving wrapper edit (one comment line)"
  pause
  echo
  if [ "$FAST" = 1 ]; then
    echo "(unattended: answering [s]kip — the decline path, escalation follows)"
    printf 's\n' | run_driver --verify --pause
    expect "user intervention required" \
      "declining the operator gate must fall through to escalation"
    cp "$WRAPPER_PRISTINE" "$VERUS_WRAPPER"
    echo
    echo "${BOLD}wrapper restored out-of-band; fresh measurement re-establishes standing:${RESET}"
    run_driver --verify
    expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
      "the restored toolchain must attest clean"
  else
    echo "${BOLD}the episode blocks on the pause rung. Repair in ANOTHER terminal:${RESET}"
    echo "    cp $WRAPPER_PRISTINE $VERUS_WRAPPER"
    echo "  (or: ./examples/demo_isolette.sh --restore-tools)"
    echo "then answer [r]e-attest. (A claim WITHOUT the repair just buys"
    echo "another failing measurement — try it.)"
    echo "if you get stuck or abort mid-scene, the same --restore-tools flag"
    echo "recovers the toolchain afterwards."
    run_driver --verify --pause
    if saw "repaired and re-attested clean in-session"; then
      echo "${BOLD}your repair stood — judged by measurement, not by your word.${RESET}"
    else
      expect "user intervention required" "skip must fall through to escalation"
      cp "$WRAPPER_PRISTINE" "$VERUS_WRAPPER"
      echo "${BOLD}declined — escalated; wrapper restored by the demo.${RESET}"
    fi
  fi
  pause
fi
if in_scenes 8; then
  banner "SCENE 8 — report tamper: the rendering is anchored to the model" \
    "The attestation report is the AUTHORITY: every protocol dir is" \
    "derived from it, so measurement targets bind to contracts only" \
    "through the report's structure — and the report itself is hashed" \
    "measure-then-use as its own always-run entry. Two attacks, one" \
    "anchor. The repair is the REGENERATION species — neither restore" \
    "nor synthesis: the report is a rendering of the model through the" \
    "measured codegen toolchain, so the rung re-emits it (tool gate" \
    "first) and the restarted episode re-attests."
  REPORT_PRISTINE="$LOG_DIR/report.pristine.json"
  cp "$REPORT" "$REPORT_PRISTINE"

  echo "${BOLD}beat 1 — deletion: one slice quietly removed from the authority${RESET}"
  echo "A re-derived protocol would measure one slice FEWER than the"
  echo "administrator intended — nothing else in the report looks wrong."
  echo "First, see how innocent the tamper looks:"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
ex.tamper_report(ex.FRONTENDS['sysml'], {})" )
  offer_diff_json "$REPORT_PRISTINE" "$REPORT" \
    "the deleted report slice (canonical vs tampered rendering)"
  cp "$REPORT_PRISTINE" "$REPORT"
  echo
  echo "The byte anchor refutes, and the regeneration rung re-emits the"
  echo "report from the model through the MEASURED toolchain:"
  run_driver --tamper-report --verify --regen-report
  expect "Tampered report: deleted a" "the deletion tamper must apply"
  expect "regenerated the attestation report from the model" \
    "the regeneration rung must re-emit the report via codegen"
  expect "isolette_sysmlv2_rust:report: all attested components intact" \
    "the regenerated report must re-attest clean"
  expect "repaired and re-attested clean in-session" \
    "the regenerated rendering must re-attest in one session"
  pause

  echo
  echo "${BOLD}beat 2 — substitution: the attack the byte anchor exists for${RESET}"
  echo "One slice's span is swapped for a DIFFERENT contract's span in"
  echo "the same file: the slice count stays right, the structure stays"
  echo "plausible, and a re-derived protocol would measure the WRONG"
  echo "lines while every count-based check reads clean. First, see how"
  echo "innocent the tamper looks:"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
ex.tamper_report_subst(ex.FRONTENDS['sysml'], {})" )
  offer_diff_json "$REPORT_PRISTINE" "$REPORT" \
    "the substituted slice span (canonical vs tampered rendering)"
  cp "$REPORT_PRISTINE" "$REPORT"
  echo
  echo "Only the rendering's hash refutes:"
  run_driver --tamper-report-subst --verify --regen-report
  expect "slice span substituted with" "the substitution tamper must apply"
  expect "regenerated the attestation report from the model" \
    "the regeneration rung must re-emit the report via codegen"
  expect "isolette_sysmlv2_rust:report: all attested components intact" \
    "the regenerated report must re-attest clean"
  pause
fi

if in_scenes 9; then
  banner "SCENE 9 — proof cheat: verification success is not proof" \
    "cargo-verus says 'verified, 0 errors' — but HOW? Two beats, two" \
    "escapes that pass every OUTCOME-based tier because they change no" \
    "proof outcome. Beat 1 — ADMIT: assume(false) in a bridge file." \
    "Beat 2 — SMUGGLE: an external_body broadcast axiom in the shared" \
    "GUMBO_Library — verifies clean, inert until 'broadcast use', so" \
    "even the verus tier (errors==0) stays green. Both sites are now" \
    "byte-anchored by the GENSRC tier (generated do-not-edit sources)," \
    "so the bytes refuse too — and the ladder's diagnosis rung" \
    "correlates the two refusals: bytes say SOMETHING changed, the" \
    "construct scan says WHAT KIND — a proof ESCAPE appeared. The" \
    "cheat scan is not made redundant by byte coverage: at the promote" \
    "boundary gold legitimately MOVES, byte-blessing would bless" \
    "whatever codegen emitted, and only the blessed escape counts" \
    "stand guard there. No repair rung: the refusal escalates."
  echo "${BOLD}beat 1 — admit: a hollow proof every outcome-tier passes${RESET}"
  MHS_API_PRISTINE="$LOG_DIR/mhs_api.pristine.rs"
  cp "$MHS_API" "$MHS_API_PRISTINE"
  echo "First, see how innocent the cheat looks:"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
ex.tamper_cheat(ex.FRONTENDS['sysml'], {})" )
  offer_diff "$MHS_API_PRISTINE" "$MHS_API" \
    "the admitted contract (pristine vs cheating prover)"
  cp "$MHS_API_PRISTINE" "$MHS_API"
  echo
  echo "Now the full episode over the cheating tree — watch which tier"
  echo "refuses (the tampered crate recompiles, so the verus beat is"
  echo "slower than usual):"
  note_slow
  run_driver --tamper-cheat --verify
  expect "Admitted a verified contract" "the cheat tamper must apply"
  expect "isolette_sysmlv2_rust:files: all attested components intact" \
    "the files tier must stay green (the cheat site is not report-named)"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "cargo-verus must still report success over the admitted proof"
  expect "isolette_sysmlv2_rust:cheats: integrity violation" \
    "the cheat tier must refuse"
  expect "thermostat_rt_mhs_mhs_cheat_targ" \
    "the refusal must attribute the cheating crate"
  expect "isolette_sysmlv2_rust:gensrc: integrity violation" \
    "the gensrc byte anchor must refuse too (the site is covered now)"
  expect "hash drift: src/bridge/thermostat_rt_mhs_mhs_api.rs" \
    "the batched appraiser must name the admitted file"
  expect "a proof ESCAPE appeared" \
    "the diagnosis rung must correlate bytes-drifted with the cheat refusal"
  expect "Restored thermostat_rt_mhs_mhs_api.rs" \
    "the driver must restore the tamper site"
  pause

  echo
  echo "${BOLD}beat 2 — smuggle: an escape every outcome-tier passes too${RESET}"
  echo "Beat 1's assume hid in the crate it poisons; this one hides in a"
  echo "DIFFERENT crate. A smuggled axiom — an external_body broadcast"
  echo "proof fn with 'ensures false' — planted in the SHARED"
  echo "GUMBO_Library verifies clean on its own (the body is trusted),"
  echo "and would inject 'false' into every importer's proof context the"
  echo "moment a 'broadcast use' pulls it in. Until then it is inert, so"
  echo "it changes NO proof outcome: files, contracts, the verus tier"
  echo "(errors==0), the sysproof hash, and the report all stay green."
  echo "Two detectors see it: the gensrc byte anchor (the foundation"
  echo "crate is covered now) says the bytes moved, and the cheat scan —"
  echo "counting escape CONSTRUCTS, not proof outcomes — says WHAT"
  echo "arrived, at the staging point, before any proof consumes it."
  echo "See how ordinary it looks:"
  GUMBO_PRISTINE="$LOG_DIR/gumbo.pristine.rs"
  GUMBO_LIB_SRC="$REPO/targets/isolette-microkit/hamr/microkit/crates/GUMBO_Library/src/lib.rs"
  cp "$GUMBO_LIB_SRC" "$GUMBO_PRISTINE"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
ex.tamper_broadcast(ex.FRONTENDS['sysml'], {})" )
  offer_diff "$GUMBO_PRISTINE" "$GUMBO_LIB_SRC" \
    "the smuggled axiom (pristine vs poisoned foundation crate)"
  cp "$GUMBO_PRISTINE" "$GUMBO_LIB_SRC"
  echo
  echo "The full episode — every outcome-based tier is blind; the byte"
  echo "anchor and the construct scan refuse together, and the diagnosis"
  echo "rung names the drift kind:"
  note_slow
  run_driver --tamper-broadcast --verify
  expect "Planted a smuggled axiom in GUMBO_Library" \
    "the broadcast tamper must apply"
  expect "isolette_sysmlv2_rust:files: all attested components intact" \
    "the files tier must stay green (GUMBO_Library is report-invisible)"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the verus tier must stay green (errors==0 — the axiom is inert, no \
proof-outcome change)"
  expect "isolette_sysmlv2_rust:proofsrc: all attested components intact" \
    "the sysproof hash must stay green (the proof crate is untouched)"
  expect "isolette_sysmlv2_rust:report: all attested components intact" \
    "the report tier must stay green"
  expect "isolette_sysmlv2_rust:cheats: integrity violation" \
    "the cheat scan must refuse"
  expect "GUMBO_Library_cheat_targ" \
    "the cheat scan must name the foundation crate"
  expect "isolette_sysmlv2_rust:gensrc: integrity violation" \
    "the gensrc byte anchor must refuse too"
  expect "hash drift: src/lib.rs" \
    "the batched appraiser must name the poisoned file"
  expect "a proof ESCAPE appeared" \
    "the diagnosis rung must correlate the byte drift with the cheat refusal"
  expect "Restored lib.rs" "the driver must restore the foundation crate"
  pause
fi

if in_scenes 10; then
  banner "SCENE 10 — the hollow system proof: verification vs bytes" \
    "sys_nominal_proof is the SYSTEM-level compositional proof (~1862" \
    "obligations, one empty-bodied VC each, discharged by Verus)." \
    "Two attacks the cheat scan can't see (no escape construct) that" \
    "the Verus tier ALSO can't see (it judges correctness — does it" \
    "verify? — not surface size). Beat 1: SHRINK — drop a proof" \
    "module; the smaller crate still verifies (0 errors). Beat 2:" \
    "SWAP — drop a real VC and add a trivial one. Both leave every" \
    "verification green; ONLY the whole-file sysproof hash refuses." \
    "Bytes anchor what a proof outcome cannot."
  note_slow
  echo "${BOLD}beat 1 — shrink: a dropped proof module${RESET}"
  echo "Commenting out a proof module leaves the crate still VERIFYING"
  echo "(the remaining obligations discharge, errors==0), so the Verus"
  echo "tier — which judges correctness, not surface size — stays green."
  echo "The shrink carries no verification signal; only the bytes changed,"
  echo "so the whole-file sysproof hash is what refuses:"
  run_driver --tamper-proof-count --verify
  expect "Shrank the proof surface" "the count tamper must apply"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the Verus tier stays green — a smaller proof still verifies (errors==0)"
  expect "isolette_sysmlv2_rust:proofsrc: integrity violation" \
    "the whole-file sysproof hash must refuse (lib.rs changed)"
  expect "hash drift: src/lib.rs" \
    "the batched appraiser must name the dropped-module file"
  pause
  echo
  echo "${BOLD}beat 2 — swap: drop-and-replace, still verifying${RESET}"
  echo "The swapped crate still verifies (a trivial VC proves as readily"
  echo "as the real one), so the Verus tier — judging correctness — stays"
  echo "green, and the count is beside the point:"
  run_driver --tamper-proof-swap --verify
  expect "verified count held at 1862" "the swap tamper must apply"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the verus tier must PASS (it still verifies — correctness, not surface)"
  expect "isolette_sysmlv2_rust:proofsrc: integrity violation" \
    "only the sysproof whole-file hash must refuse"
  expect "hash drift: src/normal_display_temp/vc_sequential.rs" \
    "the batched appraiser must attribute the swapped VC file by name"
  expect "Restored vc_sequential.rs" "the driver must restore the site"
  pause
fi

if in_scenes 11; then
  banner "SCENE 11 — the stale dependency cache: a verdict that never looked" \
    "The verus tier's 8 primary crates genuinely RE-VERIFY every run —" \
    "but the foundation crates (data, GUMBO_Library) are consumed as" \
    "cargo DEPENDENCIES, and cargo's dep freshness is mtime-gated. A" \
    "spec predicate in GUMBO_Library is flipped SEMANTICALLY (no" \
    "construct-count change) with the mtime preserved nanosecond-exact:" \
    "the cheat scan counts no new escape and the warm cache serves the" \
    "STALE pre-tamper artifact. The gensrc byte anchor refuses — bytes" \
    "always tell — and that is what exposes the Verus tier's verdict:" \
    "the TIERS DISAGREE. Bytes say the foundation changed; the Verus" \
    "tier sits green over a system proof that is FALSE of the live" \
    "tree, because 'verification succeeded' is a verdict about bytes" \
    "the verifier last LOOKED at. Beat 2 adds the dependency-freshness" \
    "guard: content-hash the dep sources, bump mtimes on drift, and the" \
    "forced re-verify lets sys_nominal_proof honestly refute (8 VCs) —" \
    "the verdicts agree again. No repair rung: the refusal escalates." \
    "The guard is DEMO-SCOPED — outside this scene the verus tier's" \
    "EVIDENCE trusts cargo's dep cache; the attested always-on guard is" \
    "postponed by design."
  GUMBO_LIB_SRC="$REPO/targets/isolette-microkit/hamr/microkit/crates/GUMBO_Library/src/lib.rs"
  SIDECAR="$REPO/.dep_freshness.json"
  rm -f "$SIDECAR"

  echo "${BOLD}beat 0 — the warm, coherent cache the attack needs${RESET}"
  echo "One gated-clean checklist run: every crate re-verifies green and"
  echo "every dependency cache is built from the CURRENT bytes. Then the"
  echo "guard's freshness record is seeded over that known-coherent state"
  echo "(trust-on-first-use):"
  note_slow
  run_driver --ready --status
  expect "readiness: PASS" "the checklist run must verify the baselines"
  expect "✓" "every crate must check off before the staleness arc"
  expect_absent "✗" "a refuted crate here means the demo started dirty"
  expect_absent "?" "an unjudged crate here means the demo started dirty"
  run_driver --fresh-deps
  expect "fresh-deps: seeded the freshness record" \
    "the guard must seed its content record over the coherent cache"
  pause

  echo
  echo "${BOLD}beat 1 — the horror: the tiers disagree${RESET}"
  echo "The flip inverts what 'a valid temperature reading' MEANS for"
  echo "every consumer — freshly verified, 8 system-proof VCs refute it."
  echo "See how innocent it looks (and note: the mtime will not change):"
  SCENE11_GUMBO="$LOG_DIR/gumbo.scene11.rs"
  cp "$GUMBO_LIB_SRC" "$SCENE11_GUMBO"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
from pathlib import Path
Path(sys.argv[1]).write_text(ex.stale_dep_text(ex.GUMBO_LIB.read_text()))
" "$LOG_DIR/gumbo.scene11.tampered.rs" )
  offer_diff "$SCENE11_GUMBO" "$LOG_DIR/gumbo.scene11.tampered.rs" \
    "the semantic flip (pristine vs tampered foundation dependency)"
  echo
  echo "The full episode over the tampered tree — the primary crates all"
  echo "re-verify, and every one of them consumes the STALE cached"
  echo "dependency; watch the byte anchor and the Verus verdict part ways:"
  note_slow
  run_driver --tamper-stale-dep --verify
  expect "Tampered a foundation dependency" "the stale-dep tamper must apply"
  expect "isolette_sysmlv2_rust:files: all attested components intact" \
    "the files tier must stay green (GUMBO_Library is report-invisible)"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the verus tier must stay green — the STALE dep verdict (this gate is \
also the regression canary for the pinned toolchain's cache behavior)"
  expect "isolette_sysmlv2_rust:cheats: all attested components intact" \
    "the cheat scan must stay silent (a semantic flip adds no construct)"
  expect "isolette_sysmlv2_rust:proofsrc: all attested components intact" \
    "the sysproof hash must stay green (the proof crate is untouched)"
  expect "isolette_sysmlv2_rust:report: all attested components intact" \
    "the report tier must stay green"
  expect "isolette_sysmlv2_rust:gensrc: integrity violation" \
    "the gensrc byte anchor must refuse — bytes always tell"
  expect "hash drift: src/lib.rs" \
    "the batched appraiser must name the flipped file"
  expect "cheat counts CLEAN" \
    "the diagnosis rung must classify the drift as a semantic edit"
  expect "Restored lib.rs" "the driver must restore the foundation crate"
  echo
  echo "${BOLD}The tiers DISAGREE — the gensrc anchor refuses while the Verus${RESET}"
  echo "${BOLD}tier sits green over a system proof that is FALSE of the live${RESET}"
  echo "${BOLD}bytes. The verus tier re-ran, honestly, over its 8 primary${RESET}"
  echo "${BOLD}crates; the lie lives in the dependency artifact cargo declined${RESET}"
  echo "${BOLD}to rebuild because the mtime said nothing changed. A refusing${RESET}"
  echo "${BOLD}byte tier saves the SYSTEM's honesty — but the green Verus cell${RESET}"
  echo "${BOLD}is still misleading EVIDENCE, and that is what beat 2 repairs:${RESET}"
  pause

  echo
  echo "${BOLD}beat 2 — the guard: freshness re-keyed on content, not mtime${RESET}"
  echo "Same tamper, same episode — plus --fresh-deps: the guard digests"
  echo "the dependency sources against its seeded record, attributes the"
  echo "drift, and bumps mtimes so cargo-verus must re-verify the"
  echo "dependency from the live bytes. Now the system proof refutes:"
  note_slow
  run_driver --tamper-stale-dep --fresh-deps --verify
  expect "Tampered a foundation dependency" "the stale-dep tamper must apply"
  expect "fresh-deps: content drift in GUMBO_Library" \
    "the guard must detect and attribute the dependency drift"
  expect "isolette_sysmlv2_rust:proofs: integrity violation" \
    "the verus tier must refuse once the dep is freshly verified"
  expect "sys_nominal_proof_verus_targ" \
    "the refusal must attribute the consumer that cannot prove"
  expect "isolette_sysmlv2_rust:gensrc: integrity violation" \
    "the byte anchor still refuses — now the verdicts AGREE"
  expect "Restored lib.rs" "the driver must restore the foundation crate"
  rm -f "$SIDECAR"
  echo
  echo "${BOLD}The refusal is the honest state — and it names the CONSUMER${RESET}"
  echo "${BOLD}(sys_nominal_proof), not the tampered dependency: the guard${RESET}"
  echo "${BOLD}restores freshness, it does not attribute. No repair rung on${RESET}"
  echo "${BOLD}purpose: a poisoned foundation escalates to the administrator.${RESET}"
  echo "${BOLD}The restore is mtime-aware both ways: beat 1's (no rebuild${RESET}"
  echo "${BOLD}happened) put bytes AND mtime back, leaving the caches${RESET}"
  echo "${BOLD}coherent for free; this one carries a FRESH mtime, because the${RESET}"
  echo "${BOLD}guard's rebuilds consumed the tampered bytes and an mtime-gated${RESET}"
  echo "${BOLD}cache must be TOLD the restore happened. The checklist proves${RESET}"
  echo "${BOLD}the tree green from live re-verification:${RESET}"
  note_slow
  run_driver --ready --status
  expect "readiness: PASS" "the restored tree must verify again"
  expect_absent "✗" "no crate may stay refuted after the restore"
  expect_absent "?" "no crate may stay unjudged after the restore"
  pause
fi

if in_scenes 12; then
  banner "SCENE 12 — the unverified foundation: bytes under the proof tower" \
    "Every verified put flows through unsafe_put_heat_control — plain" \
    "unverified Rust behind an external_body boundary Verus never" \
    "reads. Beat 1 inverts the heat command RIGHT THERE: the proofs" \
    "all pass (they are about the ghost model; the body was ALWAYS" \
    "trusted), the cheat scan counts no new escape (the escape surface" \
    "is unchanged), no report-named file moved. Only the gensrc byte" \
    "anchor refuses — and its diagnosis rung classifies the drift:" \
    "cheat counts CLEAN, a semantic edit no construct scan can see." \
    "This drift KIND is exactly why the gensrc ladder never rescues on" \
    "a clean cheat scan. Beat 2 is the repair — scene 8's regeneration" \
    "species: these files are RENDERINGS of the model through the" \
    "codegen toolchain, so the rung re-emits them (tool gate first," \
    "real codegen) and fresh measurement judges the result in-session."
  MHS_EXTERN_SRC="$REPO/targets/isolette-microkit/hamr/microkit/crates/thermostat_rt_mhs_mhs/src/bridge/extern_c_api.rs"

  echo "${BOLD}beat 1 — invert the command under the proofs${RESET}"
  echo "See how innocent it looks (and where it sits — the unsafe FFI"
  echo "glue between the verified bridge and the platform):"
  SCENE12_EXTERN="$LOG_DIR/extern_c_api.scene12.rs"
  cp "$MHS_EXTERN_SRC" "$SCENE12_EXTERN"
  ( cd "$REPO" && "$PY" -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
import isolette_rust as ex
from pathlib import Path
Path(sys.argv[1]).write_text(
    ex.MHS_EXTERN.read_text().replace(ex.FFI_MARKER, ex.FFI_TAMPERED, 1))
" "$LOG_DIR/extern_c_api.scene12.tampered.rs" )
  offer_diff "$SCENE12_EXTERN" "$LOG_DIR/extern_c_api.scene12.tampered.rs" \
    "the inverted command in the unverified FFI glue"
  echo
  echo "The full episode — the verified tower stands; the foundation"
  echo "under it now does the opposite of what the proofs say:"
  note_slow
  run_driver --tamper-ffi --verify
  expect "Inverted the heat command" "the FFI tamper must apply"
  expect "isolette_sysmlv2_rust:files: all attested components intact" \
    "the files tier must stay green (the glue is not report-named)"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "every proof must still pass — the body was always trusted"
  expect "isolette_sysmlv2_rust:cheats: all attested components intact" \
    "the cheat scan must stay silent (no new escape construct)"
  expect "isolette_sysmlv2_rust:gensrc: integrity violation" \
    "only the gensrc byte anchor may refuse"
  expect "hash drift: src/bridge/extern_c_api.rs" \
    "the batched appraiser must name the glue file"
  expect "cheat counts CLEAN" \
    "the diagnosis rung must classify the drift as a semantic edit"
  expect "Restored extern_c_api.rs" "the driver must restore the glue"
  echo
  echo "${BOLD}A cheat-clean drift in a do-not-edit file is why the ladder${RESET}"
  echo "${BOLD}never rescues: every byte of these files IS measured semantics.${RESET}"
  pause

  echo
  echo "${BOLD}beat 2 — repair by regeneration: the rendering re-emitted${RESET}"
  echo "Same tamper — and the repair rung: tool gate (HAMR + pinned"
  echo "libraries hashed just before use) -> real SysML codegen re-emits"
  echo "the generated sources from the blessed model -> the restarted"
  echo "episode re-attests. Judged by fresh measurement, never by the"
  echo "repair's own claim (codegen beat: ~1-2 min):"
  run_driver --tamper-ffi --regen-gensrc --verify
  expect "Inverted the heat command" "the FFI tamper must apply"
  expect "regenerated the generated sources from the model" \
    "the regeneration rung must re-emit via measured codegen"
  expect "isolette_sysmlv2_rust:gensrc: all attested components intact" \
    "the regenerated sources must re-attest clean"
  expect "repaired and re-attested clean in-session" \
    "the repair must end in good standing, judged by fresh measurement"
  pause
fi

if in_scenes 13; then
  banner "SCENE 13 — implementation drift: benign, re-verified" \
    "A SEMANTICALLY EQUIVALENT rewrite of the developer-owned NORMAL-" \
    "mode guard (x > y  ->  y < x). It lives OUTSIDE every contract" \
    "marker block, so every contract slice AND every marker block stay" \
    "byte-identical — only the whole-file hash moves. The files entry" \
    "passes via the l2 refinement at finer granularity, and the" \
    "confirmation chain RE-VERIFIES the rewritten implementation: the" \
    "benign change SURVIVES, no restore. The mirror of Act II's benign" \
    "spec restatement, one artifact class down." \
    "" \
    "This is the honest 'benign drift survives' story for the" \
    "implementation class: integrity is about the blessed bytes, but a" \
    "developer-owned region has no blessed bytes to match — its" \
    "attested properties are the contracts (intact) and provability" \
    "(re-verified live)."
  SCENE13_MHS="$LOG_DIR/mhs_app.rs.scene13"
  cp "$MHS_APP" "$SCENE13_MHS"
  note_slow
  run_driver --tamper-impl-benign --verify
  expect "NORMAL-mode guard rewritten equivalently" \
    "the benign equivalent rewrite must apply"
  expect "isolette_sysmlv2_rust_l2 passed after isolette_sysmlv2_rust_l1a failed" \
    "the files entry must pass via the l2 refinement (slices intact)"
  expect "isolette_sysmlv2_rust:contracts: all attested components intact" \
    "the marker-block contract tier must stay clean (drift is outside markers)"
  expect "isolette_sysmlv2_rust:proofs: all attested components intact" \
    "the rewritten implementation must RE-VERIFY green"
  pause
fi
if in_scenes 14; then
  banner "SCENE 14 — contract drift: breaking, restored" \
    "The model is UNTOUCHED. In the developer-owned app.rs, the" \
    "generated REQ_MHS_2 ensures is WEAKENED (admit both heat states)" \
    "AND the implementation is inverted to the behavior the weakening" \
    "covers for. Run alone, cargo-verus SUCCEEDS — the pair is self-" \
    "consistent. 'Verification succeeded' cannot see this: the contract" \
    "has drifted from what the blessed model renders." \
    "" \
    "The report emits NO slice for compute_cases realizations, so the" \
    "weakened REQ_MHS_2 lands between the report's l2 slices — but the" \
    "l1b MARKER tier measures every byte of the codegen-managed" \
    "contract block. It refuses, and its repair rung splices the golden" \
    "contract back. Then the honest re-measurement: the restored TRUE" \
    "contract REFUTES the still-inverted implementation — the Verus" \
    "refusal the laundering was hiding. The scene ends there, on the" \
    "exposed contract-verification failure: restoring the contract is" \
    "what makes the hidden implementation bug measurable."
  SCENE14_MHS="$LOG_DIR/mhs_app.rs.scene14"
  cp "$MHS_APP" "$SCENE14_MHS"
  ( cd "$REPO" && "$PY" "$DRIVER" --frontend sysml --tamper-contract-launder --verify \
      >"$LOG_DIR/scene14_pre.log" 2>&1 || true )
  offer_diff "$SCENE14_MHS" "$MHS_APP" \
    "the laundering the arc is about to apply (weakened REQ_MHS_2 + inverted impl)"
  ( cd "$REPO" && git checkout -- targets/isolette-microkit 2>/dev/null || true )
  note_slow
  run_driver --tamper-contract-launder --verify --repair-markers
  expect "self-consistent (verification succeeds)" \
    "the laundering must apply (self-consistent pair)"
  expect "isolette_sysmlv2_rust:contracts" \
    "the marker tier must judge the contract block"
  expect "repair:marker-blocks: restored" \
    "the marker rung must splice the golden contract block back"
  expect "confirmation failed (isolette_sysmlv2_rust_verus)" \
    "the restored true contract must refute the inverted implementation"
  expect "thermostat_rt_mhs_mhs_verus_targ" \
    "the exposed refusal must name the crate the laundering hid"
  echo
  echo "${BOLD}The laundering slipped the report's slice coverage — the report${RESET}"
  echo "${BOLD}emits no slice for compute_cases realizations — but the l1b marker${RESET}"
  echo "${BOLD}tier measures every byte of the contract block. Restoring the true${RESET}"
  echo "${BOLD}contract makes the hidden implementation bug measurable: Verus${RESET}"
  echo "${BOLD}refuses. (Repairing the implementation is scene 2's ladder; this${RESET}"
  echo "${BOLD}scene ends on the honest exposure.)${RESET}"
  pause
fi

banner "DEMO COMPLETE" \
  "postponed, by design: episode-triggering monitor (external" \
  "scheduler), wall-clock repair timeouts, the executable artifact" \
  "class (domain_monitor, dmf, drf — named by the gensrc coverage" \
  "invariant, measured by no tier yet), blessing the report under the" \
  "props class (laundered reports refuted by lineage, not just the" \
  "live hash), a real spec-guided Rust implementation engine behind" \
  "the scene 2 stand-in, and the ALWAYS-ON attested dependency-" \
  "freshness guard (scene 11's guard is demo-scoped: outside that" \
  "scene a stale dep cache can still render the verus tier's green" \
  "cell misleading — the gensrc byte anchor keeps the SYSTEM honest," \
  "but honest evidence needs the guard)."
