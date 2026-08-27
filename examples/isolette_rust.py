"""
isolette_AADL_Rust / isolette_SysMLv2_Rust (selected by --frontend) —
attestation-driven blackboard demo for the isolette: the INSPECTA
seL4/Microkit exemplar (targets/isolette-microkit), with the HAMR
**attestation report** as the authoritative source of the measurement
targets and golden slices.

The target vendors BOTH model frontends over ONE implemented
Microkit/Rust tree: the AADL workspace (aadl/) and the SysML v2 model
(sysml/). HAMR emits an attestation report per frontend
(aadl_attestation_report.json / sysml_attestation_report.json) from the
same frontend-agnostic reporter; the reports differ only in where their
Model-kind slices live (.aadl vs .sysml) — the Verus/Rust realization
slices cover the same implemented crates. `--frontend` selects which
report drives the workflow; each frontend has its own protocol set
(isolette_aadl_rust_* / isolette_sysmlv2_rust_*) and blessing, so both baselines coexist.

Protocols (generated from the selected report, never hand-curated;
prefix isolette_aadl_rust_ for AADL, isolette_sysmlv2_rust_ for SysML):

    <p>_l1a    whole-file hashes of every file the report names
               (model files + contract-bearing Rust files)
    <p>_l2     readfile_range of every report slice: Model (GUMBO
               contracts in the model language) + Verus/Rust realizations
               in the generated crates
    <p>_verus  [--validate] cargo-verus verify of every contract-bearing
               crate (7): the generated Verus contracts must PROVE against
               the implemented behavior
    <p>_cheat  [--verify] proof-escape scan of the same crates: per-crate
               counts of assume/admit/external_body/axiom & friends vs an
               exact golden baseline — verification success is only
               trusted alongside HOW it was obtained
    <p>_gensrc [--verify] whole-file hashes of the GENERATED do-not-edit
               sources of the verification surface (bridge/GUMBOX/FFI
               glue + the foundation dep crates), one batched map per
               crate, l1a-owned files excluded; provisioning is gated by
               a byte-coverage completeness invariant. On failure the
               ladder diagnoses (drift kind, vs the same episode's cheat
               verdict) and [--regen-gensrc] repairs by regeneration
               through the measured codegen toolchain — never by rescue
    <p>_props  the administrator-blessed model files (whole-file, signed)

One trust question — <p>:files — since every l2 slice lives inside an
l1a-hashed file:

    eval <p>_l1a: pass = intact (readiness has already verified the
                  SIGNED golden baseline bundle)
      fail -> <p>_l2 refines (which contract slice, model or Verus)
                fail -> [--repair] WholeFileRestoreKS restores the
                        violated files from golden; episode 2 verifies

The props blessing is owned by the out-of-band attestation manager and
changes ONLY through --promote (or first-time bootstrap): an ordinary
--provision re-blesses measurements but keeps the existing model
blessing, so an unsanctioned model change followed by re-provisioning
leaves a stale blessing that baseline verification refutes.

Usage:
    python examples/isolette_rust.py [--frontend {aadl,sysml}]
        [--check] [--provision [--bless-props]] [--promote]
        [--ready] [--status] [--verify] [--validate]
        [--tamper-verus] [--tamper-note] [--tamper-impl]
        [--tamper-impl-full] [--tamper-report] [--tamper-report-subst]
        [--repair] [--immutable-model] [--repair-granularity {file,slice}]
        [--restore-crates] [--repair-impl] [--regen-report] [--pause]

--frontend   which model frontend's report drives the workflow
             (default: aadl — byte-identical to the pre-SysML behavior)
--check      attestation-manager detection: compare the model's contract
             content against the provisioned golden slices
--provision  (re)generate the protocol dirs from the attestation
             report, capture golden, and provision via the blackboard
             (creates the signed evidence bundles readiness verifies);
             the props blessing is kept, not re-signed
--promote    the sanctioned pipeline: tool gate (HAMR toolchain + for
             SysML the pinned sysml-aadl-libraries, measured immediately
             before use) -> REAL codegen in place (the report
             regenerates; SysML needs no OSATE) -> report-driven target
             regeneration -> gold moves -> full provisioning INCLUDING
             the props re-blessing -> a verification episode against the
             new baseline. Promotion NEVER verifies: blessing is
             authority; whether the impl meets the blessed spec is that
             episode's honest measurement (RED for a blessed-but-unmet
             spec)
--tamper-verus  corrupt a line inside a Verus contract slice of the
             generated Rust; detection/attribution (and --repair)
--tamper-cheat  admit a verified contract with assume(false) in a file
             no hash or slice tier covers: every other tier stays green,
             the verus tier still reports success, only the cheat tier
             refuses
--tamper-broadcast  plant a smuggled axiom (external_body broadcast proof
             fn, ensures false) in the shared GUMBO_Library: verifies
             clean and inert until `broadcast use`, so every outcome-based
             tier (files/contracts/verus/sysproof/report) stays green —
             only the cheat scan refuses, naming the crate
--tamper-stale-dep  flip a spec predicate in the shared GUMBO_Library
             with the file's mtime PRESERVED (nanosecond-exact): the
             foundation crates are verified only as cargo dependencies,
             and cargo's dep freshness is mtime-gated, so the warm cache
             serves the STALE pre-tamper artifact and every tier stays
             green — including the verus tier, whose primary crates
             genuinely re-verify but consume the cached dep. The scan
             counts no new construct (a semantic flip), no hash or slice
             tier covers the file. Pair with --fresh-deps for the guard
             that closes it
--validate   run the Verus semantic tier after a passing l1a
             (requires the Verus toolchain; cold builds are slow)

Demo-workflow flags (examples/demo_isolette.sh rides on these; see
docs/demo_isolette_script_summary.md for the scenes):

--bless-props        with --provision: the spec-first sanctioning act —
                     re-sign the props blessing over the current model
                     files, no codegen (--promote is the full pipeline)
--ready / --status   the readiness gate alone / the per-crate proof
                     checklist (a verus-tier run rendered downgrade-only;
                     tool-hash failures poison every cell to '?')
--verify             always-run verification + report-rendering entries
                     alongside the files entry (the three-entry shape)
--immutable-model    whole-file restore straight off the l1a verdict +
                     in-session re-attest (no interaction)
--repair-granularity file|slice — the restore rung's repair unit, with
                     in-session re-attest; slice = content-aligned splice
--restore-crates     the proofs entry's restore rung: failing crates'
                     hashed files from golden + in-session re-attest
--repair-impl        the ladder: contracts-intact diagnosis, then the
                     impl rung (crate restore), then re-attest
--regen-report       the report entry's repair rung: re-emit the report
                     via measured codegen (tool gate first)
--pause              the out-of-band rung: block on a work order, YOU
                     repair, fresh measurement judges the claim
--tamper-note        benign drift outside every measured slice
--tamper-impl        the exemplar's seeded bug (REQ-MHS-2 inverted)
--tamper-impl-full   the pre-generated dummy bad implementation
--tamper-report      delete one slice from the attestation report
--tamper-report-subst  substitute one slice's span for another's
--tamper-ffi         invert the heat command in the unverified FFI glue:
                     proofs pass, cheat counts clean — only the gensrc
                     byte tier refuses
--regen-gensrc       the gensrc entry's repair rung: re-emit the
                     generated sources via measured codegen (tool gate
                     first), then fresh measurement judges
--fresh-deps         the scene-scoped dependency-freshness guard: hash
                     the foundation crates' sources against a sidecar
                     record (trust-on-first-use seed) and bump mtimes on
                     content drift, so cargo-verus cannot serve a stale
                     dep verdict. Composes with --verify (guard runs
                     after tampers, before the episode); alone it just
                     seeds/checks the record and exits
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    OutOfBandRepairKS,
    ProtocolDir,
    RangeSliceRestoreKS,
    RestartEpisodeKS,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    Verdict,
    WholeFileRestoreKS,
    attestation_request,
    carry_goldens,
    changed_contracts,
    make_attestation_predicate,
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    promotion_request,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.proof_status import render_checklist
from pybb.attestation.snapshot import mirror_path
from pybb.attestation.verus_status import verus_crate_checklist
from pybb.blackboard import Blackboard
from pybb.knowledge_source import KnowledgeSource
from pybb.attestation.copland import with_asp_targids
from pybb.attestation.props import model_files_from_report, write_props_protocol_dir
from pybb.attestation.targetmap import (
    _marker_slug,
    build_term,
    derive_targets_from_report,
    marker_blocks,
    report_slices,
)
from pybb.attestation.tools import (
    build_tools_protocol_dir,
    make_tool_gate,
    register_tool,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
ISL_ROOT = REPO / "targets" / "isolette-microkit"
ATTESTATION_DIR = ISL_ROOT / "hamr" / "microkit" / "attestation"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
VERUS_ARGS = [
    "verify", "-Z", "build-std=core,alloc,compiler_builtins",
    "-Z", "build-std-features=compiler-builtins-mem",
    "--target", "aarch64-unknown-none", "--", "--output-json",
]

# The system-level compositional proof crate (HAMR-generated, report-
# invisible: the report is component-scoped and never names it, so every
# tier that covers it does so as an explicit AM-owned extra target).
# Host-target verify: a pure proof crate, nothing runs on the image.
SYS_PROOF_CRATE = "sys_nominal_proof"
SYS_PROOF_VERUS_ARGS = ["verify", "--", "--output-json"]

# Cheat-scan coverage beyond the report-derived component crates: the
# system proof crate plus the shared foundation crates a smuggled
# broadcast axiom would poison globally.
CHEAT_EXTRA_CRATES = ("GUMBO_Library", "data", SYS_PROOF_CRATE)


@dataclass(frozen=True)
class Frontend:
    """One model frontend: its report and the protocol namespace it owns."""

    name: str           # "aadl" | "sysml"
    prefix: str         # protocol-id prefix (isolette_aadl_rust_ / isolette_sysmlv2_rust_)
    model_suffix: str   # model-language extension (--check, props scope)
    model_label: str    # human phrase for the props blessing description
    # measure the report itself (hashed measure-then-use as its own
    # always-run entry under --verify): every protocol dir is derived
    # from the report, so targets bind to contracts only through its
    # structure — the rendering must be anchored before it is trusted
    report_protocol: bool = False

    @property
    def report(self) -> Path:
        return ATTESTATION_DIR / f"{self.name}_attestation_report.json"

    @property
    def report_id(self) -> str: return f"{self.prefix}_report"

    @property
    def l1a(self) -> str: return f"{self.prefix}_l1a"

    @property
    def l1b(self) -> str: return f"{self.prefix}_l1b"

    @property
    def l2(self) -> str: return f"{self.prefix}_l2"

    @property
    def props_id(self) -> str: return f"{self.prefix}_props"

    @property
    def verus_id(self) -> str: return f"{self.prefix}_verus"

    @property
    def cheat_id(self) -> str: return f"{self.prefix}_cheat"

    @property
    def sysproof_id(self) -> str: return f"{self.prefix}_sysproof"

    @property
    def gensrc_id(self) -> str: return f"{self.prefix}_gensrc"

    @property
    def protocol_ids(self) -> tuple: return (self.l1a, self.l1b, self.l2)


FRONTENDS = {
    "aadl": Frontend(name="aadl", prefix="isolette_aadl_rust", model_suffix=".aadl",
                     model_label="AADL model file"),
    "sysml": Frontend(name="sysml", prefix="isolette_sysmlv2_rust", model_suffix=".sysml",
                      model_label="SysML v2 model file", report_protocol=True),
}

# Just-in-time tool measurement: the verus toolchain is hashed in the
# same term as the verification, before the use (~21 ms); the HAMR
# toolchain — and, for the SysML frontend, the sysml-aadl-libraries the
# codegen elaborates against — is measured by the promotion gate right
# before codegen.
TOOL_CADENCE = "per_use"
HAMR_TOOLS_ID = "hamr_tools"
SYSML_LIBS_ID = "sysml_libs"
SYSML_LIBS_ROOT = Path.home() / "Claude_workspace" / "sysml-aadl-libraries"
SIREUM_STANDALONE = Path.home() / "Applications" / "Sireum" / "bin" / "sireum"

# The libraries are codegen INPUT, not toolchain — but a contract change
# laundered through a library edit is exactly what the promote gate must
# refuse, so they are measured like a tool: pinned clone, live hashes vs
# blessed goldens (measure-in-place). Keep the clone pinned no newer than
# the Sireum release (newer library commits crash older frontends).
register_tool(SYSML_LIBS_ID, lambda: sorted(
    str(p) for p in SYSML_LIBS_ROOT.rglob("*.sysml")))

# per-frontend promote configuration: which tools protocols gate codegen
TOOL_GATE_IDS = {
    "aadl": (HAMR_TOOLS_ID,),
    "sysml": (HAMR_TOOLS_ID, SYSML_LIBS_ID),
}


def _sireum_env() -> dict:
    return {**os.environ,
            "SIREUM_CACHE": str(Path.home() / "Claude_workspace/.sireum_cache")}


def sysml_codegen() -> str:
    """Real SysML v2 codegen, in place: one CLI call, no OSATE/phantom.
    Regenerates the Microkit tree AND sysml_attestation_report.json at
    the vendored target; developer-owned app.rs files are never
    re-spliced (HAMR contract)."""
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE}")
    if not SYSML_LIBS_ROOT.is_dir():
        raise RuntimeError(
            f"sysml-aadl-libraries not found at {SYSML_LIBS_ROOT} — clone "
            "santoslab/sysml-aadl-libraries and PIN it no newer than the "
            "Sireum release")
    sysml_dir = ISL_ROOT / "sysml"
    subprocess.run(
        [str(SIREUM_STANDALONE), "hamr", "sysml", "codegen",
         "--package-name", "isolette",
         "--platform", "Microkit",
         "--runtime-monitoring",
         "--no-proyek-ive",
         "--workspace-root-dir", str(sysml_dir),
         "--sourcepath", f"{sysml_dir}:{SYSML_LIBS_ROOT}",
         "--system-name", "Isolette::Isolette_Single_Sensor",
         "--output-dir", str(ISL_ROOT / "hamr"),
         "--sel4-output-dir", str(ISL_ROOT / "hamr" / "microkit"),
         str(sysml_dir / "Isolette.sysml")],
        check=True, env=_sireum_env(), cwd=sysml_dir)
    return ("ran: sireum hamr sysml codegen -p Microkit "
            "(report regenerated in place)")


def aadl_codegen() -> str:
    """Real AADL codegen: phantom (AADL -> AIR via headless OSATE) then
    codegen -p Microkit, regenerating the tree and
    aadl_attestation_report.json in place. Wired for parity with the
    SysML frontend; its first in-place run is a supervised baseline
    migration (toolchain drift since INSPECTA generated the vendored
    tree) that has not been exercised yet."""
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE}")
    aadl_ws = ISL_ROOT / "aadl"
    with tempfile.TemporaryDirectory(prefix="pybb_air_") as tmp:
        air = Path(tmp) / "Isolette.json"
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "phantom",
                        "-f", str(air), str(aadl_ws)],
                       check=True, env=_sireum_env())
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "codegen",
                        "-p", "Microkit",
                        "--package-name", "isolette",
                        "--runtime-monitoring",
                        "--workspace-root-dir", str(aadl_ws),
                        "--output-dir", str(ISL_ROOT / "hamr"),
                        "--sel4-output-dir", str(ISL_ROOT / "hamr" / "microkit"),
                        str(air)],
                       check=True, env=_sireum_env())
    return ("ran: sireum hamr phantom + codegen -p Microkit "
            "(report regenerated in place)")


CODEGEN = {"aadl": aadl_codegen, "sysml": sysml_codegen}


def derive_report_targets(fe: Frontend):
    """The report is the authority on targets and golden slices."""
    return derive_targets_from_report(fe.report, prefix=fe.prefix)


def _write_asp_args(d: Path, asp_args: dict, no_golden: tuple = ()) -> None:
    """Write a regenerated asp_args.json, carrying existing golden
    bookkeeping forward for unchanged targets: regeneration composed
    with idempotent re-provisioning leaves an unchanged system
    byte-identical. `no_golden` names ASP ids that are NOT golden
    companions (e.g. run_command_cargo_verus under errors==0 appraisal):
    any golden bookkeeping carried onto their targets is stripped, so a
    non-companion never accumulates stale goldens."""
    path = d / "asp_args.json"
    if path.is_file():
        asp_args = carry_goldens(json.loads(path.read_text()), asp_args)
    for asp_id in no_golden:
        for args in asp_args.get(asp_id, {}).values():
            args.pop("golden_b64", None)
            args.pop("golden_ts", None)
    path.write_text(json.dumps(asp_args, indent=2) + "\n")


def verus_crates(fe: Frontend) -> list:
    """Contract-bearing crates, from the report's Verus/Rust slices."""
    crates = set()
    for s in report_slices(fe.report):
        if s["kind"] in ("Verus", "Rust") and "/crates/" in s["filepath"]:
            crates.add(s["filepath"].split("/crates/")[1].split("/")[0])
    return sorted(crates)


