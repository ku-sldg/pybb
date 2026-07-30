/-
The temp-control specification: the GUMBO compute contracts as Lean
theorems over the implementation in TempControl.Impl. The lean_check
protocol re-elaborates this file (`lake lean TempControl/Spec.lean`), so
a change to the implementation that falsifies a contract is refuted by
proof even when every hash measurement was laundered to bless it.
-/
import TempControl.Impl

namespace TempControl

/-- SetPoint_Data_Invariant: the operating band is well-formed and within
    the physical range of the device. -/
def SetPoint.valid (sp : SetPoint) : Prop :=
  50 ≤ sp.low ∧ sp.low ≤ sp.high ∧ sp.high ≤ 110

/-- GUMBO case: currentTemp above the band commands the fan On. -/
theorem fanOn_when_hot (temp : Int) (sp : SetPoint) (latest : FanCmd)
    (h : sp.high < temp) :
    computeFanCmd temp sp latest = .On := by
  simp [computeFanCmd, h]

/-- GUMBO case: currentTemp below the band commands the fan Off. -/
theorem fanOff_when_cold (temp : Int) (sp : SetPoint) (latest : FanCmd)
    (hv : sp.valid) (h : temp < sp.low) :
    computeFanCmd temp sp latest = .Off := by
  obtain ⟨_, hlh, _⟩ := hv
  have hnh : ¬ (sp.high < temp) := by omega
  simp [computeFanCmd, hnh, h]

/-- GUMBO case: currentTemp inside the band holds the latest command. -/
theorem fanHold_in_band (temp : Int) (sp : SetPoint) (latest : FanCmd)
    (h1 : sp.low ≤ temp) (h2 : temp ≤ sp.high) :
    computeFanCmd temp sp latest = latest := by
  have hnh : ¬ (sp.high < temp) := by omega
  have hnl : ¬ (temp < sp.low) := by omega
  simp [computeFanCmd, hnh, hnl]

/-- Safety: the fan is only ever On because the temperature demands it
    or because it was already On. -/
theorem fanOn_only_if_hot_or_held (temp : Int) (sp : SetPoint) (latest : FanCmd) :
    computeFanCmd temp sp latest = .On → sp.high < temp ∨ latest = .On := by
  unfold computeFanCmd
  split
  next hhot => exact fun _ => Or.inl hhot
  next =>
    split
    next => exact fun h => FanCmd.noConfusion h
    next => exact fun h => Or.inr h

-- Executable sanity checks (kernel-evaluated).
example : computeFanCmd 101 ⟨70, 90⟩ .Off = .On := by decide
example : computeFanCmd 60 ⟨70, 90⟩ .On = .Off := by decide
example : computeFanCmd 80 ⟨70, 90⟩ .On = .On := by decide

end TempControl
