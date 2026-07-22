# temp-control-jvm

Vendored copy of the HAMR **Temperature Control** tutorial example
(SAnToS Lab, KSU) — "Tutorial 00 (initial model)", Slang/JVM platform: a
temp sensor, cooling fan, and controller with GUMBO contracts, code-generated
to Slang by HAMR. This is the attested target system for the pybb gumbo
attestation examples and tests.

Provenance:

- HAMR docs walkthrough: https://hamr.sireum.org/hamr-doc/ch0X-hamr-sel4-tempControl-walkthrough.html
- SAnToS Lab: https://github.com/santoslab

Contents: `aadl/` (the AADL model with GUMBO contracts) and `slang/`
(HAMR-generated Slang/JVM project: bridges, components, GumboX oracles).
Build output (`slang/out/`) is not vendored; regenerate with the Sireum
tools (`sireum proyek ...`) as needed.

## Relation to the attested live tree

The protocol fixtures (`tests/fixtures/gumbo_*`) and the golden directory
(`golden/`) bake in absolute filepaths to the *live* target tree —
currently `~/Claude_workspace/temp-control-jvm`, which this directory is a
copy of. Adopting this copy as your live target means placing it at a path
of your choosing and re-provisioning: regenerating `asp_args.json`
filepaths, golden values, and the golden directory against that path.