def build_verus_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_verus: report-derived crate list, temp_control_aadl_rust_verus session/manifest,
    verus toolchain measurements woven in per TOOL_CADENCE."""
    d = FIXTURES / fe.verus_id
    d.mkdir(exist_ok=True)
    crate_args = {
        f"{fe.prefix}_{crate}_verus_targ": {
            "exe_args": VERUS_ARGS,
            "cwd": str(ISL_ROOT / "hamr" / "microkit" / "crates" / crate),
        }
        for crate in verus_crates(fe)
    }
    # the system proof crate: report-invisible, added explicitly
    crate_args[f"{fe.prefix}_{SYS_PROOF_CRATE}_verus_targ"] = {
        "exe_args": SYS_PROOF_VERUS_ARGS,
        "cwd": str(ISL_ROOT / "hamr" / "microkit" / "crates" / SYS_PROOF_CRATE),
    }
    targets = with_asp_targids(crate_args)
    asp_args = {"run_command_cargo_verus": targets}
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "run_command_cargo_verus",
                         "ASP_TARG_ID": targ, "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        acc, {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    session = json.loads((FIXTURES / "temp_control_aadl_rust_verus" / "session.json").read_text())
    manifest = json.loads((FIXTURES / "temp_control_aadl_rust_verus" / "manifest.json").read_text())
    # correctness appraisal (errors == 0, run_command_verus_appr from the
    # template session): the tier judges whether the implementation
    # PROVES against the blessed contracts, honestly RED for a
    # blessed-but-unmet spec. Deliberately NOT a golden comparison — a
    # broken-spec promotion must not capture failing results as the
    # golden and then match them (a golden of failure attests green).
    # Surface-shrink at errors==0 is the hash tiers' job: sysproof for
    # the proof crate, l1a + the contract-file hashes for components.
    n_tools = 0
    if TOOL_CADENCE == "per_use":
        asp_args, term, session, manifest = weave_tool_measurements(
            asp_args, term, session, manifest)
        n_tools = len(asp_args.get("hashfile", {}))
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_asp_args(d, asp_args, no_golden=("run_command_cargo_verus",))
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette Verus Verification (semantic tier)",
        "description": "cargo-verus verify over every contract-bearing "
                       "isolette crate (report-derived) plus the system-level "
                       "proof crate: the generated Verus contracts must PROVE "
                       "against the implemented behavior (errors == 0 — "
                       "honestly RED for a blessed-but-unmet spec; "
                       "surface-shrink at errors==0 is the hash tiers' job). "
                       "The verus toolchain is hashed in the same term, "
                       "before the invocations (measure-then-use).",
        "copland": f"lseq( bseq( run_command_cargo_verus×{len(targets)} ), APPR )",
    }, indent=2) + "\n")
    print(f"  {fe.verus_id}: {len(targets)} crates from report"
          + (f" + {n_tools} woven tool measurements" if n_tools else ""))
    return ProtocolDir.load(str(d))


def build_cheat_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_cheat: the proof-ESCAPE surface of every contract-bearing
    crate. The verus tier witnesses that the proofs went through; this
    tier measures HOW — per-crate counts of assume/admit/external_body
    (by path class)/bare-external/assume_specification/axiom/broadcast,
    as canonical JSON from cheat_scan_verus, appraised by exact golden
    comparison (goldenbytes_appr). A proof admitted with assume(false)
    leaves every other tier green — verification still reports success —
    and shifts a count here."""
    d = FIXTURES / fe.cheat_id
    d.mkdir(exist_ok=True)
    targets = with_asp_targids({
        f"{fe.prefix}_{crate}_cheat_targ": {
            "crate_dir": str(ISL_ROOT / "hamr" / "microkit" / "crates" / crate),
        }
        for crate in sorted({*verus_crates(fe), *CHEAT_EXTRA_CRATES})
    })
    asp_args = {"cheat_scan_verus": targets}
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "cheat_scan_verus",
                         "ASP_TARG_ID": targ, "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            acc,
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]},
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": {
                "cheat_scan_verus": {
                    "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                    "ATTRS": []},
                "sig": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"},
                        "ATTRS": []},
                "sig_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
                "goldenbytes_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1},
                                     "ATTRS": []},
            },
            "ASP_Comps": {"cheat_scan_verus": "goldenbytes_appr",
                          "sig": "sig_appr"},
        },
    }
    manifest = {"ASPS": ["cheat_scan_verus", "goldenbytes_appr", "sig",
                         "sig_appr"],
                "ASP_FS_MAP": {}, "POLICY": []}
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_asp_args(d, asp_args)
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette Verus proof-escape scan (cheat tier)",
        "description": "Per-crate counts of the constructs that make Verus "
                       "verification succeed without proof (assume, admit, "
                       "external_body by path class, bare external, "
                       "assume_specification, axiom, broadcast), appraised "
                       "as exact golden bytes. Complements the verus tier: "
                       "that one witnesses THAT the proofs pass, this one "
                       "measures HOW.",
        "copland": f"lseq( lseq( bseq( cheat_scan_verus×{len(targets)} ), "
                   "SIG ), APPR )",
    }, indent=2) + "\n")
    print(f"  {fe.cheat_id}: {len(targets)} crates scanned for proof escapes")
    return ProtocolDir.load(str(d))


