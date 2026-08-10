(*
The BLESSED statements file: the administrator's goal properties for the
temp-control system, stated abstractly over any candidate implementation.
Statement declarations only — no theorems, no proofs, no Axioms: blessing
this file signs WHAT MUST HOLD without fixing how it is implemented or
proved. The workflow owns Impl.v and Proofs.v; this file changes only
through --promote (re-blessing).
*)
From Stdlib Require Import ZArith.
Open Scope Z_scope.

Inductive FanCmd : Set :=
  | On
  | Off.

Record SetPoint : Set := mkSetPoint {
  low  : Z;
  high : Z
}.

(* SetPoint_Data_Invariant: the operating band is well-formed and within
   the physical range of the device. *)
Definition SetPoint_valid (sp : SetPoint) : Prop :=
  50 <= low sp /\ low sp <= high sp /\ high sp <= 110.

(* The shape of a candidate implementation: one control step from the
   current temperature, the operating band, and the latest command. *)
Definition Step : Type := Z -> SetPoint -> FanCmd -> FanCmd.

(* Goal: currentTemp above the band commands the fan On. *)
Definition fanOn_when_hot_prop (f : Step) : Prop :=
  forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
    high sp < temp -> f temp sp latest = On.

(* Goal: currentTemp below the band commands the fan Off. *)
Definition fanOff_when_cold_prop (f : Step) : Prop :=
  forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
    SetPoint_valid sp -> temp < low sp -> f temp sp latest = Off.

(* Goal: currentTemp inside the band holds the latest command. *)
Definition fanHold_in_band_prop (f : Step) : Prop :=
  forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
    low sp <= temp -> temp <= high sp -> f temp sp latest = latest.

(* Goal (safety): the fan is only ever On because the temperature
   demands it or because it was already On. *)
Definition fanOn_only_if_hot_or_held_prop (f : Step) : Prop :=
  forall (temp : Z) (sp : SetPoint) (latest : FanCmd),
    f temp sp latest = On -> high sp < temp \/ latest = On.

(* The blessed obligation: a sanctioned implementation satisfies every
   goal property. *)
Definition Spec (f : Step) : Prop :=
  fanOn_when_hot_prop f /\ fanOff_when_cold_prop f /\
  fanHold_in_band_prop f /\ fanOn_only_if_hot_or_held_prop f.
