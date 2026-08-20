# `examples/demo_isolette.sh` — what it exercises

An interactive walkthrough of the attestation workflow on the SysMLv2 ->
Rust isolette (the INSPECTA seL4/Microkit exemplar,
`targets/isolette-microkit`), driven end-to-end through
`isolette_rust.py --frontend sysml`. The scene outline mirrors
[demo_rocq_script_summary.md](demo_rocq_script_summary.md) on the Rocq
example; where the ecosystems differ, the scene says so and shows the
isolette's honest counterpart.

**At a glance**: ten scenes; repair species exercised: whole-file
restore, content-aligned slice splice, crate restore, sanctioned
codegen catch-up, regeneration-from-model, out-of-band pause, and the
principled refusal; three refusal properties at one gate (signature,
anchor, derivability). Keyless throughout — every repair is
deterministic or out-of-band.

**Running it**: `./examples/demo_isolette.sh` (interactive; `--help`
for flags — `--scenes`, `--drift`, `--auto`, `--repair-strategy`,
`--fast` for unattended, `--restore-tools` recovery). Warm cargo-verus
caches recommended: every Verus tier run re-verifies 8 crates (~10 s
warm, multi-minute cold); scene 3's codegen beats add ~1-2 min each.

## Setup

- Bootstrap provisioning if no blessed baseline exists.
- The readiness gate: protocol configuration checks plus verification
  of every **signed golden baseline** (l1a hashes, l2 slices, the
  blessed props model files, the verus tool hashes, the cheat tier's
  proof-escape counts) before any attestation runs.

## Scene 1 — clean baseline

- One attestation episode over every artifact class: **files** (13
  whole-file hashes: SysML packages + contract-bearing Rust),
  **contracts** (67 report slices), **verification** (cargo-verus over
  8 crates — the 7 component crates + the system proof crate — an
  ALWAYS-RUN entry whose evidence is the goldened verified COUNT, not
  just errors==0), the **cheat tier** (per-crate proof-escape counts
  over 10 crates — see scene 9), the **sysproof tier** (whole-file
  hashes of the system proof crate, batched into one
  relpath→sha256 evidence map — see scene 10), and the **report
  rendering** every protocol is derived from, with the verus toolchain
  hashed measure-then-use in the same term.
- The per-crate proof checklist, all green.

## Scene 2 — implementation tamper: the ladder repairs the right artifact

