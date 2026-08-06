/-
The BLESSED statements file: the administrator's goal properties for the
temp-control system, stated abstractly over any candidate implementation.
Self-contained by design — no imports, no theorems, no proofs: every
declaration is a type or a Prop-valued definition, so blessing this file
signs WHAT MUST HOLD without fixing how it is implemented or proved.
The workflow owns Impl.lean and Proofs.lean; this file changes only
through --promote (re-blessing).
-/

namespace TempControl

inductive FanCmd where
  | On
  | Off
deriving Repr, DecidableEq

structure SetPoint where
  low  : Int
  high : Int
deriving Repr

/-- SetPoint_Data_Invariant: the operating band is well-formed and within
    the physical range of the device. -/
def SetPoint.valid (sp : SetPoint) : Prop :=
  50 ≤ sp.low ∧ sp.low ≤ sp.high ∧ sp.high ≤ 110

/-- The shape of a candidate implementation: one control step from the
    current temperature, the operating band, and the latest command. -/
abbrev Step := Int → SetPoint → FanCmd → FanCmd

/-- Goal: currentTemp above the band commands the fan On. -/
def fanOn_when_hot_prop (f : Step) : Prop :=
  ∀ (temp : Int) (sp : SetPoint) (latest : FanCmd),
    sp.high < temp → f temp sp latest = .On

/-- Goal: currentTemp below the band commands the fan Off. -/
def fanOff_when_cold_prop (f : Step) : Prop :=
  ∀ (temp : Int) (sp : SetPoint) (latest : FanCmd),
    sp.valid → temp < sp.low → f temp sp latest = .Off

/-- Goal: currentTemp inside the band holds the latest command. -/
def fanHold_in_band_prop (f : Step) : Prop :=
  ∀ (temp : Int) (sp : SetPoint) (latest : FanCmd),
    sp.low ≤ temp → temp ≤ sp.high → f temp sp latest = latest

/-- Goal (safety): the fan is only ever On because the temperature
    demands it or because it was already On. -/
def fanOn_only_if_hot_or_held_prop (f : Step) : Prop :=
  ∀ (temp : Int) (sp : SetPoint) (latest : FanCmd),
    f temp sp latest = .On → sp.high < temp ∨ latest = .On

/-- The blessed obligation: a sanctioned implementation satisfies every
    goal property. -/
def Spec (f : Step) : Prop :=
  fanOn_when_hot_prop f ∧ fanOff_when_cold_prop f ∧
  fanHold_in_band_prop f ∧ fanOn_only_if_hot_or_held_prop f

end TempControl
