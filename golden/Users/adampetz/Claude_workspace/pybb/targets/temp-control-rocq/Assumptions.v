(*
The provability audit — deliberately OUTSIDE the dune theory: dune is
silent on warm (cached) builds, so Print output inside the theory would
vanish; this file is compiled fresh every verification run via
`rocq compile -R _build/default/TempControl TempControl Assumptions.v`.

One Print Assumptions per goal, in checklist order; the appraiser
(run_command_rocq_appr, assumptions mode) requires every section to be
"Closed under the global context". An Admitted proof or a smuggled
Axiom anywhere beneath a goal surfaces here by name.
*)
Require Import TempControl.Proofs.
Require Import TempControl.Acceptance.

Print Assumptions hot_means_not_cold.
Print Assumptions fanOn_when_hot.
Print Assumptions fanOff_when_cold.
Print Assumptions fanHold_in_band.
Print Assumptions fanOn_only_if_hot_or_held.
Print Assumptions spec_holds.
Print Assumptions acceptance.
