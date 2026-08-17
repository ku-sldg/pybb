# `demo_rocq.sh` — detailed walkthrough

The eight-scene attestation demo on the Rocq example, scene by scene, with
the exact artifact modifications each step makes ([appendix of diffs](#appendix-artifact-diffs)).
The one-page version is [demo_rocq_script_summary.md](demo_rocq_script_summary.md);
driver arc reference is [demo_rocq.md](demo_rocq.md).

**Run it**: `./examples/demo_rocq.sh` — interactive, self-cleaning, keyless by
default. `--scenes "N ..."` for a subset, `--fast --auto bless|revert --drift
benign|breaking` for unattended runs, `--restore-tools` for toolchain
recovery. Pinned checkout: tag `rocq-demo-v2`.

At every artifact-modification beat the script offers the diff interactively
(`[v]iew diff … / Enter`); this document links the same diffs statically.

## Setup — readiness before anything

Bootstrap provisioning if no blessed baseline exists, then the readiness
gate: protocol config checks plus an appraisal-only CVM replay of every
**signed golden baseline** (signature, anchoring, derivability). Nothing
attests until this passes.

## Scene 1 — clean baseline

One episode over every artifact class — **model** (blessed `Props.v` +
`Acceptance.v`, signed), **contracts** (declaration-named slices),
**verification** (`dune build` + the kernel's assumptions audit), with the
rocq/dune toolchain hashed measure-then-use in the same term — then the
per-goal checklist, all `✓`. No artifacts are modified.

## Scene 2 — implementation tamper: the ladder repairs the right artifact

The implementation's hot response is inverted ([diff&nbsp;D13](#d13)): it
elaborates fine, but the blessed goals are genuinely **false** of it — no
proof can repair this. Proof repair exhausts, and the exhaustion is the
diagnosis:

    'synthesis:rocq-proofs' exhausted … handing to 'synthesis:rocq-impl'
    synthesis:rocq-impl: 'computeFanCmd' implemented (RocqSpecGuidedImplEngine)

The impl rung re-derives the implementation from the blessed statements
alone (deterministic spec-guided engine — the derived body is the canonical
guarded-if, i.e. [diff&nbsp;D13](#d13) reversed), the seed proofs prove
again, and the proofs end byte-untouched.

---

## Scene 3 — spec drift: escalate, examine, rule

A model edit drifts the blessed spec; the episode escalates with attribution
(each failing slice marked **modified ✗** vs **moved, content unchanged ✓**),
and the operator rules over the diff: **revert** to golden, or **bless** —
spec-first sanctioning that re-signs the model class only.

- Benign flavor — the physical ceiling moves 110 → 115
  ([diff&nbsp;D1](#d1)); proofs still prove after blessing.
- Breaking flavor — `fanOn_when_hot_prop` restated through a new blessed
  `commands` relation ([diff&nbsp;D2](#d2)): the model elaborates, but the
  seed proof's closers never unfold the new name. Blessing it shows the
  spec-first state — model/contracts clean against the new baseline,
  verification refuting the not-yet-proved obligation:

      temp_control_rocq:verification: integrity violation — …; user intervention required

  then `--repair-proofs` adapts the proof and the portfolio's accepted
  script is on screen ([diff&nbsp;D3](#d3)):

      synthesis:rocq-proofs: 'fanOn_when_hot' closed (RocqTacticPortfolioEngine)

## Scene 4 — restore, at two grains

- **Whole-file** (`--immutable-model`): the floor drifts 50 → 45
  ([diff&nbsp;D4](#d4)); the failed model hash appraisal IS the repair
  order — restore from golden and re-attest in-session, no interaction:

      repaired and re-attested clean in-session (episode 2)

- **Slice** (`--repair-granularity slice`): a benign note lands outside every
  declaration while one blessed slice is corrupted ([diff&nbsp;D5](#d5)).
  Only the violated declaration is spliced back (located by NAME —
  insertion-robust); the note survives to re-measurement, so the model entry
  ends attested clean *via the contracts refinement* — the terminal proof of
  repair-scope discipline:

      temp_control_rocq:model: all attested components intact (temp_control_rocq_contracts passed)

## Scene 5 — verification failure, repair by selectable strategy

One seed proof gets a wrong-but-well-formed tactic ([diff&nbsp;D6](#d6)).
The failure-time checklist names the failing contract with its diagnostic
while **isolation variants** judge every other proof individually
(per-goal `✓`/`✗` from one proofs file, instead of `?` poisoning):

    fanHold_in_band_prop  ✗  (fanHold_in_band: isolated: Error: Cannot find a relation to rewrite.)

Then the repair, by chosen strategy — **portfolio** (keyless; its accepted
script: [diff&nbsp;D7](#d7)), **llm** (behind the portfolio; dry-run without
a key), or **pause** (out-of-band: the episode blocks on a work order, you
repair in another terminal, fresh measurement judges; a decline is final).

## Scene 6 — baseline tamper: the repair that must refuse

Three attacks on the trust state itself; the live tree stays pristine, and
each is refuted with a distinct attributed property before attestation
starts. No knowledge source can repair a baseline — the only exit is the
administrator's out-of-band re-bless.

- **Record integrity** — one flipped byte of signed bundle evidence
  ([diff&nbsp;D8](#d8)):

      bundle signature verification FAILED: Signature verification failed

- **Installation consistency** — one hand-edited installed golden
  ([diff&nbsp;D9](#d9)); the signature stays silent:

      Blessed-content appraisal failed: blessed file content mismatch

- **Semantic lineage** — laundering: the spec is edited
  ([diff&nbsp;D4](#d4) again) and an *ordinary* re-provision re-signs the
  contracts baseline from the tampered tree. The laundered bundle is fully
  self-consistent — and refuted anyway, because ordinary provisioning cannot
  refresh the blessing:

      Blessed-content appraisal failed: temp_control_rocq_props_SetPoint_valid_targ: slice golden not extractable from blessed content

## Scene 7 — toolchain tamper: measure-then-use catches the tool

A functionality-preserving edit to the rocq wrapper ([diff&nbsp;D10](#d10)):
every build and audit still runs and looks fine, but the tool hash — taken
in the same term, before use — refutes, and every proof cell poisons
fail-closed:

    fanOn_when_hot_prop  ?  (toolchain measurement failed: tool_rocq_rocq_targ)

Hash-only artifacts are unrepairable from goldens by design: the repair is
the out-of-band pause rung, and `--restore-tools` is the recovery hatch
(reinstall the canonical wrapper, prove it against the blessed golden,
confirm readiness).

## Scene 8 — audit tamper: the rendering anchored to config

The audit file's sections bind to goals only through the file's structure,
so the rendering itself is hashed against its blessed canonical bytes,
measure-then-use.

- Beat 1 — a deleted `Print Assumptions` line ([diff&nbsp;D11](#d11)):
  coverage silently shrinks; the byte anchor refutes.
- Beat 2 — a query substituted for a different closed constant
  ([diff&nbsp;D12](#d12)): count right, every section "Closed", the output
  check alone fooled (`Print Assumptions` never echoes its query) — only
  the byte anchor refutes:

      audit file diverged from its canonical rendering (temp_control_rocq_audit_file_targ)

The repair is the third species — regeneration: the file is a rendering of
AM configuration, re-rendered byte-identically from `audit_goals`:

    repair:audit-regenerate: regenerated Assumptions.v from config (7 Print Assumptions, audit order)



## Appendix: artifact diffs

<a id="d13"></a>
### D13 — scene 2: the behavior inversion

```diff
--- a/TempControl/Impl.v
+++ b/TempControl/Impl.v
 -16,6 +16,6 
    latest command. Has type `Step` — the blessed interface shape. *)
 Definition computeFanCmd (temp : Z) (sp : SetPoint) (latest : FanCmd)
     : FanCmd :=
-  if high sp <? temp then On
+  if high sp <? temp then Off
   else if temp <? low sp then Off
   else latest.
```

---

*Diffs are generated from the demo's actual transforms against the committed
artifacts (D3/D7 are the engines' real accepted scripts). If the target
package or tampers change, regenerate this appendix alongside the script.*

<a id="d1"></a>
### D1 — scene 3 (benign): the ceiling edit

```diff
--- a/TempControl/Props.v
+++ b/TempControl/Props.v
 -21,7 +21,7 
 (* SetPoint_Data_Invariant: the operating band is well-formed and within
    the physical range of the device. *)
 Definition SetPoint_valid (sp : SetPoint) : Prop :=
-  50 <= low sp /\ low sp <= high sp /\ high sp <= 110.
+  50 <= low sp /\ low sp <= high sp /\ high sp <= 115.
 
 (* The shape of a candidate implementation: one control step from the
    current temperature, the operating band, and the latest command. *)
```

<a id="d2"></a>
### D2 — scene 3 (breaking): the `commands` restatement

```diff
--- a/TempControl/Props.v
+++ b/TempControl/Props.v
 -27,10 +27,15 
    current temperature, the operating band, and the latest command. *)
 Definition Step : Type := Z -> SetPoint -> FanCmd -> FanCmd.
 
+(* The command relation: f commands c in the given situation. *)
+Definition commands (f : Step) (t : Z) (sp : SetPoint)
+                    (l c : FanCmd) : Prop :=
+  f t sp l = c.
+
 (* Goal: currentTemp above the band commands the fan On. *)
 Definition fanOn_when_hot_prop (f : Step) : Prop :=
   forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
-    high sp < temp -> f temp sp latest = On.
+    high sp < temp -> commands f temp sp latest On.
 
 (* Goal: currentTemp below the band commands the fan Off. *)
 Definition fanOff_when_cold_prop (f : Step) : Prop :=
```

<a id="d3"></a>
### D3 — scene 3 (breaking, blessed): the machine-adapted proof

The tactic portfolio's accepted script for `fanOn_when_hot`, re-proving the
restated property (note the `commands` unfold):

```diff
--- a/TempControl/Proofs.v
+++ b/TempControl/Proofs.v
 -21,8 +21,9 
 
 Theorem fanOn_when_hot : fanOn_when_hot_prop computeFanCmd.
 Proof.
-  unfold fanOn_when_hot_prop, computeFanCmd. intros temp sp latest H.
-  destruct (Z.ltb_spec (high sp) temp); [reflexivity | lia].
+  unfold fanOn_when_hot_prop, SetPoint_valid, commands, computeFanCmd. intros.
+  repeat match goal with |- context [?a <? ?b] => destruct (Z.ltb_spec a b) end;
+  first [ reflexivity | discriminate | lia ].
 Qed.
 
 Theorem fanOff_when_cold : fanOff_when_cold_prop computeFanCmd.
```

<a id="d4"></a>
### D4 — scenes 4 and 6: the floor drift (also the laundered spec)

```diff
--- a/TempControl/Props.v
+++ b/TempControl/Props.v
 -21,7 +21,7 
 (* SetPoint_Data_Invariant: the operating band is well-formed and within
    the physical range of the device. *)
 Definition SetPoint_valid (sp : SetPoint) : Prop :=
-  50 <= low sp /\ low sp <= high sp /\ high sp <= 110.
+  45 <= low sp /\ low sp <= high sp /\ high sp <= 110.
 
 (* The shape of a candidate implementation: one control step from the
    current temperature, the operating band, and the latest command. *)
```

<a id="d5"></a>
### D5 — scene 4 (slice grain): benign note + violated slice

Slice-granularity repair restores only the `fanOn_when_hot_prop`
declaration; the trailing note survives:

```diff
--- a/TempControl/Props.v
+++ b/TempControl/Props.v
 -30,7 +30,7 
 (* Goal: currentTemp above the band commands the fan On. *)
 Definition fanOn_when_hot_prop (f : Step) : Prop :=
   forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
-    high sp < temp -> f temp sp latest = On.
+  (* TAMPERED: blessed statement weakened *)
 
 (* Goal: currentTemp below the band commands the fan Off. *)
 Definition fanOff_when_cold_prop (f : Step) : Prop :=
 -53,3 +53,5 
 Definition Spec (f : Step) : Prop :=
   fanOn_when_hot_prop f /\ fanOff_when_cold_prop f /\
   fanHold_in_band_prop f /\ fanOn_only_if_hot_or_held_prop f.
+
+(* engineering note: candidate sensor swap under review *)
```

<a id="d6"></a>
### D6 — scene 5: the corrupted seed proof

```diff
--- a/TempControl/Proofs.v
+++ b/TempControl/Proofs.v
 -35,9 +35,7 
 
 Theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd.
 Proof.
-  unfold fanHold_in_band_prop, computeFanCmd. intros temp sp latest H1 H2.
-  destruct (Z.ltb_spec (high sp) temp); [lia |].
-  destruct (Z.ltb_spec temp (low sp)); [lia | reflexivity].
+  intros. reflexivity.
 Qed.
 
 Theorem fanOn_only_if_hot_or_held :
```

<a id="d7"></a>
### D7 — scene 5: the machine-repaired proof

The portfolio's accepted script for `fanHold_in_band` (name-agnostic
destruction; contrast with the seed's fixed intros):

```diff
--- a/TempControl/Proofs.v
+++ b/TempControl/Proofs.v
 -35,9 +35,9 
 
 Theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd.
 Proof.
-  unfold fanHold_in_band_prop, computeFanCmd. intros temp sp latest H1 H2.
-  destruct (Z.ltb_spec (high sp) temp); [lia |].
-  destruct (Z.ltb_spec temp (low sp)); [lia | reflexivity].
+  unfold fanHold_in_band_prop, computeFanCmd. intros.
+  repeat match goal with |- context [?a <? ?b] => destruct (Z.ltb_spec a b) end;
+  first [ reflexivity | discriminate | lia ].
 Qed.
 
 Theorem fanOn_only_if_hot_or_held :
```

<a id="d8"></a>
### D8 — scene 6 beat 1: one flipped byte of signed evidence

Pretty-printed; the change is a single character inside one RawEv slot:

```diff
--- a/golden/_bundles/temp_control_rocq_model/provision_bundle.json
+++ b/golden/_bundles/temp_control_rocq_model/provision_bundle.json
 -7,3 +7,3 
     "bS0TdzL833T8oK5X2/U4i3IfTIKsZbIk17wyJEyC0yo=",
-    "KCoKVGhlIEJMRVNTRUQgc3RhdGVtZW50cyBmaWxlOiB0aGUgYWRtaW5pc3RyYXRvcidzIGdvYWwgcHJvcGVydGllcyBmb3IgdGhlCnRlbXAtY29udHJvbCBzeXN0ZW0sIHN0YXRlZCBhYnN0cmFjdGx5IG92ZXIgYW55IGNhbmRpZGF0ZSBpbXBsZW1lbnRhdGlvbi4KU3RhdGVtZW50IGRlY2xhcmF0aW9ucyBvbmx5IOKAlCBubyB0aGVvcmVtcywgbm8gcHJvb2ZzLCBubyBBeGlvbXM6IGJsZXNzaW5nCnRoaXMgZmlsZSBzaWducyBXSEFUIE1VU1QgSE9MRCB3aXRob3V0IGZpeGluZyBob3cgaXQgaXMgaW1wbGVtZW50ZWQgb3IKcHJvdmVkLiBUaGUgd29ya2Zsb3cgb3ducyBJbXBsLnYgYW5kIFByb29mcy52OyB0aGlzIGZpbGUgY2hhbmdlcyBvbmx5CnRocm91Z2ggLS1wcm9tb3RlIChyZS1ibGVzc2luZykuCiopCkZyb20gU3RkbGliIFJlcXVpcmUgSW1wb3J0IFpBcml0aC4KT3BlbiBTY29wZSBaX3Njb3BlLgoKSW5kdWN0aXZlIEZhbkNtZCA6IFNldCA6PQogIHwgT24KICB8IE9mZi4KClJlY29yZCBTZXRQb2ludCA6IFNldCA6PSBta1NldFBvaW50IHsKICBsb3cgIDogWjsKICBoaWdoIDogWgp9LgoKKCogU2V0UG9pbnRfRGF0YV9JbnZhcmlhbnQ6IHRoZSBvcGVyYXRpbmcgYmFuZCBpcyB3ZWxsLWZvcm1lZCBhbmQgd2l0aGluCiAgIHRoZSBwaHlzaWNhbCByYW5nZSBvZiB0aGUgZGV2aWNlLiAqKQpEZWZpbml0aW9uIFNldFBvaW50X3ZhbGlkIChzcCA6IFNldFBvaW50KSA6IFByb3AgOj0KICA1MCA8PSBsb3cgc3AgL1wgbG93IHNwIDw9IGhpZ2ggc3AgL1wgaGlnaCBzcCA8PSAxMTAuCgooKiBUaGUgc2hhcGUgb2YgYSBjYW5kaWRhdGUgaW1wbGVtZW50YXRpb246IG9uZSBjb250cm9sIHN0ZXAgZnJvbSB0aGUKICAgY3VycmVudCB0ZW1wZXJhdHVyZSwgdGhlIG9wZXJhdGluZyBiYW5kLCBhbmQgdGhlIGxhdGVzdCBjb21tYW5kLiAqKQpEZWZpbml0aW9uIFN0ZXAgOiBUeXBlIDo9IFogLT4gU2V0UG9pbnQgLT4gRmFuQ21kIC0+IEZhbkNtZC4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGFib3ZlIHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT24uICopCkRlZmluaXRpb24gZmFuT25fd2hlbl9ob3RfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIGhpZ2ggc3AgPCB0ZW1wIC0+IGYgdGVtcCBzcCBsYXRlc3QgPSBPbi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGJlbG93IHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT2ZmLiAqKQpEZWZpbml0aW9uIGZhbk9mZl93aGVuX2NvbGRfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIFNldFBvaW50X3ZhbGlkIHNwIC0+IHRlbXAgPCBsb3cgc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IE9mZi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGluc2lkZSB0aGUgYmFuZCBob2xkcyB0aGUgbGF0ZXN0IGNvbW1hbmQuICopCkRlZmluaXRpb24gZmFuSG9sZF9pbl9iYW5kX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBsb3cgc3AgPD0gdGVtcCAtPiB0ZW1wIDw9IGhpZ2ggc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IGxhdGVzdC4KCigqIEdvYWwgKHNhZmV0eSk6IHRoZSBmYW4gaXMgb25seSBldmVyIE9uIGJlY2F1c2UgdGhlIHRlbXBlcmF0dXJlCiAgIGRlbWFuZHMgaXQgb3IgYmVjYXVzZSBpdCB3YXMgYWxyZWFkeSBPbi4gKikKRGVmaW5pdGlvbiBmYW5Pbl9vbmx5X2lmX2hvdF9vcl9oZWxkX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBmIHRlbXAgc3AgbGF0ZXN0ID0gT24gLT4gaGlnaCBzcCA8IHRlbXAgXC8gbGF0ZXN0ID0gT24uCgooKiBUaGUgYmxlc3NlZCBvYmxpZ2F0aW9uOiBhIHNhbmN0aW9uZWQgaW1wbGVtZW50YXRpb24gc2F0aXNmaWVzIGV2ZXJ5CiAgIGdvYWwgcHJvcGVydHkuICopCkRlZmluaXRpb24gU3BlYyAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZhbk9uX3doZW5faG90X3Byb3AgZiAvXCBmYW5PZmZfd2hlbl9jb2xkX3Byb3AgZiAvXAogIGZhbkhvbGRfaW5fYmFuZF9wcm9wIGYgL1wgZmFuT25fb25seV9pZl9ob3Rfb3JfaGVsZF9wcm9wIGYuCg==",
+    "KCoKVGhlIEAMRVNTRUQgc3RhdGVtZW50cyBmaWxlOiB0aGUgYWRtaW5pc3RyYXRvcidzIGdvYWwgcHJvcGVydGllcyBmb3IgdGhlCnRlbXAtY29udHJvbCBzeXN0ZW0sIHN0YXRlZCBhYnN0cmFjdGx5IG92ZXIgYW55IGNhbmRpZGF0ZSBpbXBsZW1lbnRhdGlvbi4KU3RhdGVtZW50IGRlY2xhcmF0aW9ucyBvbmx5IOKAlCBubyB0aGVvcmVtcywgbm8gcHJvb2ZzLCBubyBBeGlvbXM6IGJsZXNzaW5nCnRoaXMgZmlsZSBzaWducyBXSEFUIE1VU1QgSE9MRCB3aXRob3V0IGZpeGluZyBob3cgaXQgaXMgaW1wbGVtZW50ZWQgb3IKcHJvdmVkLiBUaGUgd29ya2Zsb3cgb3ducyBJbXBsLnYgYW5kIFByb29mcy52OyB0aGlzIGZpbGUgY2hhbmdlcyBvbmx5CnRocm91Z2ggLS1wcm9tb3RlIChyZS1ibGVzc2luZykuCiopCkZyb20gU3RkbGliIFJlcXVpcmUgSW1wb3J0IFpBcml0aC4KT3BlbiBTY29wZSBaX3Njb3BlLgoKSW5kdWN0aXZlIEZhbkNtZCA6IFNldCA6PQogIHwgT24KICB8IE9mZi4KClJlY29yZCBTZXRQb2ludCA6IFNldCA6PSBta1NldFBvaW50IHsKICBsb3cgIDogWjsKICBoaWdoIDogWgp9LgoKKCogU2V0UG9pbnRfRGF0YV9JbnZhcmlhbnQ6IHRoZSBvcGVyYXRpbmcgYmFuZCBpcyB3ZWxsLWZvcm1lZCBhbmQgd2l0aGluCiAgIHRoZSBwaHlzaWNhbCByYW5nZSBvZiB0aGUgZGV2aWNlLiAqKQpEZWZpbml0aW9uIFNldFBvaW50X3ZhbGlkIChzcCA6IFNldFBvaW50KSA6IFByb3AgOj0KICA1MCA8PSBsb3cgc3AgL1wgbG93IHNwIDw9IGhpZ2ggc3AgL1wgaGlnaCBzcCA8PSAxMTAuCgooKiBUaGUgc2hhcGUgb2YgYSBjYW5kaWRhdGUgaW1wbGVtZW50YXRpb246IG9uZSBjb250cm9sIHN0ZXAgZnJvbSB0aGUKICAgY3VycmVudCB0ZW1wZXJhdHVyZSwgdGhlIG9wZXJhdGluZyBiYW5kLCBhbmQgdGhlIGxhdGVzdCBjb21tYW5kLiAqKQpEZWZpbml0aW9uIFN0ZXAgOiBUeXBlIDo9IFogLT4gU2V0UG9pbnQgLT4gRmFuQ21kIC0+IEZhbkNtZC4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGFib3ZlIHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT24uICopCkRlZmluaXRpb24gZmFuT25fd2hlbl9ob3RfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIGhpZ2ggc3AgPCB0ZW1wIC0+IGYgdGVtcCBzcCBsYXRlc3QgPSBPbi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGJlbG93IHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT2ZmLiAqKQpEZWZpbml0aW9uIGZhbk9mZl93aGVuX2NvbGRfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIFNldFBvaW50X3ZhbGlkIHNwIC0+IHRlbXAgPCBsb3cgc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IE9mZi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGluc2lkZSB0aGUgYmFuZCBob2xkcyB0aGUgbGF0ZXN0IGNvbW1hbmQuICopCkRlZmluaXRpb24gZmFuSG9sZF9pbl9iYW5kX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBsb3cgc3AgPD0gdGVtcCAtPiB0ZW1wIDw9IGhpZ2ggc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IGxhdGVzdC4KCigqIEdvYWwgKHNhZmV0eSk6IHRoZSBmYW4gaXMgb25seSBldmVyIE9uIGJlY2F1c2UgdGhlIHRlbXBlcmF0dXJlCiAgIGRlbWFuZHMgaXQgb3IgYmVjYXVzZSBpdCB3YXMgYWxyZWFkeSBPbi4gKikKRGVmaW5pdGlvbiBmYW5Pbl9vbmx5X2lmX2hvdF9vcl9oZWxkX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBmIHRlbXAgc3AgbGF0ZXN0ID0gT24gLT4gaGlnaCBzcCA8IHRlbXAgXC8gbGF0ZXN0ID0gT24uCgooKiBUaGUgYmxlc3NlZCBvYmxpZ2F0aW9uOiBhIHNhbmN0aW9uZWQgaW1wbGVtZW50YXRpb24gc2F0aXNmaWVzIGV2ZXJ5CiAgIGdvYWwgcHJvcGVydHkuICopCkRlZmluaXRpb24gU3BlYyAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZhbk9uX3doZW5faG90X3Byb3AgZiAvXCBmYW5PZmZfd2hlbl9jb2xkX3Byb3AgZiAvXAogIGZhbkhvbGRfaW5fYmFuZF9wcm9wIGYgL1wgZmFuT25fb25seV9pZl9ob3Rfb3JfaGVsZF9wcm9wIGYuCg==",
     "CGByQCahXx9o4dSUFf0abD2XXgDm+4QhJBTwuOUd1o0="
```

<a id="d9"></a>
### D9 — scene 6 beat 2: one hand-edited installed golden

```diff
--- a/tests/fixtures/temp_control_rocq_model/asp_args.json
+++ b/tests/fixtures/temp_control_rocq_model/asp_args.json
 -13,3 +13,3 
    "asp_targid": "temp_control_rocq_model_props_targ",
-   "golden_b64": "KCoKVGhlIEJMRVNTRUQgc3RhdGVtZW50cyBmaWxlOiB0aGUgYWRtaW5pc3RyYXRvcidzIGdvYWwgcHJvcGVydGllcyBmb3IgdGhlCnRlbXAtY29udHJvbCBzeXN0ZW0sIHN0YXRlZCBhYnN0cmFjdGx5IG92ZXIgYW55IGNhbmRpZGF0ZSBpbXBsZW1lbnRhdGlvbi4KU3RhdGVtZW50IGRlY2xhcmF0aW9ucyBvbmx5IOKAlCBubyB0aGVvcmVtcywgbm8gcHJvb2ZzLCBubyBBeGlvbXM6IGJsZXNzaW5nCnRoaXMgZmlsZSBzaWducyBXSEFUIE1VU1QgSE9MRCB3aXRob3V0IGZpeGluZyBob3cgaXQgaXMgaW1wbGVtZW50ZWQgb3IKcHJvdmVkLiBUaGUgd29ya2Zsb3cgb3ducyBJbXBsLnYgYW5kIFByb29mcy52OyB0aGlzIGZpbGUgY2hhbmdlcyBvbmx5CnRocm91Z2ggLS1wcm9tb3RlIChyZS1ibGVzc2luZykuCiopCkZyb20gU3RkbGliIFJlcXVpcmUgSW1wb3J0IFpBcml0aC4KT3BlbiBTY29wZSBaX3Njb3BlLgoKSW5kdWN0aXZlIEZhbkNtZCA6IFNldCA6PQogIHwgT24KICB8IE9mZi4KClJlY29yZCBTZXRQb2ludCA6IFNldCA6PSBta1NldFBvaW50IHsKICBsb3cgIDogWjsKICBoaWdoIDogWgp9LgoKKCogU2V0UG9pbnRfRGF0YV9JbnZhcmlhbnQ6IHRoZSBvcGVyYXRpbmcgYmFuZCBpcyB3ZWxsLWZvcm1lZCBhbmQgd2l0aGluCiAgIHRoZSBwaHlzaWNhbCByYW5nZSBvZiB0aGUgZGV2aWNlLiAqKQpEZWZpbml0aW9uIFNldFBvaW50X3ZhbGlkIChzcCA6IFNldFBvaW50KSA6IFByb3AgOj0KICA1MCA8PSBsb3cgc3AgL1wgbG93IHNwIDw9IGhpZ2ggc3AgL1wgaGlnaCBzcCA8PSAxMTAuCgooKiBUaGUgc2hhcGUgb2YgYSBjYW5kaWRhdGUgaW1wbGVtZW50YXRpb246IG9uZSBjb250cm9sIHN0ZXAgZnJvbSB0aGUKICAgY3VycmVudCB0ZW1wZXJhdHVyZSwgdGhlIG9wZXJhdGluZyBiYW5kLCBhbmQgdGhlIGxhdGVzdCBjb21tYW5kLiAqKQpEZWZpbml0aW9uIFN0ZXAgOiBUeXBlIDo9IFogLT4gU2V0UG9pbnQgLT4gRmFuQ21kIC0+IEZhbkNtZC4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGFib3ZlIHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT24uICopCkRlZmluaXRpb24gZmFuT25fd2hlbl9ob3RfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIGhpZ2ggc3AgPCB0ZW1wIC0+IGYgdGVtcCBzcCBsYXRlc3QgPSBPbi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGJlbG93IHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT2ZmLiAqKQpEZWZpbml0aW9uIGZhbk9mZl93aGVuX2NvbGRfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIFNldFBvaW50X3ZhbGlkIHNwIC0+IHRlbXAgPCBsb3cgc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IE9mZi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGluc2lkZSB0aGUgYmFuZCBob2xkcyB0aGUgbGF0ZXN0IGNvbW1hbmQuICopCkRlZmluaXRpb24gZmFuSG9sZF9pbl9iYW5kX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBsb3cgc3AgPD0gdGVtcCAtPiB0ZW1wIDw9IGhpZ2ggc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IGxhdGVzdC4KCigqIEdvYWwgKHNhZmV0eSk6IHRoZSBmYW4gaXMgb25seSBldmVyIE9uIGJlY2F1c2UgdGhlIHRlbXBlcmF0dXJlCiAgIGRlbWFuZHMgaXQgb3IgYmVjYXVzZSBpdCB3YXMgYWxyZWFkeSBPbi4gKikKRGVmaW5pdGlvbiBmYW5Pbl9vbmx5X2lmX2hvdF9vcl9oZWxkX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBmIHRlbXAgc3AgbGF0ZXN0ID0gT24gLT4gaGlnaCBzcCA8IHRlbXAgXC8gbGF0ZXN0ID0gT24uCgooKiBUaGUgYmxlc3NlZCBvYmxpZ2F0aW9uOiBhIHNhbmN0aW9uZWQgaW1wbGVtZW50YXRpb24gc2F0aXNmaWVzIGV2ZXJ5CiAgIGdvYWwgcHJvcGVydHkuICopCkRlZmluaXRpb24gU3BlYyAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZhbk9uX3doZW5faG90X3Byb3AgZiAvXCBmYW5PZmZfd2hlbl9jb2xkX3Byb3AgZiAvXAogIGZhbkhvbGRfaW5fYmFuZF9wcm9wIGYgL1wgZmFuT25fb25seV9pZl9ob3Rfb3JfaGVsZF9wcm9wIGYuCg==",
+   "golden_b64": "KCoKVGhlIEAMRVNTRUQgc3RhdGVtZW50cyBmaWxlOiB0aGUgYWRtaW5pc3RyYXRvcidzIGdvYWwgcHJvcGVydGllcyBmb3IgdGhlCnRlbXAtY29udHJvbCBzeXN0ZW0sIHN0YXRlZCBhYnN0cmFjdGx5IG92ZXIgYW55IGNhbmRpZGF0ZSBpbXBsZW1lbnRhdGlvbi4KU3RhdGVtZW50IGRlY2xhcmF0aW9ucyBvbmx5IOKAlCBubyB0aGVvcmVtcywgbm8gcHJvb2ZzLCBubyBBeGlvbXM6IGJsZXNzaW5nCnRoaXMgZmlsZSBzaWducyBXSEFUIE1VU1QgSE9MRCB3aXRob3V0IGZpeGluZyBob3cgaXQgaXMgaW1wbGVtZW50ZWQgb3IKcHJvdmVkLiBUaGUgd29ya2Zsb3cgb3ducyBJbXBsLnYgYW5kIFByb29mcy52OyB0aGlzIGZpbGUgY2hhbmdlcyBvbmx5CnRocm91Z2ggLS1wcm9tb3RlIChyZS1ibGVzc2luZykuCiopCkZyb20gU3RkbGliIFJlcXVpcmUgSW1wb3J0IFpBcml0aC4KT3BlbiBTY29wZSBaX3Njb3BlLgoKSW5kdWN0aXZlIEZhbkNtZCA6IFNldCA6PQogIHwgT24KICB8IE9mZi4KClJlY29yZCBTZXRQb2ludCA6IFNldCA6PSBta1NldFBvaW50IHsKICBsb3cgIDogWjsKICBoaWdoIDogWgp9LgoKKCogU2V0UG9pbnRfRGF0YV9JbnZhcmlhbnQ6IHRoZSBvcGVyYXRpbmcgYmFuZCBpcyB3ZWxsLWZvcm1lZCBhbmQgd2l0aGluCiAgIHRoZSBwaHlzaWNhbCByYW5nZSBvZiB0aGUgZGV2aWNlLiAqKQpEZWZpbml0aW9uIFNldFBvaW50X3ZhbGlkIChzcCA6IFNldFBvaW50KSA6IFByb3AgOj0KICA1MCA8PSBsb3cgc3AgL1wgbG93IHNwIDw9IGhpZ2ggc3AgL1wgaGlnaCBzcCA8PSAxMTAuCgooKiBUaGUgc2hhcGUgb2YgYSBjYW5kaWRhdGUgaW1wbGVtZW50YXRpb246IG9uZSBjb250cm9sIHN0ZXAgZnJvbSB0aGUKICAgY3VycmVudCB0ZW1wZXJhdHVyZSwgdGhlIG9wZXJhdGluZyBiYW5kLCBhbmQgdGhlIGxhdGVzdCBjb21tYW5kLiAqKQpEZWZpbml0aW9uIFN0ZXAgOiBUeXBlIDo9IFogLT4gU2V0UG9pbnQgLT4gRmFuQ21kIC0+IEZhbkNtZC4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGFib3ZlIHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT24uICopCkRlZmluaXRpb24gZmFuT25fd2hlbl9ob3RfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIGhpZ2ggc3AgPCB0ZW1wIC0+IGYgdGVtcCBzcCBsYXRlc3QgPSBPbi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGJlbG93IHRoZSBiYW5kIGNvbW1hbmRzIHRoZSBmYW4gT2ZmLiAqKQpEZWZpbml0aW9uIGZhbk9mZl93aGVuX2NvbGRfcHJvcCAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZvcmFsbCAodGVtcCA6IFopIChzcCA6IFNldFBvaW50KSAobGF0ZXN0IDogRmFuQ21kKSwKICAgIFNldFBvaW50X3ZhbGlkIHNwIC0+IHRlbXAgPCBsb3cgc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IE9mZi4KCigqIEdvYWw6IGN1cnJlbnRUZW1wIGluc2lkZSB0aGUgYmFuZCBob2xkcyB0aGUgbGF0ZXN0IGNvbW1hbmQuICopCkRlZmluaXRpb24gZmFuSG9sZF9pbl9iYW5kX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBsb3cgc3AgPD0gdGVtcCAtPiB0ZW1wIDw9IGhpZ2ggc3AgLT4gZiB0ZW1wIHNwIGxhdGVzdCA9IGxhdGVzdC4KCigqIEdvYWwgKHNhZmV0eSk6IHRoZSBmYW4gaXMgb25seSBldmVyIE9uIGJlY2F1c2UgdGhlIHRlbXBlcmF0dXJlCiAgIGRlbWFuZHMgaXQgb3IgYmVjYXVzZSBpdCB3YXMgYWxyZWFkeSBPbi4gKikKRGVmaW5pdGlvbiBmYW5Pbl9vbmx5X2lmX2hvdF9vcl9oZWxkX3Byb3AgKGYgOiBTdGVwKSA6IFByb3AgOj0KICBmb3JhbGwgKHRlbXAgOiBaKSAoc3AgOiBTZXRQb2ludCkgKGxhdGVzdCA6IEZhbkNtZCksCiAgICBmIHRlbXAgc3AgbGF0ZXN0ID0gT24gLT4gaGlnaCBzcCA8IHRlbXAgXC8gbGF0ZXN0ID0gT24uCgooKiBUaGUgYmxlc3NlZCBvYmxpZ2F0aW9uOiBhIHNhbmN0aW9uZWQgaW1wbGVtZW50YXRpb24gc2F0aXNmaWVzIGV2ZXJ5CiAgIGdvYWwgcHJvcGVydHkuICopCkRlZmluaXRpb24gU3BlYyAoZiA6IFN0ZXApIDogUHJvcCA6PQogIGZhbk9uX3doZW5faG90X3Byb3AgZiAvXCBmYW5PZmZfd2hlbl9jb2xkX3Byb3AgZiAvXAogIGZhbkhvbGRfaW5fYmFuZF9wcm9wIGYgL1wgZmFuT25fb25seV9pZl9ob3Rfb3JfaGVsZF9wcm9wIGYuCg==",
    "golden_ts": "2026-08-13 14:22:59"
```

<a id="d10"></a>
### D10 — scene 7: the functionality-preserving wrapper edit

```diff
--- a/~/Claude_workspace/bin/rocq
+++ b/~/Claude_workspace/bin/rocq
 -5,3 +5,4 
 # coqdep, ...) resolve from the same pinned switch.
 export PATH="$HOME/.opam/5.2/bin:$PATH"
 exec "$HOME/.opam/5.2/bin/rocq" "$@"
+# drifted: innocuous-looking edit
```

<a id="d11"></a>
### D11 — scene 8 beat 1: the deleted audit query

```diff
--- a/Assumptions.v
+++ b/Assumptions.v
 -15,7 +15,6 
 Print Assumptions hot_means_not_cold.
 Print Assumptions fanOn_when_hot.
 Print Assumptions fanOff_when_cold.
-Print Assumptions fanHold_in_band.
 Print Assumptions fanOn_only_if_hot_or_held.
 Print Assumptions spec_holds.
 Print Assumptions acceptance.
```

<a id="d12"></a>
### D12 — scene 8 beat 2: the substituted audit query

```diff
--- a/Assumptions.v
+++ b/Assumptions.v
 -15,7 +15,7 
 Print Assumptions hot_means_not_cold.
 Print Assumptions fanOn_when_hot.
 Print Assumptions fanOff_when_cold.
-Print Assumptions fanHold_in_band.
+Print Assumptions hot_means_not_cold.
 Print Assumptions fanOn_only_if_hot_or_held.
 Print Assumptions spec_holds.
 Print Assumptions acceptance.
```
