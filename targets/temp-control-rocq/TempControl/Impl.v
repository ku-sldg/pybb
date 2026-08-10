(*
The implementation candidate — MUTABLE, never blessed: owned by the
workflow (or the developer). Its only attested property is semantic:
the proofs in Proofs.v must show it satisfies the blessed Spec
(Acceptance.v). Structural drift here is deliberately unmeasured.

Note the boolean/propositional gap the proofs must bridge: `if` needs
a bool, so guards are Z.ltb (<?) while the blessed properties speak
Z.lt (<) — Z.ltb_spec is the bridge.
*)
From Stdlib Require Import ZArith.
Require Export TempControl.Props.
Open Scope Z_scope.

(* The compute step: too hot -> On, too cold -> Off, in band -> hold the
   latest command. Has type `Step` — the blessed interface shape. *)
Definition computeFanCmd (temp : Z) (sp : SetPoint) (latest : FanCmd)
    : FanCmd :=
  if high sp <? temp then On
  else if temp <? low sp then Off
  else latest.