def build_sysproof_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_sysproof: whole-file hashes of the system-level proof crate,
    batched into ONE hashfile_many evidence blob. The report is
    component-scoped and never names sys_nominal_proof, so this is an
    AM-owned extra tier (the tools-protocol pattern), not a report
    derivation. Whole-file with NO benign-drift allowance is correct:
    every file is do-not-edit generated, so any byte change is either a
    sanctioned HAMR re-run (promote path) or tampering. This is the
    layer that stops drop-one-add-trivial — deleting a real VC and
    adding a dummy preserves the verified count, but not the bytes.

    Batched, not per-file: 124 hashfile targets made a 123-deep bseq
    chain whose CVM cost is superlinear in chain length (~30s per
    appraisal pass); one hashfile_many node hashes the same files into a
    single canonical {relpath: sha256} map (~0.1s), the walk catches
    ADDED files per-target lists cannot see, and the appraiser names
    every drifted/missing/added path so attribution survives."""
    d = FIXTURES / fe.sysproof_id
    d.mkdir(exist_ok=True)
    crate = ISL_ROOT / "hamr" / "microkit" / "crates" / SYS_PROOF_CRATE
    targ = f"{fe.prefix}_sysproof_crate_targ"
    targets = with_asp_targids({
        targ: {
            "root": str(crate),
            "files": ["Cargo.toml", "rust-toolchain.toml"],
            "walk_dirs": ["src"],
        }
    })
    asp_args = {"hashfile_many": targets}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                "ASP_CONSTRUCTOR": "ASPC",
                "ASP_BODY": {"ASP_ID": "hashfile_many", "ASP_TARG_ID": targ,
                             "ASP_ARGS": targets[targ]}}},
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]},
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": {
                "hashfile_many": {"FWD": {"FWD": "EXTEND", "_BODY": 1,
                                          "EvInSig": "NONE"}, "ATTRS": []},
                "sig": {"FWD": {"FWD": "EXTEND", "_BODY": 1,
                                "EvInSig": "ALL"}, "ATTRS": []},
                "sig_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1},
                             "ATTRS": []},
                "hashfile_many_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1},
                                       "ATTRS": []},
            },
            "ASP_Comps": {"hashfile_many": "hashfile_many_appr",
                          "sig": "sig_appr"},
        },
    }
    manifest = {"ASPS": ["hashfile_many", "hashfile_many_appr", "sig",
                         "sig_appr"],
                "ASP_FS_MAP": {}, "POLICY": []}
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_asp_args(d, asp_args)
    (d / "term.json").write_text(json.dumps(term) + "\n")
    n_files = len(list((crate / "src").rglob("*.rs"))) + 2
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette system-proof crate integrity (sysproof tier)",
        "description": "Whole-file hashes of every source of "
                       "sys_nominal_proof — the HAMR-generated system-level "
                       "compositional proof (one empty-bodied VC per "
                       "obligation, discharged by Verus) — batched into one "
                       "canonical relpath->sha256 evidence map. "
                       "Report-invisible, so covered as an AM-owned extra "
                       "tier. Catches surface-shrink the Verus tier "
                       "(errors==0) cannot see: dropping a real VC — or "
                       "dropping one and adding a trivial one — leaves the "
                       "crate verifying but changes the bytes; the appraiser "
                       "names every drifted, missing, and added file.",
        "copland": f"lseq( lseq( hashfile_many({n_files} files), SIG ), "
                   "APPR )",
    }, indent=2) + "\n")
    print(f"  {fe.sysproof_id}: {n_files} proof-crate files hashed "
          "(1 batched target)")
    return ProtocolDir.load(str(d))


# The gensrc tier's scope: the verification surface — every crate the
# verus tier verifies as a primary target (report-derived component
# crates) plus the foundation crates it consumes as cargo dependencies.
# sys_nominal_proof has its own tier; domain_monitor and the dmf crate
# are NOT verified by the verus tier, so they belong to the postponed
# executable artifact class, not here.
GENSRC_EXECUTABLE_CLASS = ("domain_monitor", "thermostat_mt_dmf_dmf",
                           "thermostat_rt_drf_drf")


def _gensrc_crates(fe: Frontend) -> list:
    return sorted({*verus_crates(fe), *DEP_CRATES})


def _l1a_files_by_crate(fe: Frontend) -> dict:
    """l1a-hashed files under crates/, as {crate: [relpath-in-crate]} —
    the files another tier OWNS (developer-owned app.rs under the l2
    slice-rescue regime, plus the report-named api.rs files), which the
    gensrc walk must exclude so their semantics stay theirs."""
    l1a = json.loads((FIXTURES / fe.l1a / "asp_args.json").read_text())
    out: dict = {}
    for a in l1a["hashfile"].values():
        fp = a["filepath"]
        if "/crates/" not in fp:
            continue
        crate, rel = fp.split("/crates/")[1].split("/", 1)
        out.setdefault(crate, []).append(rel)
    return {c: sorted(rels) for c, rels in out.items()}


def check_gensrc_coverage(fe: Frontend) -> None:
    """The byte-coverage completeness invariant, checked at provisioning:
    every .rs file in the verification surface is covered by exactly one
    byte tier — l1a (report-named, developer-relevant), gensrc (the
    generated complement), or sysproof — and the exclusion list matches
    the l1a coverage exactly. A codegen version that emits a new file
    outside the walked dirs, or the report un-naming a file the
    exclusions still list, fails provisioning loudly instead of
    silently reopening the scene 9/11 coverage hole."""
    crates_root = ISL_ROOT / "hamr" / "microkit" / "crates"
    excluded = _l1a_files_by_crate(fe)
    problems = []
    covered_crates = set(_gensrc_crates(fe)) | {SYS_PROOF_CRATE}
    for crate_dir in sorted(p for p in crates_root.iterdir() if p.is_dir()):
        crate = crate_dir.name
        if crate not in covered_crates:
            if crate not in GENSRC_EXECUTABLE_CLASS:
                problems.append(
                    f"crate {crate} is in no byte tier and not a known "
                    "executable-class crate")
            continue
        for f in sorted(crate_dir.rglob("*.rs")):
            if "target" in f.relative_to(crate_dir).parts:
                continue
            rel = str(f.relative_to(crate_dir)).replace("\\", "/")
            in_walk = rel.startswith("src/")
            if crate == SYS_PROOF_CRATE:
                if not in_walk:
                    problems.append(f"{crate}/{rel}: outside the sysproof walk")
            elif rel in excluded.get(crate, []):
                pass  # l1a owns it (and l2 refines it where sliced)
            elif not in_walk:
                problems.append(f"{crate}/{rel}: outside the gensrc walk")
    for crate, rels in excluded.items():
        for rel in rels:
            if not (crates_root / crate / rel).is_file():
                problems.append(
                    f"stale exclusion: {crate}/{rel} is l1a-listed but absent")
    if problems:
        raise SystemExit(
            "byte-coverage completeness check FAILED:\n  "
            + "\n  ".join(problems))
    print("  byte-coverage completeness: every verification-surface .rs "
          "is covered (l1a / gensrc / sysproof)")


def build_gensrc_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_gensrc: whole-file hashes of the GENERATED sources of the
    verification surface — the do-not-edit complement of the l1a tier.
    One hashfile_many batch per crate (component crates + the foundation
    dep crates), walking src/ with the l1a-covered files EXCLUDED so
    developer-owned app.rs keeps its l2 slice-rescue semantics and the
    report-named api.rs files keep theirs.

    Whole-file with NO benign-drift allowance, like the sysproof tier:
    every covered file is codegen-emitted, so any byte change is either
    a sanctioned HAMR re-run (promote) or tampering. This closes scene
    9's coverage hole (the admit site, the smuggle site) and scene 11's
    (the stale-dep flip) at the byte layer; the cheat scan stays
    always-run because it alone guards the promote boundary, where gold
    legitimately moves and byte-blessing would bless whatever codegen
    emitted. On failure the ladder DIAGNOSES (drift characterization
    against the same episode's cheat verdict) and — opt-in — REPAIRS by
    regeneration (scene 8's species: these files are renderings of the
    model through the measured toolchain), never by rescue: a
    cheat-clean drift can still be a weakened contract."""
    d = FIXTURES / fe.gensrc_id
    d.mkdir(exist_ok=True)
    excluded = _l1a_files_by_crate(fe)
    targets = with_asp_targids({
        f"{fe.prefix}_{crate}_gensrc_targ": {
            "root": str(ISL_ROOT / "hamr" / "microkit" / "crates" / crate),
            "files": ["Cargo.toml", "rust-toolchain.toml"],
            "walk_dirs": ["src"],
            **({"exclude": excluded[crate]} if crate in excluded else {}),
        }
        for crate in _gensrc_crates(fe)
    })
    asp_args = {"hashfile_many": targets}
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "hashfile_many",
                         "ASP_TARG_ID": targ, "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            acc,
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]},
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": {
                "hashfile_many": {"FWD": {"FWD": "EXTEND", "_BODY": 1,
                                          "EvInSig": "NONE"}, "ATTRS": []},
                "sig": {"FWD": {"FWD": "EXTEND", "_BODY": 1,
                                "EvInSig": "ALL"}, "ATTRS": []},
                "sig_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1},
                             "ATTRS": []},
                "hashfile_many_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1},
                                       "ATTRS": []},
            },
            "ASP_Comps": {"hashfile_many": "hashfile_many_appr",
                          "sig": "sig_appr"},
        },
    }
    manifest = {"ASPS": ["hashfile_many", "hashfile_many_appr", "sig",
                         "sig_appr"],
                "ASP_FS_MAP": {}, "POLICY": []}
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_asp_args(d, asp_args)
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    n_excluded = sum(len(v) for v in excluded.values())
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette generated-source integrity (gensrc tier)",
        "description": "Whole-file hashes of the generated do-not-edit "
                       "Rust of the verification surface — bridge, GUMBOX, "
                       "extern_c_api, mod/lib/logging, generated test "
                       "scaffolding, and the foundation dep crates — one "
                       "batched relpath->sha256 map per crate, with the "
                       "l1a-owned files excluded so developer-owned code "
                       "keeps its slice-rescue semantics. Closes the "
                       "byte-coverage hole the cheat and stale-dep scenes "
                       "exploited; no benign-drift allowance, repair is "
                       "regeneration via measured codegen or escalation.",
        "copland": f"lseq( lseq( bseq( hashfile_many×{len(targets)} ), "
                   "SIG ), APPR )",
    }, indent=2) + "\n")
    print(f"  {fe.gensrc_id}: {len(targets)} crates walked "
          f"({n_excluded} l1a-owned files excluded)")
    return ProtocolDir.load(str(d))


