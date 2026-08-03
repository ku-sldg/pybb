/-
The landing-gear implementation: data types and the gear-command step
function for the classic avionics retraction interlock — the lever may
command retraction, but the gear must never retract on the ground
(weight-on-wheels) or below the configured retraction speed.

Deliberately proof-free: the executable (Main) imports ONLY this module,
so `lake exe` never elaborates the specification — a tamper that breaks a
theorem cannot fail the exec tier's build. Provability (gear_check) and
behavior (gear_exec) stay independent measurements.
-/

namespace LandingGear

inductive GearLever where
  | Up
  | Down
deriving Repr, DecidableEq

inductive GearCmd where
  | Retract
  | Extend
  | Hold
deriving Repr, DecidableEq

instance : ToString GearCmd where
  toString
    | .Retract => "Retract"
    | .Extend => "Extend"
    | .Hold => "Hold"

structure Config where
  retractSpeed : Int
deriving Repr

/-- The compute entry point: lever Down always extends; lever Up retracts
    only airborne at or above the retraction speed, else holds. -/
def computeGearCmd (speed : Int) (cfg : Config) (lever : GearLever)
    (wow : Bool) : GearCmd :=
  match lever, wow with
  | .Down, _ => .Extend
  | .Up, true => .Hold
  | .Up, false =>
    if speed < cfg.retractSpeed then .Hold else .Retract

end LandingGear
