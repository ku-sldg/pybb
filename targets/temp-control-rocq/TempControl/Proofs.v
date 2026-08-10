(*
Proofs — MUTABLE, never blessed: seed proofs the workflow may modify,
replace, or use as guidance, and where intermediate lemmas may be
introduced. A proof's only value is that the kernel accepts it AND the
assumptions audit finds it closed — `Admitted.` compiles cleanly (it
just adds an axiom), so elaboration alone proves nothing; Assumptions.v
is where provability is judged. The one obligation imposed from outside
is Acceptance.v (blessed): `spec_holds : Spec computeFanCmd` must exist
with exactly that type.
*)
From Stdlib Require Import ZArith Lia.
Require Export TempControl.Impl.
Open Scope Z_scope.

(* Intermediate lemma introduced by the workflow. *)
Lemma hot_means_not_cold : forall (temp : Z) (sp : SetPoint),
    SetPoint_valid sp -> high sp < temp -> ~ (temp < low sp).
Proof.
  unfold SetPoint_valid. intros temp sp Hv Hh. lia.
Qed.

Theorem fanOn_when_hot : fanOn_when_hot_prop computeFanCmd.
Proof.
  unfold fanOn_when_hot_prop, computeFanCmd. intros temp sp latest H.
  destruct (Z.ltb_spec (high sp) temp); [reflexivity | lia].
Qed.

Theorem fanOff_when_cold : fanOff_when_cold_prop computeFanCmd.
Proof.
  unfold fanOff_when_cold_prop, computeFanCmd, SetPoint_valid.
  intros temp sp latest Hv Hc.
  destruct (Z.ltb_spec (high sp) temp); [lia |].
  destruct (Z.ltb_spec temp (low sp)); [reflexivity | lia].
Qed.

Theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd.
Proof.
  unfold fanHold_in_band_prop, computeFanCmd. intros temp sp latest H1 H2.
  destruct (Z.ltb_spec (high sp) temp); [lia |].
  destruct (Z.ltb_spec temp (low sp)); [lia | reflexivity].
Qed.

Theorem fanOn_only_if_hot_or_held :
    fanOn_only_if_hot_or_held_prop computeFanCmd.
Proof.
  unfold fanOn_only_if_hot_or_held_prop, computeFanCmd.
  intros temp sp latest H.
  destruct (Z.ltb_spec (high sp) temp); [left; assumption |].
  destruct (Z.ltb_spec temp (low sp)); [discriminate | right; assumption].
Qed.

(* The acceptance witness: every blessed goal property holds of the
   implementation. Acceptance.v (blessed) pins this name and type. *)
Theorem spec_holds : Spec computeFanCmd.
Proof.
  exact (conj fanOn_when_hot
        (conj fanOff_when_cold
        (conj fanHold_in_band fanOn_only_if_hot_or_held))).
Qed.

(* Working material (kernel-evaluated sanity checks). *)
Example hot_vec : computeFanCmd 101 (mkSetPoint 70 90) Off = On.
Proof. reflexivity. Qed.
Example cold_vec : computeFanCmd 60 (mkSetPoint 70 90) On = Off.
Proof. reflexivity. Qed.
Example hold_vec : computeFanCmd 80 (mkSetPoint 70 90) On = On.
Proof. reflexivity. Qed.
