(* BLESSED: the canonical obligation binding — fails to elaborate if
   spec_holds is missing, renamed, or weaker than the blessed Spec. *)
Require Import TempControl.Proofs.
Definition acceptance : Spec computeFanCmd := spec_holds.
