import TempControl.Impl

open TempControl

/-
The executable: one control step. computeFanCmd is the only logic here —
Main just parses arguments and prints the command, so the attested
behavior of the binary is exactly the behavior the blessed goal
properties (TempControl/Props.lean) constrain via spec_holds.

Imports ONLY Impl: a tamper that breaks a proof cannot fail this build —
provability and behavior stay independent measurements.

Usage: temp-control-goals <temp> <low> <high> <On|Off>
Output (deterministic, appraised by the executable protocol): fanCmd=<On|Off>
-/

def parseFan : String → Option FanCmd
  | "On"  => some .On
  | "Off" => some .Off
  | _     => none

def usage : String :=
  "usage: temp-control-goals <temp> <low> <high> <On|Off>"

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