def build_report_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_report: one hashfile measurement of the attestation report,
    goldenbytes-appraised against its provisioned golden hash — the
    measure-then-use anchor on the rendering every protocol dir is
    derived from. The report is a plain (golden-copied) target, so scene
    tampers self-clean at driver exit like any other; its REPAIR species
    is regeneration (re-emit via measured codegen), never hand-editing."""
    d = FIXTURES / fe.report_id
    d.mkdir(exist_ok=True)
    targ = f"{fe.prefix}_report_targ"
    targets = {targ: {"filepath": str(fe.report), "env_var": "",
                      "asp_targid": targ}}
    hashfile_types = {
        "hashfile": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                     "ATTRS": []},
        "sig": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"}, "ATTRS": []},
        "sig_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
        "goldenbytes_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
    }
    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": hashfile_types,
            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr"},
        },
    }
    manifest = {"ASPS": ["hashfile", "goldenbytes_appr", "sig", "sig_appr"],
                "ASP_FS_MAP": {}, "POLICY": []}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                "ASP_CONSTRUCTOR": "ASPC",
                "ASP_BODY": {"ASP_ID": "hashfile", "ASP_TARG_ID": targ}}},
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]},
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    _write_asp_args(d, {"hashfile": targets})
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette attestation-report rendering",
        "description": "Whole-file hash of the HAMR attestation report — the "
                       "authority every protocol dir is derived from. "
                       "Measurement targets bind to contracts only through "
                       "the report's structure, so the rendering itself is "
                       "anchored measure-then-use before it is trusted. "
                       "Repair species: regeneration via measured codegen.",
        "copland": "lseq( lseq( hashfile(report), SIG ), APPR )",
    }, indent=2) + "\n")
    return ProtocolDir.load(str(d))


def derive_l1b_targets(l1a_args: dict) -> dict:
    """<p>_l1b: the codegen-managed BEGIN/END MARKER contract blocks of
    every l1a-hashed contract-bearing .rs file, measured whole-block via
    marker anchors (insertion-robust; readfile_marker_range). The
    coverage backstop for the report's contract slices: the report emits
    Verus-realization slices for initialize/general clauses but NONE for
    compute_cases realizations, so contract drift can land between the
    report's slices — every marker-region byte is measured here
    regardless of what the report names."""
    targs = {}
    for a in l1a_args["hashfile"].values():
        fp = a["filepath"]
        if not fp.endswith(".rs"):
            continue
        stem = Path(fp).stem.lower()
        for begin, end in marker_blocks(Path(fp).read_text()):
            targ = f"{stem}_{_marker_slug(begin)}_targ"
            n = 2
            while targ in targs:
                targ = f"{stem}_{_marker_slug(begin)}_{n}_targ"
                n += 1
            targs[targ] = {"filepath": fp,
                           "begin_marker": begin, "end_marker": end}
    return {"readfile_marker_range": with_asp_targids(targs)}


def _marker_line_spans(text: str) -> list:
    """1-based inclusive line spans of every BEGIN/END MARKER block."""
    lines = text.splitlines()
    spans = []
    open_at = None
    for i, ln in enumerate(lines, start=1):
        stripped = ln.strip().removeprefix("//").strip()
        if stripped.startswith("BEGIN MARKER"):
            open_at = i
        elif stripped.startswith("END MARKER") and open_at is not None:
            spans.append((open_at, i))
            open_at = None
    return spans


def lint_marker_coverage(l1a_args: dict, l2_args: dict,
                         l1b_args: dict) -> None:
    """Provision-time coverage lint (the analogue of the gensrc
    byte-coverage invariant, for contract-bearing developer-owned .rs
    files): every such file must carry marker blocks — measured whole by
    the l1b tier — and every report contract slice on it must live
    INSIDE a marker block. Refuses loudly on a contract-bearing file
    with no marker coverage; reports the residual (marker lines the
    report does not slice — covered only by l1b)."""
    rs_slices = {}
    for t in l2_args["readfile_range"].values():
        if t["filepath"].endswith(".rs"):
            rs_slices.setdefault(t["filepath"], []).append(
                (t["start_index"], t["end_index"]))
    marker_files = {}
    for t in l1b_args["readfile_marker_range"].values():
        marker_files.setdefault(t["filepath"], 0)
        marker_files[t["filepath"]] += 1
    residual = 0
    wholefile = []
    for fp, spans in rs_slices.items():
        blocks = _marker_line_spans(Path(fp).read_text())
        if not blocks:
            # a fully-generated file (e.g. a bridge api.rs): no
            # developer-owned region exists, so there are no markers —
            # its coverage is whole-file l1a semantics, not l1b
            wholefile.append(Path(fp).name)
            continue
        for (a, b) in spans:
            if not any(ba <= a and b <= bb for ba, bb in blocks):
                raise SystemExit(
                    f"marker-coverage lint: report slice {a}-{b} of "
                    f"{Path(fp).name} lies OUTSIDE every marker block — "
                    "the slice would be unrepairable by the marker rung; "
                    "refusing to provision")
        sliced = sum(b - a + 1 for a, b in spans)
        marked = sum(b - a + 1 for a, b in blocks)
        residual += max(0, marked - sliced)
    print(f"  marker-coverage lint: {sum(marker_files.values())} marker "
          f"blocks over {len(marker_files)} contract-bearing .rs files; "
          f"~{residual} marker lines carry NO report slice (the "
          "compute_cases realization hole) — covered by the l1b tier"
          + (f"; fully-generated (whole-file semantics, no markers): "
             f"{', '.join(sorted(wholefile))}" if wholefile else ""))


def build_protocol_dirs(fe: Frontend, bless_props: bool = False) -> dict:
    """(Re)generate the frontend's protocol dirs from its report. The
    props definition is AM-owned: rewritten only under --promote
    (bless_props) or when missing entirely (bootstrap) — an ordinary
    --provision keeps the existing blessing untouched."""
    derived = derive_report_targets(fe)
    protocols = {}
    for pid, asp_args in derived.items():
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        template = "temp_control_aadl_slang_l1a" if pid.endswith("_l1a") else "temp_control_aadl_slang_l2"
        for f in ("session.json", "manifest.json"):
            shutil.copy2(FIXTURES / template / f, d / f)
        _write_asp_args(d, asp_args)
        (d / "term.json").write_text(json.dumps(build_term(asp_args)) + "\n")
        protocols[pid] = ProtocolDir.load(str(d))
        print(f"  {pid}: {sum(len(t) for t in asp_args.values())} targets from report")
    # l1b: marker-block contract coverage (backstop for the report's
    # slice emission — see derive_l1b_targets)
    l1b_args = derive_l1b_targets(derived[fe.l1a])
    d = FIXTURES / fe.l1b
    d.mkdir(exist_ok=True)
    for f in ("session.json", "manifest.json"):
        shutil.copy2(FIXTURES / "temp_control_aadl_slang_l1b" / f, d / f)
    _write_asp_args(d, l1b_args)
    (d / "term.json").write_text(json.dumps(build_term(l1b_args)) + "\n")
    protocols[fe.l1b] = ProtocolDir.load(str(d))
    print(f"  {fe.l1b}: "
          f"{len(l1b_args['readfile_marker_range'])} marker blocks")
    lint_marker_coverage(derived[fe.l1a], derived[fe.l2], l1b_args)
    props_dir = FIXTURES / fe.props_id
    if bless_props or not (props_dir / "asp_args.json").is_file():
        # props scope = every file the report classifies as Model-kind —
        # the report is the authority, not the file extension (both
        # reports place one Model-classified Verus spec fn in a generated
        # app.rs; the committed AADL blessing has always covered it)
        model_files = model_files_from_report(fe.report)
        write_props_protocol_dir(
            props_dir, fe.prefix, model_files,
            "The administrator-blessed golden spec: whole-file signed evidence "
            f"of every {fe.model_label} the report's GUMBO contract (Model) "
            "slices live in. Baseline verification checks that all hash and "
            "slice goldens are derivable from the blessed content.")
        print(f"  {fe.props_id}: {len(model_files)} blessed model files")
    else:
        print(f"  {fe.props_id}: existing blessing kept "
              "(only --promote re-blesses the model)")
    protocols[fe.props_id] = ProtocolDir.load(str(props_dir))
    if fe.report_protocol:
        protocols[fe.report_id] = build_report_protocol(fe)
        print(f"  {fe.report_id}: 1 report rendering target")
    protocols[fe.verus_id] = build_verus_protocol(fe)
    protocols[fe.cheat_id] = build_cheat_protocol(fe)
    protocols[fe.sysproof_id] = build_sysproof_protocol(fe)
    protocols[fe.gensrc_id] = build_gensrc_protocol(fe)
    build_tools_protocol_dir(
        FIXTURES / HAMR_TOOLS_ID, "hamr", ["hamr"],
        "The HAMR codegen + report-emitter toolchain (sireum.jar + the "
        "org.sireum OSATE plugins): measured in place at blessing, and "
        "re-measured by the promotion gate immediately before codegen.")
    protocols[HAMR_TOOLS_ID] = ProtocolDir.load(str(FIXTURES / HAMR_TOOLS_ID))
    print(f"  {HAMR_TOOLS_ID}: "
          f"{len(protocols[HAMR_TOOLS_ID].asp_args['hashfile'])} tool artifacts")
    if fe.name == "sysml":
        build_tools_protocol_dir(
            FIXTURES / SYSML_LIBS_ID, "sysml", [SYSML_LIBS_ID],
            "The SysMLv2 AADL libraries the codegen elaborates against "
            "(pinned clone): codegen INPUT measured like a tool — a "
            "contract change laundered through a library edit must fail "
            "the promotion gate's live hashes against these blessed "
            "goldens.")
        protocols[SYSML_LIBS_ID] = ProtocolDir.load(str(FIXTURES / SYSML_LIBS_ID))
        print(f"  {SYSML_LIBS_ID}: "
              f"{len(protocols[SYSML_LIBS_ID].asp_args['hashfile'])} library files")
    return protocols


def load_protocols(fe: Frontend, validate: bool = False) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in (*fe.protocol_ids, fe.props_id)):
        print(f"{fe.prefix} protocol dirs missing — generating from the "
              "attestation report")
        protocols = build_protocol_dirs(fe)
    else:
        protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
                     for pid in (*fe.protocol_ids, fe.props_id)}
        if fe.report_protocol:
            if not (FIXTURES / fe.report_id / "asp_args.json").is_file():
                build_report_protocol(fe)
            protocols[fe.report_id] = ProtocolDir.load(
                str(FIXTURES / fe.report_id))
    if validate:
        protocols[fe.verus_id] = ProtocolDir.load(str(FIXTURES / fe.verus_id))
        for pid, build in ((fe.cheat_id, build_cheat_protocol),
                           (fe.sysproof_id, build_sysproof_protocol),
                           (fe.gensrc_id, build_gensrc_protocol)):
            if not (FIXTURES / pid / "asp_args.json").is_file():
                build(fe)
            protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    return protocols


def provision_flow(fe: Frontend, protocols: dict,
                   bless_props: bool = False,
                   force_timestamp: bool = False) -> None:
    """Capture golden and provision the report-derived goldens on the
    blackboard (the provisioning run signs each evidence bundle; tool
    hash goldens land measure-in-place). The props blessing is
    provisioned ONLY under --promote (bless_props) or when it has never
    been blessed (bootstrap): re-signing the model files is the
    administrator's sanctioning act, so ordinary re-provisioning —
    including a laundering pass — cannot refresh it."""
    props = protocols.get(fe.props_id)
    props_unblessed = props is not None and not any(
        a.get("golden_b64")
        for a in props.asp_args.get("readfile", {}).values())
    pids = list(fe.protocol_ids)
    if props is not None and (bless_props or props_unblessed):
        pids.append(fe.props_id)
    if fe.report_id in protocols:
        pids.append(fe.report_id)
    if fe.cheat_id in protocols:
        pids.append(fe.cheat_id)
    if fe.sysproof_id in protocols:
        pids.append(fe.sysproof_id)
    if fe.gensrc_id in protocols:
        # the byte-coverage completeness invariant gates provisioning:
        # a new uncovered file (codegen drift) or a stale exclusion
        # refuses loudly before any golden is captured
        check_gensrc_coverage(fe)
        pids.append(fe.gensrc_id)
    measured = {pid: protocols[pid] for pid in pids}
    for pid in (fe.verus_id, HAMR_TOOLS_ID, SYSML_LIBS_ID):
        if pid in protocols and "hashfile" in protocols[pid].asp_args:
            measured[pid] = protocols[pid]
    snapshot = TargetSnapshot.capture(measured, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files")
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, measured, GOLDEN_ROOT))
    for pid in measured:
        request_provision(ctl.blackboard, pid, force_timestamp=force_timestamp)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")


def _combined_tool_gate(client, protocols: dict, tool_ids: tuple):
    """One gate over several tools protocols (toolchain + codegen
    inputs): first drift refuses."""
    gates = [(tid, make_tool_gate(client, protocols[tid]))
             for tid in tool_ids if tid in protocols]

    def gate():
        for _, g in gates:
            error = g()
            if error:
                return error
        return None

    return gate


def print_check(fe: Frontend, protocols: dict) -> list:
    changed = changed_contracts(protocols[fe.l2], model_suffix=fe.model_suffix)
    if changed:
        print("HAMR codegen needed — model contracts changed since "
              "last provisioning:")
        for targ in changed:
            print(f"  {targ}")
    else:
        print("No model contract changes since last provisioning; "
              "codegen not needed.")
    return changed


def promote_flow(fe: Frontend, protocols: dict) -> None:
    """
    The sanctioning act, in pipeline order:

      1. detection report (informational — what is being sanctioned)
      2. promotion request alone on the blackboard; its predicate runs
         the gates and moves gold: tool gate (HAMR toolchain, and for
         SysML the pinned libraries, measured immediately before use) ->
         real codegen IN PLACE (the report regenerates — the one step
         re-provisioning alone can never do) -> report-driven target
         regeneration -> golden capture. NO verification: blessing is
         the administrator's authority act; whether the implementation
         proves against the blessed spec is the next episode's honest
         measurement, not a precondition of gold moving
      3. only after the promote outcome is good: rebuild the AM-owned
         dirs from the NEW report (props blessing definition, verus
         crate list) and provision everything, props included — the
         re-blessing
      4. verification episode against the new baseline — where a
         blessed-but-unmet spec shows a RED verification tier until the
         implementation catches up

    Steps 2 and 3 are deliberately two blackboard runs: a refused gate
    (tool drift, failed codegen) must leave the old baseline fully in
    place, so no provision request exists until the promotion outcome is
    known good.
    """
    print("=== sanction review (contract diff) ===")
    print_check(fe, protocols)

    print("\n=== promotion episode (gates, then gold moves) ===")
    client = CvmSubprocessClient()
    gated = {pid: protocols[pid]
             for pid in (*fe.protocol_ids, fe.props_id, fe.verus_id)}
    ctl = BlackboardController()
    ctl.register_predicate("promotion", make_promotion_predicate(
        gated, GOLDEN_ROOT,
        targets_fn=lambda: derive_report_targets(fe),
        codegen_fn=CODEGEN[fe.name],
        tool_gate=_combined_tool_gate(client, protocols,
                                      TOOL_GATE_IDS[fe.name]),
    ))
    ctl.blackboard.write_entry(
        key=f"promote:{fe.prefix}", predicate="promotion",
        measurement=promotion_request(fe.prefix), partition="provision")
    bb = ctl.run()
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: REFUSED - {entry.result.error}")
    outcome = bb.provision[f"promote:{fe.prefix}"].result
    print(f"  promote:{fe.prefix}: {outcome.codegen}; "
          f"targets regenerated={outcome.targets}; "
          f"{outcome.captured} files -> golden "
          "(no verification — the episode judges the new baseline)")

    print("\n=== provisioning the new baseline (props re-blessed) ===")
    fresh = build_protocol_dirs(fe, bless_props=True)
    protocols.update(fresh)
    provision_flow(fe, protocols, bless_props=True)

    print("\n=== verification episode (new baseline) ===")
    attest_episode(fe, protocols, repair=False, validate=True)


class CrateFileRestoreKS(KnowledgeSource):
    """
    Whole-file repair rung for the VERIFICATION tier: the verus tier's
    components carry a crate cwd, not a filepath, so the restore maps
    each failing crate to its l1a-hashed (and therefore goldened) files
    and restores those. The scope discipline is the crate boundary the
    failing component attests: files of passing crates are never
    touched. Same repair-cannot-mint-trust contract as the other
    restore rungs — pair with RestartEpisodeKS so fresh measurement
    judges the restore in-session.
    """

    name: str = "repair:whole-file:crate"
    partition: List[str] = []
    max_attempts: int = 1
    golden_root: Path
    hashed_files: List[str]  # the l1a protocol's filepaths (goldened)

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if not isinstance(entry.result, Verdict):
                continue
            crate_dirs = [Path(c.args["cwd"]) for c in entry.result.failing()
                          if (c.args or {}).get("cwd")]
            restored, unrestorable = [], []
            for fp in sorted(self.hashed_files):
                if not any(d in Path(fp).parents for d in crate_dirs):
                    continue
                golden_copy = mirror_path(self.golden_root, Path(fp))
                if golden_copy.is_file():
                    shutil.copy2(golden_copy, fp)
                    restored.append(fp)
                else:
                    unrestorable.append(fp)
            print(f"  {self.name}: restored {len(restored)} file(s) from golden"
                  + (f", {len(unrestorable)} unrestorable" if unrestorable else ""))
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=entry.measurement, result=None,
            )


def tamper_verus(fe: Frontend, protocols: dict) -> None:
    """Corrupt a line inside a Verus contract slice of the generated Rust."""
    l2 = protocols[fe.l2].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if "thermostat_rt_mhs" in a["filepath"]
                      and a["filepath"].endswith(".rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))
    print(f"Tampered Verus slice: {rs.name} line {args['start_index']} ({targ})")


MHS_APP = (ISL_ROOT / "hamr" / "microkit" / "crates" / "thermostat_rt_mhs_mhs"
           / "src" / "component" / "thermostat_rt_mhs_mhs_app.rs")

MHS_API = (ISL_ROOT / "hamr" / "microkit" / "crates" / "thermostat_rt_mhs_mhs"
           / "src" / "bridge" / "thermostat_rt_mhs_mhs_api.rs")

# tamper_cheat's injection point: the first statement of the verified
# put_heat_control body in MHS_API — a file cargo-verus verifies but no
# hash or slice tier measures
CHEAT_MARKER = "self.api.unverified_put_heat_control(value);"
CHEAT_LINE = "assume(false); // TAMPERED: proof admitted"


def tamper_cheat(fe: Frontend, protocols: dict) -> None:
    """The cheating prover: admit put_heat_control's contract with
    assume(false). The file is Verus-verified but sits outside every
    hash (l1a) and slice (l2) target, so the files and contracts tiers
    stay green, and the verus tier still reports the same success —
    only the cheat tier's count drift (assume 0 -> 1) refuses."""
    src = MHS_API.read_text()
    if CHEAT_LINE in src:
        print(f"tamper-cheat: {MHS_API.name} already tampered")
        return
    if CHEAT_MARKER not in src:
        raise SystemExit(f"tamper-cheat: injection marker not found in "
                         f"{MHS_API.name} (codegen drift?)")
    src = src.replace(CHEAT_MARKER, f"{CHEAT_LINE}\n      {CHEAT_MARKER}", 1)
    MHS_API.write_text(src)
    print(f"Admitted a verified contract: {CHEAT_LINE!r} injected into "
          f"put_heat_control ({MHS_API.name})")


