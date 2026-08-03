# Isolette SysML v2 model

Vendored from loonwerks/INSPECTA-models `isolette/sysml/` (commit 4da74d7,
2026-07-02) — the SysML v2 frontend of the same system the `aadl/`
workspace models. The committed
`hamr/microkit/attestation/sysml_attestation_report.json` was generated
from these sources over the same implemented Microkit/Rust crates the
AADL report covers; the two reports differ only in where their
Model-kind slices live (.sysml vs .aadl).

Codegen (not needed for attestation; requires the santoslab
sysml-aadl-libraries pinned no newer than the Sireum release):

    sireum hamr sysml codegen -p Microkit --workspace-root-dir sysml \
        --sourcepath "sysml:<sysml-aadl-libraries>" \
        --system-name Isolette::Isolette_Single_Sensor sysml/Isolette.sysml
