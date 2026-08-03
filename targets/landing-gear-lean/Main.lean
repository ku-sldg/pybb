import LandingGear.Impl

open LandingGear

/-
The executable: one control step. The verified computeGearCmd is the only
logic here — Main just parses arguments and prints the command, so the
attested behavior of the binary is exactly the behavior the theorems
in LandingGear/Spec.lean constrain.

Usage: landing-gear <speed> <retractSpeed> <Up|Down> <wow|air>
Output (deterministic, appraised by the gear_exec protocol):
gearCmd=<Retract|Extend|Hold>
-/

def parseLever : String → Option GearLever
  | "Up"   => some .Up
  | "Down" => some .Down
  | _      => none

def parseWow : String → Option Bool
  | "wow" => some true
  | "air" => some false
  | _     => none

def usage : String :=
  "usage: landing-gear <speed> <retractSpeed> <Up|Down> <wow|air>"

def main (args : List String) : IO UInt32 := do
  match args with
  | [s, rs, lever, wow] =>
    match s.toInt?, rs.toInt?, parseLever lever, parseWow wow with
    | some speed, some retractSpeed, some l, some w =>
      IO.println s!"gearCmd={computeGearCmd speed ⟨retractSpeed⟩ l w}"
      return 0
    | _, _, _, _ =>
      IO.eprintln usage
      return 1
  | _ =>
    IO.eprintln usage
    return 1