MHS_EXTERN = (ISL_ROOT / "hamr" / "microkit" / "crates"
              / "thermostat_rt_mhs_mhs" / "src" / "bridge" / "extern_c_api.rs")

# tamper_ffi's target: the unsafe FFI glue under the proof tower. The
# body is plain unverified Rust (the verified bridge calls it through an
# external_body trait fn), so inverting the command here changes NO
# proof outcome, adds NO escape construct, and sits outside every l1a/l2
# target — only the gensrc byte tier can see it.
FFI_MARKER = ("    return put_heat_control(value as *const "
              "Isolette_Data_Model::On_Off as *mut "
              "Isolette_Data_Model::On_Off);")
FFI_TAMPERED = """    // TAMPERED: command inverted at the unverified FFI boundary
    let inverted = match value {
      Isolette_Data_Model::On_Off::Onn => Isolette_Data_Model::On_Off::Off,
      _ => Isolette_Data_Model::On_Off::Onn,
    };
    return put_heat_control(&inverted as *const Isolette_Data_Model::On_Off
                            as *mut Isolette_Data_Model::On_Off);"""


def tamper_ffi(fe: Frontend, protocols: dict) -> None:
    """Invert the heat command inside unsafe_put_heat_control — the
    unverified FFI glue every verified put flows through. The proofs are
    about the ghost model and the bridge's external_body boundary, so
    the crate still verifies (0 errors), the cheat scan counts no new
    construct (the escape surface is unchanged — the body was ALREADY
    trusted), and no hash or slice tier names this file. The verified
    tower stands; the foundation under it now does the opposite of what
    the proofs say. Only the gensrc byte tier refuses — and a
    cheat-clean drift like this is exactly why the gensrc ladder never
    rescues on a clean construct scan."""
    src = MHS_EXTERN.read_text()
    if "TAMPERED" in src:
        print(f"tamper-ffi: {MHS_EXTERN.name} already tampered")
        return
    if FFI_MARKER not in src:
        raise SystemExit(f"tamper-ffi: injection marker not found in "
                         f"{MHS_EXTERN.name} (codegen drift?)")
    MHS_EXTERN.write_text(src.replace(FFI_MARKER, FFI_TAMPERED, 1))
    print("Inverted the heat command in the unverified FFI glue "
          f"({MHS_EXTERN.name}): every proof still passes — the bodies "
          "were always trusted — and the cheat scan counts no new escape; "
          "only the gensrc byte tier can see it")


GUMBO_LIB = (ISL_ROOT / "hamr" / "microkit" / "crates" / "GUMBO_Library"
             / "src" / "lib.rs")

# tamper_broadcast plants a smuggled axiom in the shared foundation crate:
# an external_body proof fn (unchecked body) asserting a FALSE quantified
# fact, marked broadcast so a later `broadcast use` would inject it into
# every importer's proof context. It sits inside the GUMBO verus block.
BROADCAST_MARKER = "  // END MARKER GUMBO VERUS MARKER"
BROADCAST_AXIOM = (
    "  // TAMPERED: smuggled proof-context poison (false, unchecked body)\n"
    "  #[verifier::external_body]\n"
    "  pub broadcast proof fn smuggled_axiom()\n"
    "    ensures false\n"
    "  {}\n")


def tamper_broadcast(fe: Frontend, protocols: dict) -> None:
    """Plant a smuggled axiom in the shared foundation crate
    GUMBO_Library: an external_body (unchecked-body) broadcast proof fn
    whose ensures is `false`. The body is trusted, so it verifies clean
    on its own; once an importer says `broadcast use` it would inject
    `false` into that proof context — every proof downstream becomes
    vacuous.

    Every OUTCOME-based tier stays green, because until a `broadcast use`
    pulls it in the axiom is inert: it changes no proof outcome and
    lives in no hashed or sliced file. files (GUMBO_Library is
    report-invisible), contracts, the verus tier (errors==0 — the
    importers still verify, the axiom is not yet consumed),
    the sysproof hash (the proof crate is untouched), and the report all
    pass. Only the CHEAT tier — which counts escape CONSTRUCTS, not
    proof outcomes — refuses, naming GUMBO_Library (broadcast 0->1,
    external_body.other 0->1), catching the axiom at the staging point
    before any proof consumes it."""
    src = GUMBO_LIB.read_text()
    if "smuggled_axiom" in src:
        print(f"tamper-broadcast: {GUMBO_LIB.name} already tampered")
        return
    if BROADCAST_MARKER not in src:
        raise SystemExit(f"tamper-broadcast: injection marker not found in "
                         f"{GUMBO_LIB.name} (codegen drift?)")
    src = src.replace(BROADCAST_MARKER, BROADCAST_AXIOM + BROADCAST_MARKER, 1)
    GUMBO_LIB.write_text(src)
    print(f"Planted a smuggled axiom in GUMBO_Library ({GUMBO_LIB.name}): "
          "external_body broadcast proof fn, ensures false — verifies clean, "
          "inert until `broadcast use` (only the cheat scan sees it)")


# tamper_stale_dep's target: a spec predicate in the same shared
# foundation crate, flipped SEMANTICALLY (== -> !=, no construct-count
# change) with the file's mtime preserved nanosecond-exact. The verus
# tier's PRIMARY crates always re-verify, but the foundation crates are
# consumed as cargo DEPENDENCIES, and cargo's dep freshness is
# mtime-gated — so the warm cache serves the stale pre-tamper artifact
# and the flip changes no live verdict. sys_nominal_proof consumes the
# predicate load-bearingly: freshly verified, 8 of its VCs refute.
STALE_DEP_SPEC = (
    "pub open spec fn isValidTempWstatus_spec"
    "(value: Isolette_Data_Model::TempWstatus_i) -> bool\n"
    "  {\n"
    "    value.status == Isolette_Data_Model::ValueStatus::Valid\n"
    "  }")


def stale_dep_text(text: str) -> str:
    """The stale-dep tamper as a pure text transform (for previews)."""
    if text.count(STALE_DEP_SPEC) != 1:
        raise SystemExit("tamper-stale-dep: isValidTempWstatus_spec not "
                         f"found in {GUMBO_LIB.name} (codegen drift?)")
    return text.replace(STALE_DEP_SPEC,
                        STALE_DEP_SPEC.replace("==", "!="), 1)


def tamper_stale_dep(fe: Frontend, protocols: dict) -> None:
    """Flip isValidTempWstatus_spec's meaning in the shared
    GUMBO_Library, preserving the file's mtime nanosecond-exact.

    Every tier stays green: files/contracts (the foundation crate sits
    in no hashed or sliced file), the cheat scan (a semantic flip adds
    no escape construct), the sysproof hash (the proof crate's bytes are
    untouched) — and the verus tier, because although its 8 primary
    crates genuinely re-verify every run, they consume GUMBO_Library as
    a cargo DEPENDENCY, and cargo's mtime-gated dep freshness serves the
    stale pre-tamper artifact. 'Verification succeeded' is a verdict
    about bytes the verifier last LOOKED at. Only --fresh-deps (the
    content-hash guard) forces the dep re-verify that lets
    sys_nominal_proof refute the flip."""
    src = GUMBO_LIB.read_text()
    if "!= Isolette_Data_Model::ValueStatus::Valid" in src:
        print(f"tamper-stale-dep: {GUMBO_LIB.name} already tampered")
        return
    st = GUMBO_LIB.stat()
    GUMBO_LIB.write_text(stale_dep_text(src))
    os.utime(GUMBO_LIB, ns=(st.st_atime_ns, st.st_mtime_ns))
    print("Tampered a foundation dependency (GUMBO_Library): flipped "
          "isValidTempWstatus_spec (== -> !=) with the mtime preserved "
          "nanosecond-exact — cargo-verus's warm dependency cache will "
          "serve the STALE pre-tamper verdict")


# the dependency-freshness guard's scope: the foundation crates the
# verus tier consumes only as cargo dependencies (the system proof crate
# is a primary target — always re-verified — so it needs no guard)
DEP_CRATES = ("data", "GUMBO_Library")
DEP_FRESHNESS_SIDECAR = REPO / ".dep_freshness.json"


