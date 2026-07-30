import TempControl.Impl

open TempControl

/-
The executable: one control step. The verified computeFanCmd is the only
logic here — Main just parses arguments and prints the command, so the
attested behavior of the binary is exactly the behavior the theorems
in TempControl/Spec.lean constrain.

Usage: temp-control <temp> <low> <high> <On|Off>
Output (deterministic, appraised by the lean_exec protocol): fanCmd=<On|Off>
-/

def parseFan : String → Option FanCmd
  | "On"  => some .On
  | "Off" => some .Off
  | _     => none

def usage : String :=
  "usage: temp-control <temp> <low> <high> <On|Off>"

def main (args : List String) : IO UInt32 := do
  match args with
  | [t, lo, hi, latest] =>
    match t.toInt?, lo.toInt?, hi.toInt?, parseFan latest with
    | some temp, some low, some high, some l =>
      IO.println s!"fanCmd={computeFanCmd temp ⟨low, high⟩ l}"
      return 0
    | _, _, _, _ =>
      IO.eprintln usage
      return 1
  | _ =>
    IO.eprintln usage
    return 1
