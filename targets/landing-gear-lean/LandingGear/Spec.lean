/-
The landing-gear specification: the retraction-interlock contracts as
Lean theorems over the implementation in LandingGear.Impl. The gear_check
protocol re-elaborates this file (`lake lean LandingGear/Spec.lean`), so
a change to the implementation that falsifies a contract is refuted by
proof even when every hash measurement was laundered to bless it.
-/
import LandingGear.Impl

namespace LandingGear

/-- Config_Data_Invariant: the retraction speed is positive and within
    the aircraft's placarded gear-operating envelope. -/
def Config.valid (cfg : Config) : Prop :=
  0 < cfg.retractSpeed ∧ cfg.retractSpeed ≤ 300

/-- Contract: a Down lever always commands Extend, whatever the sensors
    say — gear extension is never inhibited. -/
theorem extend_when_commanded (speed : Int) (cfg : Config) (wow : Bool) :
    computeGearCmd speed cfg .Down wow = .Extend := by
  cases wow <;> rfl

/-- Safety: the gear never retracts with weight on wheels. -/
theorem no_retract_on_ground (speed : Int) (cfg : Config) (lever : GearLever) :
    computeGearCmd speed cfg lever true ≠ .Retract := by
  cases lever <;> simp [computeGearCmd]

/-- Safety: the gear never retracts below the configured retraction
    speed. -/
theorem no_retract_below_speed (speed : Int) (cfg : Config)
    (lever : GearLever) (wow : Bool) (h : speed < cfg.retractSpeed) :
    computeGearCmd speed cfg lever wow ≠ .Retract := by
  cases lever <;> cases wow <;> simp [computeGearCmd, h]

/-- Contract: an Up lever retracts once airborne at or above the
    retraction speed. -/
theorem retract_when_safe (speed : Int) (cfg : Config)
    (h : cfg.retractSpeed ≤ speed) :
    computeGearCmd speed cfg .Up false = .Retract := by
  have hn : ¬ (speed < cfg.retractSpeed) := by omega
  simp [computeGearCmd, hn]

/-- Safety converse: retraction is only ever commanded with the lever Up,
    airborne, at or above the retraction speed. -/
theorem retract_only_when_safe (speed : Int) (cfg : Config)
    (lever : GearLever) (wow : Bool) :
    computeGearCmd speed cfg lever wow = .Retract →
    lever = .Up ∧ wow = false ∧ cfg.retractSpeed ≤ speed := by
  cases lever with
  | Down => cases wow <;> simp [computeGearCmd]
  | Up =>
    cases wow with
    | true => simp [computeGearCmd]
    | false =>
      simp only [computeGearCmd]
      split
      next => simp
      next hge => simp; omega

-- Executable sanity checks (kernel-evaluated).
example : computeGearCmd 80 ⟨140⟩ .Up true = .Hold := by decide
example : computeGearCmd 180 ⟨140⟩ .Up false = .Retract := by decide
example : computeGearCmd 200 ⟨140⟩ .Down false = .Extend := by decide

end LandingGear