def _dep_crate_digest(crate: str) -> str:
    """One content digest per foundation crate: sorted relative paths +
    sha256 of every source file and the manifest."""
    import hashlib
    root = ISL_ROOT / "hamr" / "microkit" / "crates" / crate
    h = hashlib.sha256()
    for f in sorted((*(root / "src").rglob("*.rs"), root / "Cargo.toml")):
        h.update(str(f.relative_to(root)).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def fresh_deps_guard() -> None:
    """The scene-scoped dependency-freshness guard: cargo's dep cache is
    mtime-gated, so a content change with a preserved mtime yields a
    stale 'verified' verdict for every consumer. The guard re-keys
    freshness on CONTENT: it digests each foundation crate's sources
    against a sidecar record and, on drift, bumps the crate's source
    mtimes so cargo-verus must re-verify the dep (and its dependents)
    from the live bytes. Free when nothing changed.

    The sidecar is cache state, not trust state: it lives outside
    golden/, is seeded trust-on-first-use over the current warm cache
    (the demo seeds it right after a gated-clean checklist run), and on
    drift is updated to the live digest — sound in both directions,
    since a later restore registers as drift again and forces one more
    honest re-verify. Promoting the guard to an attested ASP with a
    blessed record is postponed by design."""
    live = {crate: _dep_crate_digest(crate) for crate in DEP_CRATES}
    if not DEP_FRESHNESS_SIDECAR.is_file():
        DEP_FRESHNESS_SIDECAR.write_text(json.dumps(live, indent=2) + "\n")
        print("fresh-deps: seeded the freshness record for "
              f"{', '.join(DEP_CRATES)} (trust-on-first-use over the "
              "current warm cache)")
        return
    recorded = json.loads(DEP_FRESHNESS_SIDECAR.read_text())
    drifted = [c for c in DEP_CRATES if recorded.get(c) != live[c]]
    if not drifted:
        print("fresh-deps: dependency sources match the freshness record "
              "— the warm cache is honest")
        return
    for crate in drifted:
        root = ISL_ROOT / "hamr" / "microkit" / "crates" / crate
        for f in (*(root / "src").rglob("*.rs"), root / "Cargo.toml"):
            os.utime(f)
    DEP_FRESHNESS_SIDECAR.write_text(json.dumps(live, indent=2) + "\n")
    print("fresh-deps: content drift in " + ", ".join(drifted)
          + " — mtimes bumped so cargo-verus must RE-VERIFY the "
          "dependency from the live bytes (no stale verdict)")


SYS_PROOF_DIR = (ISL_ROOT / "hamr" / "microkit" / "crates" / SYS_PROOF_CRATE)
SYS_PROOF_LIB = SYS_PROOF_DIR / "src" / "lib.rs"
SYS_PROOF_VC = (SYS_PROOF_DIR / "src" / "normal_display_temp"
                / "vc_sequential.rs")

# tamper_proof_swap drops this unreferenced empty-bodied VC and adds a
# trivial one, holding the verified count constant
_SWAP_DROP = "pub proof fn vc_pre_assert_oi"
_SWAP_ADD = ("verus! {\n"
             "pub proof fn dropped_and_replaced() ensures true {}\n")


def tamper_proof_count(fe: Frontend, protocols: dict) -> None:
    """Shrink the verified surface: comment out one proof module of the
    system proof crate. The crate still verifies (0 errors) — the Verus
    tier judges correctness, not surface size, so it stays GREEN. Only
    the sysproof whole-file hash refuses (lib.rs changed)."""
    src = SYS_PROOF_LIB.read_text()
    mod = "pub mod normal_display_temp;"
    if mod not in src:
        raise SystemExit(f"tamper-proof-count: '{mod}' not found "
                         f"in {SYS_PROOF_LIB.name} (codegen drift?)")
    src = src.replace(mod, f"// {mod}  // COUNT TAMPER: module dropped", 1)
    SYS_PROOF_LIB.write_text(src)
    print(f"Shrank the proof surface: commented out {mod!r} "
          f"({SYS_PROOF_LIB.name})")


def tamper_proof_swap(fe: Frontend, protocols: dict) -> None:
    """Drop-and-replace: delete a real VC and add a trivial one. The
    crate still verifies (0 errors), so the Verus tier (correctness)
    stays green and the cheat scan stays silent (no escape construct).
    Only the sysproof whole-file hash refuses — the surface changed
    even though every proof outcome is clean."""
    import re
    src = SYS_PROOF_VC.read_text()
    m = re.search(r'pub proof fn vc_pre_assert_oi.*?\n\{\}\n', src, re.S)
    if not m:
        raise SystemExit(f"tamper-proof-swap: vc_pre_assert_oi block not "
                         f"found in {SYS_PROOF_VC.name} (codegen drift?)")
    src = src[:m.start()] + src[m.end():]       # drop the real VC
    src = src.replace("verus! {", _SWAP_ADD, 1)  # add the trivial one
    SYS_PROOF_VC.write_text(src)
    print(f"Swapped a proof: dropped vc_pre_assert_oi, added a trivial VC "
          f"({SYS_PROOF_VC.name}) — verified count held at 1862")


def tamper_note(fe: Frontend, protocols: dict) -> None:
    """Benign drift: an engineering note appended OUTSIDE every measured
    slice of a hashed file — the whole-file hash fails, every contract
    slice passes. Pairs with --tamper-verus for the slice-granularity
    repair beat: the slice rung must restore only the violated block and
    leave this note standing."""
    with open(MHS_APP, "a") as f:
        f.write("\n// engineering note: candidate sensor swap under review\n")
    print(f"Appended a benign note to {MHS_APP.name} (outside every slice)")


def tamper_impl(fe: Frontend, protocols: dict) -> None:
    """The INSPECTA exemplar's own seeded bug: in NORMAL mode with the
    temperature below the lower bound, command Off instead of On — the
    REQ_MHS_2 ensures clause is genuinely FALSE of the implementation.
    The edit lives in the developer-owned region: every contract slice
    stays intact, so integrity attests clean at finer granularity and
    only the verification tier refutes."""
    import re
    text = MHS_APP.read_text()
    tampered, n = re.subn(
        r"^(\s*)//(currentCmd = On_Off::Off; // seeded bug/error)\n"
        r"(\s*)(currentCmd = On_Off::Onn;)",
        r"\1\2\n\3//\4", text, count=1, flags=re.M)
    if n == 0:
        raise SystemExit("--tamper-impl: the seeded-bug lines were not found "
                         f"in {MHS_APP}")
    MHS_APP.write_text(tampered)
    print(f"Tampered implementation: {MHS_APP.name} REQ-MHS-2 response "
          "inverted (developer region; contract slices untouched)")


def tamper_impl_benign(fe: Frontend, protocols: dict) -> None:
    """Benign implementation drift: a semantically equivalent rewrite of
    the developer-owned NORMAL-mode guard (x > y  ->  y < x). Every
    contract slice stays byte-identical and the rewritten implementation
    still PROVES against the unchanged contracts — only the whole-file
    hash refuses, and the files entry ends attested clean via the l2
    refinement while the verus tier re-verifies the rewrite."""
    text = MHS_APP.read_text()
    a = "if (currentTemp.degrees > upper.degrees) {"
    b = "if (upper.degrees < currentTemp.degrees) {"
    if a not in text:
        raise SystemExit("--tamper-impl-benign: the NORMAL-mode guard was "
                         f"not found in {MHS_APP}")
    MHS_APP.write_text(text.replace(a, b, 1))
    print(f"Tampered implementation (benign): {MHS_APP.name} NORMAL-mode "
          "guard rewritten equivalently (x > y -> y < x; contract slices "
          "untouched, still provable)")


def tamper_contract_launder(fe: Frontend, protocols: dict) -> None:
    """Contract drift laundering: WEAKEN the generated REQ_MHS_2 ensures
    (admit both heat-control states) AND invert the implementation to
    the very behavior the weakening covers for. cargo-verus succeeds —
    the pair is self-consistent — but the contract has drifted from what
    the blessed model renders: the byte anchors (l1a + the l2 lineage
    against goldens derived from the blessed model) are the only
    detectors. The model itself is untouched."""
    import re
    text = MHS_APP.read_text()
    a = ("(api.heat_control == Isolette_Data_Model::On_Off::Onn),\n"
         "        // case REQ_MHS_3")
    b = ("(api.heat_control == Isolette_Data_Model::On_Off::Onn ||\n"
         "          api.heat_control == Isolette_Data_Model::On_Off::Off),"
         "  // TAMPERED: weakened\n"
         "        // case REQ_MHS_3")
    if a not in text:
        raise SystemExit("--tamper-contract-launder: the REQ_MHS_2 ensures "
                         f"consequent was not found in {MHS_APP}")
    text = text.replace(a, b, 1)
    tampered, n = re.subn(
        r"^(\s*)//(currentCmd = On_Off::Off; // seeded bug/error)\n"
        r"(\s*)(currentCmd = On_Off::Onn;)",
        r"\1\2\n\3//\4", text, count=1, flags=re.M)
    if n == 0:
        raise SystemExit("--tamper-contract-launder: the seeded-bug lines "
                         f"were not found in {MHS_APP}")
    MHS_APP.write_text(tampered)
    print(f"Tampered contract + implementation: {MHS_APP.name} REQ_MHS_2 "
          "ensures WEAKENED and the response inverted to match — "
          "self-consistent (verification succeeds), but the contract has "
          "drifted from the blessed model")


def tamper_report(fe: Frontend, protocols: dict) -> None:
    """Deletion: one Slice quietly removed from a contract report — the
    authority now names one fewer measurement target, and every protocol
    dir re-derived from it would measure less than the blessing
    intended. Only the report's own byte anchor refutes."""
    d = json.loads(fe.report.read_text())
    for comp in d["reports"]:
        for contract in comp.get("reports", []):
            if len(contract.get("slices", [])) > 1:
                gone = contract["slices"].pop()
                fe.report.write_text(json.dumps(d, indent=2) + "\n")
                print(f"Tampered report: deleted a {gone['kind']} slice from "
                      f"{contract['id']} ({'_'.join(comp['idPath'])})")
                return
    raise SystemExit("--tamper-report: no multi-slice contract found")


def tamper_report_subst(fe: Frontend, protocols: dict) -> None:
    """Substitution: one slice's span swapped for a different span in
    the same file — the slice count stays right, the structure stays
    plausible, and a re-derived protocol would measure the WRONG lines
    while every count-based check reads clean. Only the byte anchor
    refutes."""
    d = json.loads(fe.report.read_text())
    spans = []  # (contract_id, slice) with line spans, per uri
    for comp in d["reports"]:
        for contract in comp.get("reports", []):
            for s in contract.get("slices", []):
                pos = s.get("pos", {})
                if "beginLine" in pos:
                    spans.append((contract["id"], s))
    for i, (cid_a, a) in enumerate(spans):
        for cid_b, b in spans[i + 1:]:
            pa, pb = a["pos"], b["pos"]
            if cid_a != cid_b and pa["uri"] == pb["uri"] \
                    and pa["beginLine"] != pb["beginLine"]:
                pa["beginLine"], pa["endLine"] = pb["beginLine"], pb["endLine"]
                fe.report.write_text(json.dumps(d, indent=2) + "\n")
                print(f"Tampered report: {cid_a}'s slice span substituted "
                      f"with {cid_b}'s (same file, same slice count)")
                return
    raise SystemExit("--tamper-report-subst: no substitutable slice pair")


class ReportRegenerateKS(KnowledgeSource):
    """
    The regeneration rung — neither restore nor synthesis: the report is
    a RENDERING of the model through the codegen toolchain, so the
    repair re-emits it (real codegen, in place) behind the tool gate
    that anchors the emitter to its blessed hashes. Fresh measurement
    then judges the regenerated rendering against the provisioned golden
    (pair with RestartEpisodeKS).
    """

    name: str = "repair:regenerate-report"
    partition: List[str] = []
    max_attempts: int = 1
    fe_name: str
    tool_gate: object = None

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if self.tool_gate is not None:
                error = self.tool_gate()
                if error:
                    print(f"  {self.name}: toolchain gate refused "
                          f"regeneration: {error}")
                    continue  # decline; handoff/escalation follows
            desc = CODEGEN[self.fe_name]()
            print(f"  {self.name}: regenerated the attestation report "
                  f"from the model ({desc})")
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=entry.measurement, result=None,
            )


class GenSrcDriftDiagnosisKS(KnowledgeSource):
    """
    The gensrc ladder's diagnosis rung — attribution, never rescue. The
    cheat tier already ran in this same episode, so no new measurement
    is needed: for each drifted crate the rung correlates the two
    verdicts and names the drift KIND — "a proof escape appeared" (the
    cheat scan refused the same crate) or "cheat counts clean — a
    semantic edit no construct scan can see" (a weakened contract, a
    changed FFI body). The latter is exactly why a clean cheat scan must
    never pass a failed byte anchor: these files are do-not-edit
    generated, every byte is measured semantics. Diagnosis only — the
    chain hands the key onward (regeneration or escalation) either way.
    """

    name: str = "diagnose:gensrc-drift"
    partition: List[str] = []
    max_attempts: int = 1
    prefix: str
    cheats_key: str = ""

    def _crate_of(self, targ: str, suffix: str) -> str:
        return targ[len(self.prefix) + 1:-len(suffix)] \
            if targ.startswith(self.prefix) and targ.endswith(suffix) else targ

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        cheat_failing = set()
        if self.cheats_key:
            # a refused cheat entry has no repair chain, so by the time
            # this rung runs it has already been POPPED into the
            # escalate map — look in both places
            cheat = (blackboard.get_entry(self.cheats_key)
                     or blackboard.get_escalate().get(self.cheats_key))
            if cheat is not None and isinstance(cheat.result, Verdict):
                cheat_failing = {
                    self._crate_of(c.targ_id or "", "_cheat_targ")
                    for c in cheat.result.failing()}
        for key in keys:
            entry = blackboard.get_entry(key)
            if not isinstance(entry.result, Verdict):
                continue
            for c in entry.result.failing():
                crate = self._crate_of(c.targ_id or "", "_gensrc_targ")
                reason = " ".join((c.reason or "").split())[:120]
                if crate in cheat_failing:
                    print(f"  {self.name}: {crate} — bytes drifted AND the "
                          "cheat scan refused the same crate: a proof "
                          f"ESCAPE appeared ({reason})")
                else:
                    print(f"  {self.name}: {crate} — bytes drifted with "
                          "cheat counts CLEAN: a semantic edit no "
                          "construct scan can see (weakened contract, "
                          f"changed unverified body) ({reason})")
            # diagnosis only: never writes, never repairs


class GenSrcRegenerateKS(KnowledgeSource):
    """
    The gensrc repair rung — scene 8's regeneration species applied to
    the generated sources: like the report, these files are RENDERINGS
    of the model through the codegen toolchain, so the honest repair is
    neither restore-from-golden (that's for developer-owned artifacts)
    nor rescue — it re-emits them via real codegen behind the measured
    tool gate, and fresh measurement judges the result (pair with
    RestartEpisodeKS).
    """

    name: str = "repair:regenerate-gensrc"
    partition: List[str] = []
    max_attempts: int = 1
    fe_name: str
    tool_gate: object = None

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if self.tool_gate is not None:
                error = self.tool_gate()
                if error:
                    print(f"  {self.name}: toolchain gate refused "
                          f"regeneration: {error}")
                    continue  # decline; handoff/escalation follows
            desc = CODEGEN[self.fe_name]()
            print(f"  {self.name}: regenerated the generated sources "
                  f"from the model ({desc})")
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=entry.measurement, result=None,
            )


