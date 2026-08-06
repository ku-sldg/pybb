/-
Proofs — MUTABLE, never blessed: seed proofs the workflow may modify,
replace, or use as guidance, and where intermediate lemmas may be
introduced. A proof's only value is that it elaborates — the kernel
re-judges this file at every verification run, so proof bytes need no
integrity protection. The one obligation imposed from outside is
Acceptance.lean (blessed): `spec_holds : Spec computeFanCmd` must exist
with exactly that type.
-/
import TempControl.Impl

namespace TempControl

/-- Intermediate lemma introduced by the workflow. -/
theorem hot_means_not_cold (temp : Int) (sp : SetPoint)
    (hv : sp.valid) (h : sp.high < temp) : ¬ (temp < sp.low) := by
  obtain ⟨_, hlh, _⟩ := hv
  omega

theorem fanOn_when_hot : fanOn_when_hot_prop computeFanCmd := by
  unfold fanOn_when_hot_prop
  intro temp sp latest h
  unfold computeFanCmd
  split
  next => rfl
  next hn => exact absurd h hn

theorem fanOff_when_cold : fanOff_when_cold_prop computeFanCmd := by
  unfold fanOff_when_cold_prop
  intro temp sp latest hv h
  obtain ⟨_, hlh, _⟩ := hv
  have hnh : ¬ (sp.high < temp) := by omega
  simp [computeFanCmd, hnh, h]

theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd := by
  unfold fanHold_in_band_prop
  intro temp sp latest h1 h2
  have hnh : ¬ (sp.high < temp) := by omega
  have hnl : ¬ (temp < sp.low) := by omega
  simp [computeFanCmd, hnh, hnl]

theorem fanOn_only_if_hot_or_held :
    fanOn_only_if_hot_or_held_prop computeFanCmd := by
  unfold fanOn_only_if_hot_or_held_prop computeFanCmd
  intro temp sp latest
  split
  next hhot => exact fun _ => Or.inl hhot
  next =>
    split
    next => exact fun h => FanCmd.noConfusion h
    next => exact fun h => Or.inr h

/-- The acceptance witness: every blessed goal property holds of the
    implementation. Acceptance.lean (blessed) pins this name and type. -/
theorem spec_holds : Spec computeFanCmd := by
  unfold Spec
  exact ⟨fanOn_when_hot, fanOff_when_cold, fanHold_in_band,
         fanOn_only_if_hot_or_held⟩

-- Working material (kernel-evaluated sanity checks).
example : computeFanCmd 101 ⟨70, 90⟩ .Off = .On := by decide
example : computeFanCmd 60 ⟨70, 90⟩ .On = .Off := by decide
example : computeFanCmd 80 ⟨70, 90⟩ .On = .On := by decide

end TempControl