- A **pre-generated dummy bad implementation** replaces the
  developer-owned compute logic wholesale ([diff&nbsp;D1](#d1); heat
  ON in INIT and FAILED modes, both NORMAL responses inverted): it
  compiles fine, but the blessed contracts are genuinely **false** of
  it, so no contract-side repair can help.
- The ladder diagnoses before it repairs: the contracts-intact rung
  finds every contract slice of the failing crate byte-identical to
  golden — the exhaustion *is the diagnosis* that the implementation is
  the artifact at fault — and hands off to the impl rung, which
  restores the implementation (crate-scoped, from golden, standing in
  for a future spec-guided Rust engine). The restarted episode
  re-attests; the model and contract slices end untouched.

## Scene 3 — spec drift: escalate, examine, rule

- A GUMBO contract edit in `Regulate.sysml` (operator's choice:
  **benign** semantically equivalent restatement
  ([diff&nbsp;D2](#d2)), or **breaking** — REQ_MHS_1's initialize
  guarantee flipped Off -> Onn ([diff&nbsp;D3](#d3)), which codegen
  accepts but the implementation cannot honor).
- Detection and escalation with attribution: the l2 refinement names
  the changed slices; interactive ruling over the diff — **revert**, or
  **bless**: spec-first sanctioning (`--provision --bless-props`
  re-signs the props class only; no codegen).
- After a bless, model and contracts attest clean while the generated
  realization still renders the OLD statements. The catch-up is the
  **sanctioned pipeline** (`--promote`): tool gate (HAMR + pinned
  sysml-aadl-libraries hashed just before use) -> **real SysML
  codegen** (re-splices the contract marker regions inside the
  developer-owned app.rs) -> **Verus proof gate** -> gold moves ->
  props re-blessed. Benign: the regenerated contracts prove, with the
  codegen re-splice shown as a diff ([diff&nbsp;D4](#d4)). Breaking:
  the proof gate
  **refuses** before gold moves — the old baseline stays fully in
  place, and the honest exits are an implementation fix (scene 2's
  ladder) or walking the sanction back.

## Scene 4 — restore, at two grains

- **Whole-file** (`--immutable-model`): the ruling for automated
  pipelines — measured files never drift ([diff&nbsp;D5](#d5)); the
  failed l1a hash appraisal IS the repair order, restore + re-attest
  **in-session**, no interaction, no l2 examination.
- **Slice** (`--repair-granularity slice`): the repair unit is the
  measurement unit ([diff&nbsp;D6](#d6)) — only the violated contract
  slice is spliced back, located by **content alignment** (difflib
  against golden; insertion-robust), benign drift elsewhere in the
  same file survives,
  and the files entry ends attested clean *via the l2 contracts
  refinement* — the terminal proof the note survived re-measurement.

## Scene 5 — verification failure, repair by selectable strategy

- The implementation drifts in its **developer-owned region** — the
  INSPECTA exemplar's own seeded bug (REQ-MHS-2 response inverted,
  [diff&nbsp;D7](#d7)). Every contract slice is intact, so integrity
  attests clean at finer
  granularity; the always-run verus tier refutes the crate: the
  generated contracts are genuinely **false** of the drifted behavior.
- Strategy chosen at the prompt or `--repair-strategy`: **restore**
  (the failing crate's hashed files from golden — crate-scoped, judged
  by fresh measurement in-session) or **pause** (out-of-band: the
  episode blocks on a work order, *you* repair in another terminal, and
  only fresh measurement — never your claim — re-establishes standing).
- Rocq's tactic-portfolio / LLM strategies have no honest counterpart
  here: Verus contracts are generated artifacts, so "repairing" them
  would launder the spec, and repairing the *implementation* was
  scene 2's ladder.

## Scene 6 — baseline tamper: the repair that must refuse

- Three beats, one gate, three attributed refusals: a **flipped byte of
  signed bundle evidence** ([diff&nbsp;D8](#d8); record integrity — the
  signature refutes), a **hand-edited installed golden**
  ([diff&nbsp;D9](#d9); installation consistency — the anchor refutes,
  signature silent), and **laundering** — a tampered spec
  ([diff&nbsp;D5](#d5) again) re-provisioned into fully
  self-consistent measurement baselines,
  refuted by semantic lineage: every hash and slice golden must be
  *derivable from the blessed signed bytes*, and ordinary provisioning
  cannot refresh the props blessing.
- Each stops attestation before it starts — the ready entry's failure
  chain is empty by design, so the only exit is the administrator's
  out-of-band re-bless.

## Scene 7 — toolchain tamper: measure-then-use catches the tool

- A **functionality-preserving** edit to the cargo-verus wrapper
  ([diff&nbsp;D10](#d10)): every verification still runs and looks fine,
  but the tool hash — taken in
  the same term, before use — refutes, and every proof cell poisons to
  `?` fail-closed. Readiness still passes: the stored record is
  coherent; the *live* tool drifted.
- Hash-only artifacts are unrepairable from goldens by design: the
  repair is the out-of-band pause rung — you restore the wrapper, fresh
  measurement re-establishes standing. (`--restore-tools` is the
  recovery hatch: reinstall the canonical wrapper, prove it against the
  blessed golden, confirm readiness.)

## Scene 8 — report tamper: the rendering anchored and regenerated

- The attestation report is the **authority** every protocol dir is
  derived from — measurement targets bind to contracts only through its
  structure — so the report itself is hashed measure-then-use as its
  own always-run entry. Beat 1: a **deleted slice**
  ([diff&nbsp;D11](#d11); a re-derived protocol would measure one
  target fewer than the blessing intended). Beat 2: a slice span
  **substituted** for a different contract's ([diff&nbsp;D12](#d12)) —
  counts stay right, structure stays plausible; only the byte anchor
  refutes.
- The repair is the regeneration species — neither restore nor
  synthesis: the report is a **rendering of the model through the
  measured codegen toolchain**, so the rung re-emits it (tool gate
  first, then real codegen) and the restarted episode re-attests.

## Scene 9 — proof cheat: verification success is not proof

Two beats, two proof escapes that pass every OUTCOME-based tier because
they change no proof outcome — caught only by the cheat scan, which
counts escape **constructs**.

- **Beat 1 — ADMIT** ([diff&nbsp;D13](#d13)): `assume(false)` admits a
  verified contract inside a bridge file **no hash or slice tier
  covers** (`thermostat_rt_mhs_mhs_api.rs` — Verus-verified but outside
  every l1a and l2 target). files/contracts green, and cargo-verus
  reports the **same success** over the hollow proof — the verus
  count golden is unchanged (an admit alters no count). Only the cheat
  tier refuses: `cheat_scan_verus` re-counts the proof-escape surface
  (assume, admit, external_body by path class, bare external,
  assume_specification, axiom, broadcast, uninterp — the constructs
  Verus's own `--no-cheating` flag names, textually scanned), and the
  drift (assume 0 → 1) fails the exact-bytes golden, attributing the
  crate.
- **Beat 2 — SMUGGLE** ([diff&nbsp;D14](#d14)): an `external_body`
  `broadcast proof fn` with `ensures false` planted in the shared
  `GUMBO_Library` — a foundation crate no hash or slice tier covers.
  It verifies clean on its own (the body is trusted) and is **inert
  until a `broadcast use`** pulls it in, so it changes no verified
  count: files, contracts, the **verus count golden**, the sysproof
  hash, and the report all stay green. Only the cheat scan catches it,
  at the staging point before any proof consumes it, naming
  `GUMBO_Library` (broadcast 0 → 1, external_body.other 0 → 1). The
  robust detector: a construct scan sees the escape even when every
  outcome is still clean.
- No repair rung **on purpose** (either beat): a proof escape is never
  machine-repairable — the refusal escalates to the administrator, and
  the driver restores the tamper site from a pre-episode snapshot (the
  cheat sites have no golden mirror, deliberately).
- The honest baseline the golden blesses: 86 `external_body` sites,
  all in generated bridge/component platform-boundary files; zero
  assume/admit/axiom/broadcast anywhere. The scan covers the seven
  component crates, the system proof crate, and the shared foundation
  crates (`data`, `GUMBO_Library`), where the only blessed escape is
  26 `uninterp` action fns in `sys_nominal_proof/actions.rs`.

## Scene 10 — the hollow system proof: count vs bytes

- `sys_nominal_proof` is the **system-level compositional proof**
  (~1862 obligations, one empty-bodied VC each, discharged by Verus).
  Two attacks that add **no escape construct**, so the cheat scan stays
  silent — a demonstration that "verification succeeded" is not
  enough, and neither is "no cheats present."
- **Beat 1 — SHRINK** ([diff&nbsp;D15](#d15)): comment out a proof
  module. The crate still verifies (0 errors) but proves fewer
  obligations, so the verus tier's **verified-COUNT** golden refuses
  (1862 drops) — the reason the tier goldens the whole normalized
  `verification-results`, not just `errors==0`. The sysproof hash
  refuses too (lib.rs changed).
- **Beat 2 — SWAP** ([diff&nbsp;D16](#d16)): drop a real VC and add a
  trivial `ensures true` one, holding the count at 1862. The verus
  tier goes **blind** (count preserved) and the cheat scan stays silent
  (no escape construct) — **only** the whole-file **sysproof hash**
  refuses, naming the swapped file in the refusal ("hash drift:
  src/normal_display_temp/vc_sequential.rs" — the batched appraiser
  carries per-file attribution in its reason). Bytes anchor what a
  count cannot. The sysproof crate is do-not-edit generated, so
  whole-file hashing with no benign-drift allowance is correct; no
  repair rung — the refusal escalates.

## Throughout

- **Opt-in VSCode diffs** at every artifact-modification beat: the
  seeded behavior bug (scene 5), the wrapper edit (scene 7), the
  deleted and substituted report slices (scene 8, pretty-printed
  JSON, shown BEFORE the arc — "see how innocent the tamper looks"),
  the admitted contract and the smuggled foundation axiom (scene 9's
  two beats, same before-the-arc reveal),
  the dummy-bad-impl inversion (scene 2), the codegen re-splice after
  a benign bless (scene 3), and scene 6's trust-state attacks — the
  flipped evidence byte and the hand-edited golden (both
  pretty-printed JSON), and the blessed-vs-laundered spec —
  `[v]iew diff / Enter to continue`, terminal fallback, skipped in
  unattended runs. Scene 3's ruling diff (golden vs proposed) is
  always shown. This document links the same diffs statically — see
  the [appendix](#appendix-artifact-diffs).
- Every scene gates on expected output (including no-✗/no-? checks on
  clean checklists), so regressions — or a dirty starting tree — abort
  loudly.
- Self-cleaning: tampered targets restore at every driver exit;
  bundles, goldens, wrapper, and any demo blessing are restored on
  script exit (scene 3's codegen catch-up requires a git-clean
  `targets/isolette-microkit` and restores through git).

Postponed by design: episode-triggering monitor, wall-clock repair
timeouts, the executable artifact class, blessing the report under the
props class (so a laundered report is refuted by lineage, not just by
the live hash), and a real spec-guided Rust implementation engine.

## Appendix: artifact diffs

The same diffs the script offers interactively (`[v]iew diff … / Enter`), statically. Paths are relative to `targets/isolette-microkit/` (model + generated tree) or the pybb repo root (trust state).

<a id="d1"></a>
### D1 — scene 2: the pre-generated dummy bad implementation

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -114,28 +114,25 
 
           // ----- INIT Mode --------
           Regulator_Mode::Init_Regulator_Mode => {
-              // REQ-MHS-1
-              currentCmd = On_Off::Off;
+              // DUMMY BAD IMPL: heat left ON during initialization
+              currentCmd = On_Off::Onn;
           },
 
           // ------ NORMAL Mode -------
           Regulator_Mode::Normal_Regulator_Mode => {
               if (currentTemp.degrees > upper.degrees) {
-                  // REQ-MHS-3
+                  // DUMMY BAD IMPL: inverted response when too hot
+                  currentCmd = On_Off::Onn;
+              } else if (currentTemp.degrees < lower.degrees) {
+                  // DUMMY BAD IMPL: inverted response when too cold
                   currentCmd = On_Off::Off;
-              } else if (currentTemp.degrees < lower.degrees) {
-                  assert(api.current_tempWstatus.degrees < api.lower_desired_temp.degrees);
-                  // REQ-MHS-2
-                  //currentCmd = On_Off::Off; // seeded bug/error
-                  currentCmd = On_Off::Onn;
               }
-              // otherwise currentCmd defaults to lastCmd (REQ-MHS-4)
           },
 
           // ------ FAILED Mode -------
           Regulator_Mode::Failed_Regulator_Mode => {
-              // REQ-MHS-5
-              currentCmd = On_Off::Off;
+              // DUMMY BAD IMPL: heat left ON after failure
+              currentCmd = On_Off::Onn;
           }
       }
 
```

<a id="d2"></a>
### D2 — scene 3 (benign): the `lower_is_lower_temp` restatement

Semantically equivalent (`x <= y` -> `y >= x`), in both components carrying the guarantee; the regenerated contracts still prove.

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -188,7 +188,7 
                 // general guarantee between outgoing port values
                 guarantee lower_is_lower_temp "Derived requirement, not in AR-08-32: MHS unconditionally assumes the
                                               |Desired Range is well-ordered,.":
-                    lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                    upper_desired_temp.degrees >= lower_desired_temp.degrees;
 
                 compute_cases
                     // ====== Regulator Status ======    
 -460,7 +460,7 
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
                 // assumption on set points enforced within the Operator Interface
-                assume lower_is_lower_temp: lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                assume lower_is_lower_temp: upper_desired_temp.degrees >= lower_desired_temp.degrees;
             
                 // the lastCmd state variable is always equal to the value of the heat_control output port
                 guarantee lastCmd "Set lastCmd to value of output Cmd port":
```

<a id="d3"></a>
### D3 — scene 3 (breaking): REQ_MHS_1's initialize guarantee flipped

Codegen accepts it; the implementation initializes the heat control Off, so the catch-up's proof gate must refuse.

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -455,7 +455,7 
                 guarantee REQ_MHS_1 "If the Regulator Mode is INIT, the Heat Control shall be
                                     |set to Off.
                                     |https://www.faa.gov/sites/faa.gov/files/aircraft/air_cert/design_approvals/air_software/AR-08-32.pdf#page=110 ":
-                    heat_control == Isolette_Data_Model::On_Off.Off;
+                    heat_control == Isolette_Data_Model::On_Off.Onn;
             
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
```

<a id="d4"></a>
### D4 — scene 3 (benign, blessed): the codegen re-splice

What `--promote` wrote back into the developer-owned file's marker region — the realization catching up with the blessed restatement.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -54,7 +54,7 
       requires
         // BEGIN MARKER TIME TRIGGERED REQUIRES
         // assume lower_is_lower_temp
-        old(api).lower_desired_temp.degrees <= old(api).upper_desired_temp.degrees,
+        old(api).upper_desired_temp.degrees >= old(api).lower_desired_temp.degrees,
         // END MARKER TIME TRIGGERED REQUIRES
       ensures
         // BEGIN MARKER TIME TRIGGERED ENSURES
```

<a id="d5"></a>
### D5 — scene 4 beat 1: the model drift (also scene 6's laundered edit)

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -188,7 +188,7 
                 // general guarantee between outgoing port values
                 guarantee lower_is_lower_temp "Derived requirement, not in AR-08-32: MHS unconditionally assumes the
                                               |Desired Range is well-ordered,.":
-                    lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                    lower_desired_temp.degrees < upper_desired_temp.degrees;
 
                 compute_cases
                     // ====== Regulator Status ======    
 -460,7 +460,7 
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
                 // assumption on set points enforced within the Operator Interface
-                assume lower_is_lower_temp: lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                assume lower_is_lower_temp: lower_desired_temp.degrees < upper_desired_temp.degrees;
             
                 // the lastCmd state variable is always equal to the value of the heat_control output port
                 guarantee lastCmd "Set lastCmd to value of output Cmd port":
```

<a id="d6"></a>
### D6 — scene 4 beat 2: one corrupted slice + the benign note

Slice restore splices back ONLY the violated block; the note survives, and the files entry passes via the l2 refinement.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -11,7 +11,7 
 
   pub struct thermostat_rt_mhs_mhs {
     // BEGIN MARKER STATE VARS
-    pub lastCmd: Isolette_Data_Model::On_Off,
+// TAMPERED: verus contract weakened
     // END MARKER STATE VARS
   }
 
 -175,3 +175,5 
   }
 
 }
+
+// engineering note: candidate sensor swap under review
```

<a id="d7"></a>
### D7 — scene 5: the seeded behavior bug

The INSPECTA exemplar's own seeded bug: in NORMAL mode below the lower bound, command Off instead of On.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -126,8 +126,8 
               } else if (currentTemp.degrees < lower.degrees) {
                   assert(api.current_tempWstatus.degrees < api.lower_desired_temp.degrees);
                   // REQ-MHS-2
-                  //currentCmd = On_Off::Off; // seeded bug/error
-                  currentCmd = On_Off::Onn;
+                  currentCmd = On_Off::Off; // seeded bug/error
+                  //currentCmd = On_Off::Onn;
               }
               // otherwise currentCmd defaults to lastCmd (REQ-MHS-4)
           },
```

<a id="d8"></a>
### D8 — scene 6 beat 1: one flipped byte of signed evidence

Pretty-printed and truncated; the change is a single character inside one RawEv slot of the props bundle.

```diff
--- a/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json
+++ b/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json
 -8,5 +8,5 
     "Ly8gTW9uaXRvci5zeXNtbApwYWNrYWdlIE1vbml0b3IgewogIAo…[truncated]…ogIH0KfQo=",
     "cGFja2FnZSBPcGVyYXRvcl9JbnRlcmZhY2UgewogIAogIHByaXZ…[truncated]…8KICB9Cn0K",
-    "Ly8gUmVndWxhdGUuc3lzbWwKCnBhY2thZ2UgUmVndWxhdGUgewo…[truncated]…CAgIH0KfQo="
+    "Ly8gUmVndWAhdGUuc3lzbWwKCnBhY2thZ2UgUmVndWxhdGUgewo…[truncated]…CAgIH0KfQo="
    ]
   },
```

<a id="d9"></a>
### D9 — scene 6 beat 2: one hand-edited installed golden

The bundle stays authentic; only the anchor to the signed evidence refutes.

```diff
--- a/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json
+++ b/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json
 -33,5 +33,5 
    "filepath": "/Users/adampetz/Claude_workspace/pybb/ta…[truncated]…late.sysml",
    "asp_targid": "isolette_sysmlv2_rust_props_regulate_targ",
-   "golden_b64": "Ly8gUmVndWxhdGUuc3lzbWwKCnBhY2thZ2UgUm…[truncated]…AgIH0KfQo=",
+   "golden_b64": "Ly8gUmVndWAhdGUuc3lzbWwKCnBhY2thZ2UgUm…[truncated]…AgIH0KfQo=",
    "golden_ts": "2026-08-17 09:04:12"
   }
```

<a id="d10"></a>
### D10 — scene 7: the functionality-preserving wrapper edit

```diff
--- a/~/Claude_workspace/bin/cargo-verus
+++ b/~/Claude_workspace/bin/cargo-verus
 -3,3 +3,4 
 # (CVM child processes see this via CvmConfig.path_prepend).
 export PATH="/Users/adampetz/Claude_workspace/verus-arm64-macos:$HOME/.cargo/bin:$PATH"
 exec /Users/adampetz/Claude_workspace/verus-arm64-macos/cargo-verus "$@"
+# drifted: innocuous-looking edit
```

<a id="d11"></a>
### D11 — scene 8 beat 1: the deleted report slice

Pretty-printed; one Verus slice quietly gone from the authority.

```diff
--- a/attestation/sysml_attestation_report.json
+++ b/attestation/sysml_attestation_report.json
 -36,19 +36,4 
         "length": 121
        }
-      },
-      {
-       "type": "Slice",
-       "kind": "Verus",
-       "meta": "Verus realization of GUMBO initializes contract",
-       "pos": {
-        "type": "Position",
-        "uri": "../crates/thermostat_rt_mri_mri/src/component/thermostat_rt_mri_mri_app.rs",
-        "beginLine": 25,
-        "beginCol": 11,
-        "endLine": 26,
-        "endCol": 72,
-        "offset": 567,
-        "length": 73
-       }
       }
      ]
```

<a id="d12"></a>
### D12 — scene 8 beat 2: the substituted slice span

Slice count unchanged; the slice now points at a different contract's lines in the same file.

```diff
--- a/attestation/sysml_attestation_report.json
+++ b/attestation/sysml_attestation_report.json
 -29,7 +29,7 
         "type": "Position",
         "uri": "../../../sysml/Regulate.sysml",
-        "beginLine": 176,
+        "beginLine": 182,
         "beginCol": 16,
-        "endLine": 177,
+        "endLine": 186,
         "endCol": 111,
         "offset": 9738,
```

<a id="d13"></a>
### D13 — scene 9: the admitted contract

One injected line: `put_heat_control`'s real `ensures` still stands in
the text, but the proof context now contains `false` — everything
downstream is vacuously provable, and cargo-verus reports the same
success.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/bridge/thermostat_rt_mhs_mhs_api.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/bridge/thermostat_rt_mhs_mhs_api.rs
 -85,6 +85,7 
         self.heat_control == value,
     {
+      assume(false); // TAMPERED: proof admitted
       self.api.unverified_put_heat_control(value);
       self.heat_control = value;
     }
```

<a id="d14"></a>
### D14 — scene 9 beat 2: the smuggled foundation axiom

An `external_body` `broadcast proof fn` with `ensures false`, planted in
the shared `GUMBO_Library`. The body is unchecked, so it verifies clean;
inert until a `broadcast use` pulls it in, so no verified count moves.
Only the construct scan sees it.

```diff
--- a/crates/GUMBO_Library/src/lib.rs
+++ b/crates/GUMBO_Library/src/lib.rs
 -172,6 +172,11 
     value.status == Isolette_Data_Model::ValueStatus::Valid
   }
+  // TAMPERED: smuggled proof-context poison (false, unchecked body)
+  #[verifier::external_body]
+  pub broadcast proof fn smuggled_axiom()
+    ensures false
+  {}
   // END MARKER GUMBO VERUS MARKER
```

<a id="d15"></a>
### D15 — scene 10 beat 1: the shrunken proof surface

One commented module: the crate still verifies (0 errors) but proves
fewer obligations, so the verified count drops below the golden 1862.

```diff
--- a/crates/sys_nominal_proof/src/lib.rs
+++ b/crates/sys_nominal_proof/src/lib.rs
 -49,1 +49,1 
-pub mod normal_display_temp;
+// pub mod normal_display_temp;  // COUNT TAMPER: module dropped
```

<a id="d16"></a>
### D16 — scene 10 beat 2: drop-and-replace at constant count

A real VC dropped, a trivial one added — the verified count stays 1862,
so the verus tier is blind; only the whole-file hash sees the change.

```diff
--- a/crates/sys_nominal_proof/src/normal_display_temp/vc_sequential.rs
+++ b/crates/sys_nominal_proof/src/normal_display_temp/vc_sequential.rs
 -19,7 +19,7 
 verus! {
+pub proof fn dropped_and_replaced() ensures true {}
 
-/** VC[1]: Pre-Assert -- before_oi |- OI compute assumes */
-pub proof fn vc_pre_assert_oi(st: SystemState)
-  requires
-    true /* before_oi has no assertion */,
-  ensures
-    true /* no assertions at out-places */,
-{}
-
 /** VC[2]: Next-Assert (task) ... */
 pub proof fn vc_next_assert_task_oi(pre: SystemState, post: SystemState)
```