# The pre-generated dummy bad implementation (scene 8's tamper stand-in
# for a real-world bad implementation): the developer-owned compute
# logic replaced wholesale — heat ON in INIT and FAILED modes, both
# NORMAL responses inverted. It compiles fine; the blessed contracts
# are genuinely FALSE of it, so no contract-side repair can help.
DUMMY_BAD_IMPL = """match regulator_mode {

          // ----- INIT Mode --------
          Regulator_Mode::Init_Regulator_Mode => {
              // DUMMY BAD IMPL: heat left ON during initialization
              currentCmd = On_Off::Onn;
          },

          // ------ NORMAL Mode -------
          Regulator_Mode::Normal_Regulator_Mode => {
              if (currentTemp.degrees > upper.degrees) {
                  // DUMMY BAD IMPL: inverted response when too hot
                  currentCmd = On_Off::Onn;
              } else if (currentTemp.degrees < lower.degrees) {
                  // DUMMY BAD IMPL: inverted response when too cold
                  currentCmd = On_Off::Off;
              }
          },

          // ------ FAILED Mode -------
          Regulator_Mode::Failed_Regulator_Mode => {
              // DUMMY BAD IMPL: heat left ON after failure
              currentCmd = On_Off::Onn;
          }
      }"""


def dummy_bad_impl_text(text: str) -> str:
    """The given app.rs source with its compute logic replaced by the
    pre-generated dummy bad implementation (pure function — the demo
    uses it to render the would-be tamper for a diff without touching
    the live tree)."""
    head, sep, rest = text.partition("match regulator_mode {")
    if not sep:
        raise SystemExit("dummy bad impl: no match block found")
    _, sep2, tail = rest.partition(
        "// -------------- Set values of output ports")
    if not sep2:
        raise SystemExit("dummy bad impl: no output-ports anchor found")
    return head + DUMMY_BAD_IMPL + "\n\n      " + sep2 + tail


def tamper_impl_full(fe: Frontend, protocols: dict) -> None:
    """Swap in the pre-generated dummy bad implementation: the whole
    match block of the developer-owned compute logic replaced. Every
    contract slice stays byte-identical — the implementation is the
    only artifact that moved."""
    MHS_APP.write_text(dummy_bad_impl_text(MHS_APP.read_text()))
    print(f"Tampered implementation: {MHS_APP.name} compute logic replaced "
          "with the pre-generated DUMMY BAD IMPL (contract slices untouched)")


class ContractsIntactDiagnosisKS(KnowledgeSource):
    """
    The ladder's diagnosis rung: before any repair, establish WHICH
    artifact is at fault. For every failing crate it checks each blessed
    contract slice of that crate's measured files against the golden
    slice bytes (by content — the goldens were baseline-verified at
    readiness). Contracts intact means the refutation cannot be repaired
    on the contract side — the implementation is the artifact at fault —
    and the rung DECLINES, handing the chain to the impl rung. The
    exhaustion is the diagnosis.
    """

    name: str = "diagnose:contracts-intact"
    partition: List[str] = []
    max_attempts: int = 1
    l2_targets: dict  # the l2 protocol's readfile_range asp_args

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        import base64
        for key in keys:
            entry = blackboard.get_entry(key)
            if not isinstance(entry.result, Verdict):
                continue
            crate_dirs = [c.args["cwd"] for c in entry.result.failing()
                          if (c.args or {}).get("cwd")]
            intact, drifted = 0, []
            live_norm = {}  # newline-stripped file bytes, the golden's form
            for targ, args in sorted(self.l2_targets.items()):
                fp = args.get("filepath", "")
                if not any(fp.startswith(d.rstrip("/") + "/")
                           for d in crate_dirs):
                    continue
                # readfile_range goldens are the slice's lines
                # concatenated WITHOUT newlines; normalize the live file
                # the same way and locate by content (insertion-robust)
                if fp not in live_norm:
                    live_norm[fp] = Path(fp).read_bytes() \
                        .replace(b"\r\n", b"\n").replace(b"\n", b"")
                golden = base64.b64decode(args.get("golden_b64", ""))
                if golden and golden in live_norm[fp]:
                    intact += 1
                else:
                    drifted.append(targ)
            if drifted:
                print(f"  {self.name}: {len(drifted)} contract slice(s) "
                      "drifted — a contract-side repair applies first: "
                      + ", ".join(drifted[:3]))
            else:
                print(f"  {self.name}: all {intact} contract slices of the "
                      "failing crate(s) are byte-identical to golden — the "
                      "IMPLEMENTATION is the artifact at fault; handing to "
                      "the impl rung")
            # diagnosis only: never writes, never repairs — the chain
            # hands the key to the next rung either way


# ── the progress view (--ready / --status) ────────────────────────────────────

def ready_flow(fe: Frontend, protocols: dict):
    """The standalone readiness gate: protocol configuration checks plus
    verification of every signed golden baseline, no attestation."""
    print(f"verifying {len(protocols)} signed baseline(s) "
          f"({', '.join(sorted(protocols))}) ...", flush=True)
    report = make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT,
        client=CvmSubprocessClient())(readiness_request(list(protocols)))
    print(f"readiness: {'PASS' if report else 'FAIL'} "
          f"(checked: {', '.join(report.checked)})")
    if report.baseline_verified:
        print("  signed baselines verified: "
              + ", ".join(report.baseline_verified))
    for p in (*report.problems, *report.baseline_problems):
        print(f"  problem: {p}")
    return report


def status_flow(fe: Frontend, protocols: dict, ready: bool,
                status: bool) -> None:
    """The per-crate proof checklist, same semantics as the Rocq
    driver's goals view: QUICK by default (one verification-tier run —
    rows from the AM-owned crate list, cells from each crate's own
    cargo-verus component, downgrade-only; a failed woven tool hash
    poisons every cell to '?'). --ready additionally runs the readiness
    gate first — alone it just prints the report; combined with
    --status a failure poisons every cell."""
    report = ready_flow(fe, protocols) if ready else None
    if not status:
        return
    verdict = make_attestation_predicate(CvmSubprocessClient(), protocols)(
        attestation_request(fe.verus_id))
    checklist = verus_crate_checklist(
        verdict, protocols[fe.verus_id].asp_args["run_command_cargo_verus"])
    if ready and not report:
        problems = "; ".join((*report.problems, *report.baseline_problems))
        checklist = checklist.poison(f"readiness failed: {problems[:200]}")
    elif ready:
        checklist = checklist.model_copy(update={"trusted": True})
    print(render_checklist(checklist, subject="contract-bearing crates"))


def _find_marker_block(lines: list, begin: str, end: str):
    """Inclusive (i, j) 0-based indices of the marker block, matching the
    readfile_marker_range ASP's location rule (marker = sole content of
    the line after stripping an optional // prefix)."""
    def is_marker(ln, m):
        return ln.strip().removeprefix("//").strip() == m
    i = next((k for k, ln in enumerate(lines) if is_marker(ln, begin)), None)
    if i is None:
        return None
    j = next((k for k in range(i + 1, len(lines))
              if is_marker(lines[k], end)), None)
    if j is None:
        return None
    return i, j


class MarkerBlockRestoreKS(KnowledgeSource):
    """The l1b repair rung: splice the GOLDEN bytes of every drifted
    marker block back into the live file — located by marker anchor
    (insertion-robust), so developer-owned regions outside the blocks
    are left untouched. Contract drift is repaired from the blessed
    golden; whether the surviving implementation still PROVES against
    the restored contracts is the restarted episode's honest
    measurement, not this rung's claim."""

    name: str = "repair:marker-blocks"
    partition: List[str] = []
    max_attempts: int = 1
    l1b_targets: dict
    golden_root: str

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        restored = []
        for t in self.l1b_targets.values():
            live = Path(t["filepath"])
            gold = Path(f"{self.golden_root}{live}")
            if not gold.is_file():
                continue
            live_lines = live.read_text().splitlines(keepends=True)
            gold_lines = gold.read_text().splitlines(keepends=True)
            lb = _find_marker_block(live_lines, t["begin_marker"],
                                    t["end_marker"])
            gb = _find_marker_block(gold_lines, t["begin_marker"],
                                    t["end_marker"])
            if lb is None or gb is None:
                continue
            li, lj = lb
            gi, gj = gb
            if live_lines[li:lj + 1] != gold_lines[gi:gj + 1]:
                live_lines[li:lj + 1] = gold_lines[gi:gj + 1]
                live.write_text("".join(live_lines))
                restored.append(
                    f"{live.name}[{t['begin_marker'].removeprefix('BEGIN ')}]")
        if restored:
            print(f"repair:marker-blocks: restored {len(restored)} golden "
                  f"marker block(s): {', '.join(restored)}")


