/-
The implementation candidate — MUTABLE, never blessed: owned by the
workflow (or the developer). Its only attested properties are semantic:
the proofs in Proofs.lean must show it satisfies the blessed Spec
(Acceptance.lean), and the pinned binary must answer the behavior
vectors. Structural drift here is deliberately unmeasured.
-/
import TempControl.Props

namespace TempControl

instance : ToString FanCmd where
  toString
    | .On => "On"
    | .Off => "Off"

/-- The compute step: too hot → On, too cold → Off, in band → hold the
    latest command. Has type `Step` — the blessed interface shape. -/
def computeFanCmd (temp : Int) (sp : SetPoint) (latest : FanCmd) : FanCmd :=
  if temp > sp.high then .On
  else if temp < sp.low then .Off
  else latest

end TempControl
