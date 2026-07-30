/-
The temp-control implementation: data types and the fan-control step
function, mirroring the HAMR TempControl tutorial (targets/temp-control-jvm,
targets/temp-control-microkit). Integer-first, matching the microkit/Verus
port.

Deliberately proof-free: the executable (Main) imports ONLY this module,
so `lake exe` never elaborates the specification — a tamper that breaks a
theorem cannot fail the exec tier's build. Provability (lean_check) and
behavior (lean_exec) stay independent measurements.
-/

namespace TempControl

inductive FanCmd where
  | On
  | Off
deriving Repr, DecidableEq

instance : ToString FanCmd where
  toString
    | .On => "On"
    | .Off => "Off"

structure SetPoint where
  low  : Int
  high : Int
deriving Repr

/-- The compute entry point: too hot → On, too cold → Off,
    in band → hold the latest command. -/
def computeFanCmd (temp : Int) (sp : SetPoint) (latest : FanCmd) : FanCmd :=
  if temp > sp.high then .On
  else if temp < sp.low then .Off
  else latest

end TempControl