def attest_episode(fe: Frontend, protocols: dict, repair: bool,
                   validate: bool = False, granularity: str = "file",
                   restart: bool = False, pause: bool = False,
                   verify: bool = False, immutable: bool = False,
                   restore_crates: bool = False, repair_impl: bool = False,
                   regen_report: bool = False, regen_gensrc: bool = False,
                   repair_markers: bool = False,
                   tool_gate=None) -> BlackboardController:
    """
    One verification episode. The baseline shape is unchanged (files
    entry at l1a, l2 refinement on failure, optional --validate
    verus confirmation on pass, whole-file repair rung under --repair).
    The demo modes compose on top:

      immutable       the automated-pipeline ruling: measured files must
                      never drift, so the failed l1a hash appraisal IS
                      the repair order — whole-file restore straight off
                      the l1a verdict, no l2 examination, no interaction
      verify          a SECOND always-run episode entry, {prefix}:proofs,
                      seeded at the verus tier — the verification class
                      judged every episode regardless of what integrity
                      finds (the Rocq example's three-entry shape)
      restart         in-session re-attestation: RestartEpisodeKS after
                      the repair rung, so a repaired entry ends the run
                      judged by FRESH measurement, not escalated pending
                      the next one
      granularity     the repair unit under restart: "file" (whole-file
                      restore) or "slice" (content-aligned splice of only
                      the violated blocks — benign drift elsewhere in the
                      file survives)
      restore_crates  (with verify) the proofs entry's restore rung:
                      failing crates' hashed files restored from golden
      repair_impl     (with verify) the ladder: diagnosis first (the
                      failing crates' contract slices checked against
                      golden — intact contracts mean the IMPLEMENTATION
                      is the artifact at fault), then the impl rung
                      (crate-scoped restore, standing in for a
                      spec-guided engine), then in-session re-attest
      regen_report    (with verify) the report entry's repair rung: the
                      rendering is REGENERATED from the model via
                      measured codegen (tool gate first), then fresh
                      measurement judges it
      pause           the out-of-band rung on both entries' failure
                      chains: the episode blocks on a work order, YOU
                      repair, fresh measurement judges the claim
    """
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation",
        make_attestation_predicate(client, protocols,
                                   archive_dir=REPO / "evidence"))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    files_key = f"{fe.prefix}:files"
    proofs_key = f"{fe.prefix}:proofs"
    report_key = f"{fe.prefix}:report"
    cheats_key = f"{fe.prefix}:cheats"
    proofsrc_key = f"{fe.prefix}:proofsrc"
    gensrc_key = f"{fe.prefix}:gensrc"
    contracts_key = f"{fe.prefix}:contracts"
    with_markers = verify and fe.l1b in protocols
    with_report = verify and fe.report_id in protocols
    with_cheats = verify and fe.cheat_id in protocols
    with_proofsrc = verify and fe.sysproof_id in protocols
    with_gensrc = verify and fe.gensrc_id in protocols
    siblings = [proofs_key] if verify else []
    if with_markers:
        siblings.append(contracts_key)
    if with_cheats:
        siblings.append(cheats_key)
    if with_proofsrc:
        siblings.append(proofsrc_key)
    if with_gensrc:
        siblings.append(gensrc_key)

    if immutable:
        # refined_by = the entry's own l1a protocol: the hash verdict
        # itself names the repair targets
        fail_chain = [WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                         refined_by=fe.l1a)]
    else:
        fail_chain = [TierKS(protocol_id=fe.l2)]
        if repair or restart:
            if granularity == "slice":
                fail_chain.append(RangeSliceRestoreKS(golden_root=GOLDEN_ROOT,
                                                      refined_by=fe.l2))
            else:
                fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                                     refined_by=fe.l2))
    pause_ks = OutOfBandRepairKS(also=[]) if pause else None
    if pause_ks is not None:
        fail_chain.append(pause_ks)
    if restart:
        fail_chain.append(RestartEpisodeKS(budget=1, also=siblings))

    proofs_chain = []
    if verify:
        if repair_impl:
            proofs_chain.append(ContractsIntactDiagnosisKS(
                l2_targets=protocols[fe.l2].asp_args["readfile_range"]))
        if restore_crates or repair_impl:
            proofs_chain.append(CrateFileRestoreKS(
                golden_root=GOLDEN_ROOT,
                hashed_files=[a["filepath"] for a in
                              protocols[fe.l1a].asp_args["hashfile"].values()]))
            proofs_chain.append(RestartEpisodeKS(
                # budget 2: a marker-rung repair may already have spent
                # one restart on this key before the impl rung runs
                name="restart:proofs", budget=2, also=[files_key]))
        if pause_ks is not None:
            pause_ks.also = [files_key]
            proofs_chain.append(pause_ks)

    markers_chain = []
    if with_markers and repair_markers:
        markers_chain = [
            MarkerBlockRestoreKS(
                l1b_targets=protocols[fe.l1b].asp_args[
                    "readfile_marker_range"],
                golden_root=str(GOLDEN_ROOT)),
            RestartEpisodeKS(name="restart:markers", budget=1,
                             also=[files_key, proofs_key]),
        ]

    report_chain = []
    if with_report and regen_report:
        report_chain = [
            ReportRegenerateKS(fe_name=fe.name, tool_gate=tool_gate),
            RestartEpisodeKS(name="restart:report", budget=1),
        ]

    # the gensrc ladder: coarse byte anchor (the entry itself), then
    # diagnosis (drift KIND, correlated against the same episode's cheat
    # verdict), then — opt-in — regeneration via measured codegen. Never
    # a rescue rung: a cheat-clean drift can still be a weakened
    # contract or a changed unverified body
    gensrc_chain = []
    if with_gensrc:
        gensrc_chain.append(GenSrcDriftDiagnosisKS(
            prefix=fe.prefix,
            cheats_key=cheats_key if with_cheats else ""))
        if regen_gensrc:
            gensrc_chain.append(GenSrcRegenerateKS(fe_name=fe.name,
                                                   tool_gate=tool_gate))
            gensrc_chain.append(RestartEpisodeKS(name="restart:gensrc",
                                                 budget=1))

    confirm = [TierKS(protocol_id=fe.verus_id)] if validate else []
    episodes = {files_key: fe.l1a}
    if verify:
        episodes[proofs_key] = fe.verus_id
    if with_markers:
        # the marker tier: every byte of the codegen-managed contract
        # blocks, measured regardless of what the report slices — the
        # backstop for contract drift between the report's slices
        episodes[contracts_key] = fe.l1b
    if with_cheats:
        # the cheat tier: no repair chain on purpose — an admitted proof
        # is never machine-repairable, the refusal must escalate
        episodes[cheats_key] = fe.cheat_id
    if with_proofsrc:
        # the system proof crate's byte integrity: do-not-edit generated,
        # so any drift is a sanctioned HAMR re-run (promote path) or
        # tampering — escalate, never machine-repair
        episodes[proofsrc_key] = fe.sysproof_id
    if with_gensrc:
        episodes[gensrc_key] = fe.gensrc_id
    if with_report:
        episodes[report_key] = fe.report_id
    starter = StartAttestationKS(episodes=episodes)
    seen = set()
    for ks in (*confirm, *fail_chain, *proofs_chain, *markers_chain,
               *report_chain, *gensrc_chain, starter):
        if id(ks) not in seen:
            controller.add_ks(ks)
            seen.add(id(ks))
    controller.route(files_key, on_pass=confirm, on_fail=fail_chain)
    if verify:
        controller.route(proofs_key, on_pass=[], on_fail=proofs_chain)
    if with_markers:
        controller.route(contracts_key, on_pass=[], on_fail=markers_chain)
    if with_cheats:
        controller.route(cheats_key, on_pass=[], on_fail=[])
    if with_proofsrc:
        controller.route(proofsrc_key, on_pass=[], on_fail=[])
    if with_gensrc:
        controller.route(gensrc_key, on_pass=[], on_fail=gensrc_chain)
    if with_report:
        controller.route(report_key, on_pass=[], on_fail=report_chain)
    controller.blackboard.write_entry(
        key=f"{fe.prefix}:ready", predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route(f"{fe.prefix}:ready", on_pass=[starter], on_fail=[])
    controller.run()
    semantic = [fe.verus_id] + ([fe.cheat_id] if with_cheats else [])
    print(trust_summary(controller.blackboard, semantic=semantic))
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", choices=sorted(FRONTENDS),
                        default="aadl")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--force-timestamp", action="store_true",
                        help="stamp fresh golden_ts values even when the "
                             "extracted goldens are unchanged")
    parser.add_argument("--bless-props", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--tamper-verus", action="store_true")
    parser.add_argument("--tamper-cheat", action="store_true")
    parser.add_argument("--tamper-broadcast", action="store_true",
                        help="plant a smuggled axiom (external_body broadcast "
                             "proof fn, ensures false) in the shared "
                             "GUMBO_Library — inert, so every outcome-based "
                             "tier stays green; only the cheat scan refuses, "
                             "naming the crate")
    parser.add_argument("--tamper-proof-count", action="store_true",
                        help="drop a proof module of the system proof crate "
                             "(still verifies — Verus green; only the "
                             "sysproof hash refuses)")
    parser.add_argument("--tamper-proof-swap", action="store_true",
                        help="drop a real VC and add a trivial one, still "
                             "verifying (Verus green; only the sysproof hash "
                             "refuses)")
    parser.add_argument("--tamper-ffi", action="store_true",
                        help="invert the heat command in the unverified FFI "
                             "glue: every proof passes, cheat counts clean — "
                             "only the gensrc byte tier refuses (the drift "
                             "kind no rescue rung may forgive)")
    parser.add_argument("--regen-gensrc", action="store_true",
                        help="the gensrc entry's repair rung: re-emit the "
                             "generated sources via measured codegen (tool "
                             "gate first), then fresh measurement judges")
    parser.add_argument("--tamper-stale-dep", action="store_true",
                        help="flip a GUMBO_Library spec predicate with the "
                             "mtime preserved — cargo's mtime-gated dep cache "
                             "serves the stale verdict, every tier stays "
                             "green; --fresh-deps is the guard that closes it")
    parser.add_argument("--fresh-deps", action="store_true",
                        help="content-hash the foundation dep crates against "
                             "a sidecar record and bump mtimes on drift, so "
                             "cargo-verus must re-verify the dep from the "
                             "live bytes; alone: seed/check the record only")
    parser.add_argument("--tamper-note", action="store_true")
    parser.add_argument("--tamper-impl", action="store_true")
    parser.add_argument("--tamper-impl-full", action="store_true")
    parser.add_argument("--tamper-impl-benign", action="store_true",
                        help="benign equivalent rewrite of the developer-owned "
                             "guard: slices intact, still proves")
    parser.add_argument("--tamper-contract-launder", action="store_true",
                        help="weaken the generated REQ_MHS_2 ensures AND invert "
                             "the impl to match: verification succeeds, the "
                             "contract has drifted from the blessed model")
    parser.add_argument("--tamper-report", action="store_true")
    parser.add_argument("--tamper-report-subst", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--ready", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--immutable-model", action="store_true")
    parser.add_argument("--repair-granularity", choices=("file", "slice"),
                        default=None)
    parser.add_argument("--restore-crates", action="store_true")
    parser.add_argument("--repair-impl", action="store_true")
    parser.add_argument("--repair-markers", action="store_true",
                        help="l1b repair rung: splice golden marker blocks "
                             "back on contract drift, then restart")
    parser.add_argument("--regen-report", action="store_true")
    parser.add_argument("--pause", action="store_true")
    cli = parser.parse_args()
    fe = FRONTENDS[cli.frontend]
    tampers = ((tamper_verus, cli.tamper_verus),
               (tamper_cheat, cli.tamper_cheat),
               (tamper_broadcast, cli.tamper_broadcast),
               (tamper_ffi, cli.tamper_ffi),
               (tamper_stale_dep, cli.tamper_stale_dep),
               (tamper_proof_count, cli.tamper_proof_count),
               (tamper_proof_swap, cli.tamper_proof_swap),
               (tamper_note, cli.tamper_note),
               (tamper_impl, cli.tamper_impl),
               (tamper_impl_full, cli.tamper_impl_full),
               (tamper_impl_benign, cli.tamper_impl_benign),
               (tamper_contract_launder, cli.tamper_contract_launder),
               (tamper_report, cli.tamper_report),
               (tamper_report_subst, cli.tamper_report_subst))

    if cli.check:
        print_check(fe, load_protocols(fe))
        return
    if cli.fresh_deps and not cli.verify:
        # standalone: seed or check the freshness record, no episode
        fresh_deps_guard()
        return
    if cli.ready or cli.status:
        # the progress view: tamper flags apply first (a checklist over
        # a deliberately broken tree is a demo beat), and NOTHING is
        # restored on exit — the view must not mutate the tree
        protocols = load_protocols(fe, validate=True)
        for tamper, flag in tampers:
            if flag:
                tamper(fe, protocols)
        status_flow(fe, protocols, ready=cli.ready, status=cli.status)
        return
    if cli.promote:
        protocols = load_protocols(fe, validate=True)
        for tid in TOOL_GATE_IDS[fe.name]:
            if (FIXTURES / tid / "asp_args.json").is_file():
                protocols[tid] = ProtocolDir.load(str(FIXTURES / tid))
        promote_flow(fe, protocols)
        return
    if cli.provision:
        # --bless-props: the spec-first sanctioning act — re-sign the
        # props blessing over the CURRENT model files (plus ordinary
        # re-provisioning), without running codegen. The generated
        # realization has not caught up yet; --promote is the sanctioned
        # pipeline that makes it (tool gate -> real codegen -> proof
        # gate -> gold -> re-bless).
        protocols = build_protocol_dirs(fe, bless_props=cli.bless_props)
        provision_flow(fe, protocols, bless_props=cli.bless_props,
                       force_timestamp=cli.force_timestamp)
        return

    restart = (cli.immutable_model or cli.repair_granularity is not None
               or cli.restore_crates or cli.repair_impl
               or cli.repair_markers)
    granularity = cli.repair_granularity or "file"
    protocols = load_protocols(fe, validate=cli.validate or cli.verify)
    tool_gate = None
    if cli.regen_report or cli.regen_gensrc:
        # the regeneration rungs re-run codegen: measure the emitter
        # (and, for SysML, the pinned libraries) immediately before use
        for tid in TOOL_GATE_IDS[fe.name]:
            if (FIXTURES / tid / "asp_args.json").is_file():
                protocols[tid] = ProtocolDir.load(str(FIXTURES / tid))
        tool_gate = _combined_tool_gate(CvmSubprocessClient(), protocols,
                                        TOOL_GATE_IDS[fe.name])
    snapshot_ids = list(fe.protocol_ids)
    if fe.report_id in protocols and mirror_path(GOLDEN_ROOT,
                                                 fe.report).is_file():
        # pre-bootstrap the report has no golden copy yet; readiness
        # refuses the un-provisioned baseline on its own
        snapshot_ids.append(fe.report_id)
    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in snapshot_ids}, GOLDEN_ROOT)
    # tamper sites with no golden mirror (the cheat site sits outside
    # every hash/slice target by design; the sysproof crate is hashed
    # but not snapshot-copied) are restored from a pre-tamper snapshot
    src_backups = {
        f: f.read_text()
        for f, flag in ((MHS_API, cli.tamper_cheat),
                        (MHS_EXTERN, cli.tamper_ffi),
                        (GUMBO_LIB,
                         cli.tamper_broadcast or cli.tamper_stale_dep),
                        (SYS_PROOF_LIB, cli.tamper_proof_count),
                        (SYS_PROOF_VC, cli.tamper_proof_swap))
        if flag
    }
    # the stale-dep restore also restores the file's mtime — but ONLY
    # when the guard did not run: without --fresh-deps the dep caches
    # were never rebuilt (they still hold artifacts of the pre-tamper
    # bytes), so bytes+mtime back leaves them coherent with no rebuild.
    # Under --fresh-deps the guard's bump made every consumer rebuild
    # from the TAMPERED bytes; the restore must carry a fresh mtime, or
    # cargo (freshness is mtime-gated — the scene's whole point) would
    # keep serving the poisoned artifacts over the restored tree
    mtime_backups = ({GUMBO_LIB: GUMBO_LIB.stat().st_mtime_ns}
                     if cli.tamper_stale_dep and not cli.fresh_deps
                     else {})
    for tamper, flag in tampers:
        if flag:
            tamper(fe, protocols)
    if cli.fresh_deps:
        # the guard runs AFTER the tampers, before the episode — it must
        # judge the live (possibly tampered) tree
        fresh_deps_guard()
    try:
        attest_episode(fe, protocols, repair=cli.repair,
                       validate=cli.validate, granularity=granularity,
                       restart=restart, pause=cli.pause, verify=cli.verify,
                       immutable=cli.immutable_model,
                       restore_crates=cli.restore_crates,
                       repair_impl=cli.repair_impl,
                       regen_report=cli.regen_report,
                       regen_gensrc=cli.regen_gensrc,
                       repair_markers=cli.repair_markers,
                       tool_gate=tool_gate)
        if cli.repair and not restart:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(fe, protocols, repair=cli.repair,
                           validate=cli.validate)
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")
        for f, original in src_backups.items():
            if f.read_text() != original:
                f.write_text(original)
                if f in mtime_backups:
                    os.utime(f, ns=(f.stat().st_atime_ns, mtime_backups[f]))
                print(f"Restored {f.name} from the pre-tamper snapshot")


if __name__ == "__main__":
    main()
