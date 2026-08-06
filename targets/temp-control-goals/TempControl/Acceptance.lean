/- BLESSED obligation binding: the live tree must prove exactly the
   blessed Spec for the sanctioned implementation. Fails to elaborate if
   spec_holds is missing, renamed, or has any weaker type. -/
import TempControl.Proofs

example : TempControl.Spec TempControl.computeFanCmd := TempControl.spec_holds
