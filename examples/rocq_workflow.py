"""
Shared driver for the Rocq attestation examples (phase 1): protocol-dir
generation, provisioning, attestation episodes, and the tamper demos,
parameterized by a per-package RocqExampleConfig. A focused mirror of
examples/lean_workflow.py — same artifact-class organization, adapted to
what the Rocq toolchain gives us.

The protocols are organized by ARTIFACT CLASS, one protocol family per
class:

    <p>_model         the blessed full model: per blessed file, readfile
                      (whole-file content, signed at provisioning — the
                      administrator's blessing) AND hashfile (the cheap
                      episode check), one SIG. Promote-owned: ordinary
                      re-provisioning never refreshes it.
    <p>_contracts     every attributable contract region of the BLESSED
                      files: one readfile_range per top-level declaration,
                      named by declaration. Always-run — contract-region
                      tamper must not hide behind a passing hash tier.
                      (Mutable files — Impl.v, Proofs.v — carry no
                      structural goldens: their attested property is
                      provability, not bytes.)
    <p>_verification  TWO targets in one term, sequenced: `dune build`
                      (every file must elaborate — but `Admitted.` and
                      `Axiom` elaborate cleanly, so this alone proves
                      nothing) then the assumptions audit, `rocq compile`
                      of the package-root Print Assumptions file. The
                      appraiser (run_command_rocq_appr, assumptions mode)
                      requires every audited goal to be "Closed under the
                      global context"; an Admitted proof or a smuggled
                      Axiom anywhere beneath a goal is refuted BY NAME.
                      The rocq/dune toolchain is hashed in the same term,
                      before the invocations (measure-then-use).

Three entries mirror the pipeline: <p>:model (fail -> <p>_contracts
refines the attribution -> [--repair] restore), <p>:contracts always-run
(fail -> [--repair] restore), and <p>:verification ALWAYS-RUN (fail ->
escalate). Unlike the Lean tiers there is no --validate gate: the audit
is cheap, and it is the point of this example — elaboration success is
NOT provability, only the audit separates them.

Scenarios are PURE CONFIGURATION: examples/temp_control_rocq.py is a
thin config module over this driver; nothing here knows the scenario.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    OutOfBandRepairKS,
    ProtocolDir,
    RestartEpisodeKS,
    RocqImplSynthesisKS,
    RocqOutOfBandRepairKS,
    RocqPackageSynthesisKS,
    RocqProofSynthesisKS,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    attestation_request,
    make_provision_predicate,
    make_attestation_predicate,
    make_readiness_predicate,
    readiness_request,
    request_provision,
    splice_proof_rocq,
    stub_impl_axiom,
    trust_summary,
)
from pybb.attestation.copland import with_asp_targids
from pybb.attestation.proof_status import render_checklist, stale_files
from pybb.attestation.props import write_model_protocol_dir
from pybb.attestation.rocq_status import rocq_goal_checklist
from pybb.attestation.targetmap import (
    build_term,
    derive_targets_from_rocq,
    rocq_decl_spans,
)
from pybb.attestation.tools import (
    ASP_USES,
    register_tool,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
EVIDENCE_DIR = REPO / "evidence"  # per-episode archived responses (gzipped)
CONTRACTS_TEMPLATE = "temp_control_aadl_slang_l2"  # session/manifest shape
WORKSPACE_BIN = Path.home() / "Claude_workspace" / "bin"
OPAM_BIN = Path.home() / ".opam" / "5.2" / "bin"

# Just-in-time tool measurement: the rocq toolchain (workspace wrappers ->
# pinned opam-switch binaries) is hashed IN THE SAME TERM as the
# verification tier's tool invocations, sequenced before the uses. Same
# cadence knob as the Lean driver; phase 1 uses the default.
TOOL_CADENCE = "per_use"

_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}
TIER_SESSION = {
    "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": {
            "run_command_dune": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "run_command_rocq": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "run_command_rocq_appr": {
                # EXTEND: the appraiser retains the evidence it judged, so
                # the tool's output survives into the episode response and
                # the verified appraisal summary lifts it per entry
                # (ComponentResult.measured_b64) — the per-target join
                # material
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
        },
        # one companion appraises both command ASPs: build mode (no
        # `goals` in the target's args) for dune, assumptions mode
        # (`goals` present) for the audit
        "ASP_Comps": {"run_command_dune": "run_command_rocq_appr",
                      "run_command_rocq": "run_command_rocq_appr"},
    },
}
TIER_MANIFEST = {"ASPS": ["run_command_dune", "run_command_rocq",
                          "run_command_rocq_appr"],
                 "ASP_FS_MAP": {}, "POLICY": []}


def rocq_artifacts() -> list:
    """The rocq/dune invocation chain: workspace wrappers (the names the
    CVM's forked ASPs resolve via path_prepend) -> the pinned opam-switch
    binaries the wrappers exec."""
    return [str(p) for p in (
        WORKSPACE_BIN / "rocq",
        WORKSPACE_BIN / "dune",
        OPAM_BIN / "rocq",
        OPAM_BIN / "dune",
    )]


@dataclass
class RocqExampleConfig:
    """One Rocq scenario: everything the driver needs, nothing else."""

    prefix: str            # protocol-id prefix and entry namespace
    package_root: Path     # the vendored dune project
    theory_name: str       # dune coq.theory name (the audit's -R mapping)
    blessed_rels: list     # blessed files, relative (statements + binding)
    audit_rel: str         # Print Assumptions file at the PACKAGE ROOT,
                           # outside the theory (dune is silent on warm
                           # builds; the audit must recompile every run)
    audit_goals: list      # goal names in audit order — the appraiser's
                           # assumptions-mode args: one Print Assumptions
                           # section per goal, every one must be closed
    tamper_targ: str       # contracts slice whose last line --tamper corrupts
    proofs_rel: str        # mutable proofs file the semantic tampers edit
    tamper_admitted_decl: str  # theorem --tamper-admitted admits
    tamper_axiom_decl: str     # theorem --tamper-axiom discharges by postulate
    tamper_axiom_name: str     # the smuggled axiom's name (the audit names it)
    tamper_axiom_stmt: str     # the smuggled Axiom declaration, verbatim
    restart_budget: int = None  # when set, --repair chains end in a
                                # RestartEpisodeKS: the repair is judged by
                                # fresh measurement IN-SESSION (one run)

    # ── goal-directed workflow knobs (default None/"" = unavailable) ──────
    bless_lint: object = None     # callable(cfg), invoked before the model
                                  # class is (re)blessed; raises to refuse
    binding_goal: str = "acceptance"    # the audit goal whose section is
                                        # the "Spec bound (acceptance)" row
    binding_witness: str = "spec_holds" # the proofs-file obligation witness
    impl_rel: str = ""            # the implementation source file (mutable)
    impl_name: str = ""           # the implementation the goals quantify over
    synthesis_engines: list = None  # --synthesize's engine ladder (callables,
                                  # GoalContext -> candidate inner scripts);
                                  # None = --synthesize unavailable
    break_proof_decl: str = ""    # --break-proof's target: the seed theorem
                                  # whose proof body gets corrupted

    def __post_init__(self) -> None:
        self.package_root = Path(self.package_root)
        # idempotent registration: ASP_USES is module state, so guard the
        # used_by append against repeated config construction
        register_tool("rocq", rocq_artifacts, used_by=[
            asp for asp in ("run_command_dune", "run_command_rocq")
            if "rocq" not in ASP_USES.get(asp, [])])

    # ── derived identity: one protocol per artifact class ─────────────────
    @property
    def model_id(self) -> str: return f"{self.prefix}_model"

    @property
    def contracts_id(self) -> str: return f"{self.prefix}_contracts"

    @property
    def verification_id(self) -> str: return f"{self.prefix}_verification"

    @property
    def protocol_ids(self) -> tuple:
        return (self.model_id, self.contracts_id)

    @property
    def all_ids(self) -> tuple:
        return (*self.protocol_ids, self.verification_id)

    @property
    def model_files(self) -> list:
        return [str(self.package_root / r) for r in self.blessed_rels]

    @property
    def proofs_file(self) -> Path:
        return self.package_root / self.proofs_rel

    @property
    def props_rel(self) -> str:
        """The blessed statements file (checklist rows, engine context)."""
        return self.blessed_rels[0]

    @property
    def props_file(self) -> Path:
        return self.package_root / self.props_rel

    def entry(self, question: str) -> str:
        return f"{self.prefix}:{question}"

    # ── tier config (the AM-owned protocol definitions) ───────────────────
    @property
    def build_targ(self) -> str:
        return f"{self.prefix}_build_verification_targ"

    @property
    def assumptions_targ(self) -> str:
        return f"{self.prefix}_assumptions_verification_targ"

    @property
    def verification_targets(self) -> dict:
        """{asp_id: {targ: args}} in EXECUTION ORDER: the build first (the
        audit reads the theory's compiled .vo files from _build), then the
        assumptions audit. The audit target's `goals` list IS the
        appraiser's assumptions-mode configuration — build mode carries no
        goals key, so a clean exit judges the build."""
        return {
            "run_command_dune": {self.build_targ: {
                "exe_args": ["build"],
                "cwd": str(self.package_root)}},
            "run_command_rocq": {self.assumptions_targ: {
                "exe_args": ["compile",
                             "-R", f"_build/default/{self.theory_name}",
                             self.theory_name, self.audit_rel],
                "cwd": str(self.package_root),
                "goals": list(self.audit_goals)}},
        }

    @property
    def tier_meta(self) -> dict:
        # display name carries no prefix — the protocol id disambiguates
        return {
            self.verification_id: {
                "name": "Rocq Proof Verification (verification class)",
                "description":
                    "Runs `dune build` (every file must elaborate) then the "
                    f"assumptions audit (`rocq compile {self.audit_rel}`, one "
                    "Print Assumptions per blessed goal). Elaboration alone "
                    "proves nothing — `Admitted.` and `Axiom` compile with "
                    "exit 0 — so the appraiser requires every goal to be "
                    "closed under the global context, and a refusal names "
                    "the goal and the axioms it leans on. The rocq/dune "
                    "toolchain is hashed in the same term, before the "
                    "invocations (measure-then-use).",
            },
        }


# ── protocol-dir generation ───────────────────────────────────────────────────

def _tier_term(targets_by_asp: dict) -> dict:
    """lseq( bseq_chain(ASPC...), APPR ) over {asp_id: {targ: args}},
    preserving asp/target order — the build must precede the audit."""
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": targ,
                         "ASP_ARGS": args}}}
        for asp_id, targets in targets_by_asp.items()
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [acc, _APPR]}


def build_tier_protocol_dir(cfg: RocqExampleConfig) -> None:
    """(Re)generate the verification dir from the config, with tool
    measurements woven in per TOOL_CADENCE."""
    targets_by_asp = {asp_id: with_asp_targids(targets)
                      for asp_id, targets in cfg.verification_targets.items()}
    asp_args = {asp_id: dict(targets)
                for asp_id, targets in targets_by_asp.items()}
    term = _tier_term(targets_by_asp)
    session, manifest = TIER_SESSION, TIER_MANIFEST
    if TOOL_CADENCE == "per_use":
        asp_args, term, session, manifest = weave_tool_measurements(
            asp_args, term, session, manifest)
    d = FIXTURES / cfg.verification_id
    d.mkdir(exist_ok=True)
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(
        json.dumps(cfg.tier_meta[cfg.verification_id], indent=2) + "\n")
    n_cmds = sum(len(t) for a, t in asp_args.items() if a != "hashfile")
    n_tools = len(asp_args.get("hashfile", {}))
    print(f"  {cfg.verification_id}: {n_cmds} targets"
          + (f" + {n_tools} woven tool measurements" if n_tools else ""))


def build_protocol_dirs(cfg: RocqExampleConfig,
                        bless_model: bool = False) -> dict:
    """(Re)generate the artifact-class protocol dirs. The model class is
    AM-owned: rewritten only when blessing is requested or when missing
    entirely (bootstrap) — an ordinary --provision keeps the existing
    blessing untouched."""
    derived = derive_targets_from_rocq(cfg.package_root, prefix=cfg.prefix,
                                       files=cfg.model_files)
    protocols = {}
    d = FIXTURES / cfg.contracts_id
    d.mkdir(exist_ok=True)
    for f in ("session.json", "manifest.json"):
        shutil.copy2(FIXTURES / CONTRACTS_TEMPLATE / f, d / f)
    asp_args = derived[cfg.contracts_id]
    (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
    (d / "term.json").write_text(json.dumps(build_term(asp_args)) + "\n")
    protocols[cfg.contracts_id] = ProtocolDir.load(str(d))
    print(f"  {cfg.contracts_id}: "
          f"{sum(len(t) for t in asp_args.values())} declaration slices from scan")
    model_dir = FIXTURES / cfg.model_id
    if bless_model or not (model_dir / "asp_args.json").is_file():
        blessed = ", ".join(Path(f).name for f in cfg.model_files)
        write_model_protocol_dir(
            model_dir, cfg.prefix, cfg.model_files,
            "The MODEL class: whole-file signed content (the "
            f"administrator's blessing) and hash of {blessed}. Episodes "
            "check the live model against the blessed content and hash; "
            "baseline verification checks that every declaration-slice "
            "golden is derivable from the blessed bytes.")
        print(f"  {cfg.model_id}: {len(cfg.model_files)} blessed model file(s)")
    else:
        print(f"  {cfg.model_id}: existing blessing kept")
    protocols[cfg.model_id] = ProtocolDir.load(str(model_dir))
    build_tier_protocol_dir(cfg)
    protocols[cfg.verification_id] = ProtocolDir.load(
        str(FIXTURES / cfg.verification_id))
    return protocols


def load_protocols(cfg: RocqExampleConfig) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in cfg.all_ids):
        print(f"{cfg.prefix} protocol dirs missing — generating from the "
              "syntax scan")
        return build_protocol_dirs(cfg)
    return {pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in cfg.all_ids}


# ── provisioning ──────────────────────────────────────────────────────────────

def provision_flow(cfg: RocqExampleConfig, protocols: dict,
                   bless_model: bool = False) -> None:
    """Capture golden and provision on the blackboard: the contracts
    class and — with woven tool measurements — the verification tier,
    whose tool hash goldens land measure-in-place (live artifacts, no
    golden copies). The MODEL class is provisioned ONLY when blessing is
    requested or when it has never been blessed (bootstrap): re-signing
    the model is the administrator's sanctioning act, so ordinary
    re-provisioning — including a laundering pass — cannot refresh it."""
    model = protocols.get(cfg.model_id)
    model_unblessed = model is not None and not any(
        a.get("golden_b64")
        for a in model.asp_args.get("readfile", {}).values())
    pids = [cfg.contracts_id]
    if model is not None and (bless_model or model_unblessed):
        if cfg.bless_lint is not None:
            cfg.bless_lint(cfg)  # raises to refuse the blessing
        pids.append(cfg.model_id)
    measured = {pid: protocols[pid] for pid in pids}
    verification = protocols.get(cfg.verification_id)
    if verification is not None and "hashfile" in verification.asp_args:
        measured[cfg.verification_id] = verification
    snapshot = TargetSnapshot.capture(measured, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files")
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, measured, GOLDEN_ROOT))
    for pid in measured:
        request_provision(ctl.blackboard, pid)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")


# ── tamper demos ──────────────────────────────────────────────────────────────

def tamper(cfg: RocqExampleConfig, protocols: dict) -> None:
    """Corrupt the last line of a named blessed-declaration slice — the
    structural tamper: the contracts class attributes it BY NAME."""
    args = protocols[cfg.contracts_id].asp_args["readfile_range"][cfg.tamper_targ]
    spec = Path(args["filepath"])
    lines = spec.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  (* TAMPERED: blessed statement weakened *)\n"
    spec.write_text("".join(lines))
    print(f"Tampered blessed slice: {spec.name} line {args['end_index']} "
          f"({args['metadata']})")


def _splice_proof_body(cfg: RocqExampleConfig, decl: str,
                       replacement: str, prelude: str = "") -> bytes:
    """Snapshot the mutable proofs file, then rewrite the named theorem's
    proof block (`Proof.` through `Qed.`) to `replacement`, optionally
    inserting `prelude` (e.g. a smuggled Axiom) as its own block just
    above the theorem. Statement untouched. Returns the pristine bytes —
    every tamper flow restores them in a finally."""
    path = cfg.proofs_file
    original = path.read_bytes()
    lines = original.decode().splitlines(keepends=True)
    span = next((s for s in rocq_decl_spans(original.decode())
                 if s[1] == decl), None)
    if span is None:
        raise SystemExit(f"{cfg.proofs_rel}: declaration '{decl}' not found")
    _kind, _name, start, end = span  # 1-based inclusive
    block = lines[start - 1:end]
    proof_at = next((i for i, l in enumerate(block)
                     if l.strip().startswith("Proof.")), None)
    if proof_at is None:
        raise SystemExit(f"{cfg.proofs_rel}: '{decl}' has no Proof. block")
    new_block = [*block[:proof_at],
                 *[l + "\n" for l in replacement.splitlines()]]
    prelude_lines = [l + "\n" for l in prelude.splitlines()] + ["\n"] \
        if prelude else []
    lines[start - 1:end] = [*prelude_lines, *new_block]
    path.write_text("".join(lines))
    return original


def tamper_admitted(cfg: RocqExampleConfig) -> bytes:
    """Replace the target theorem's proof with `Admitted.` — the honest
    unfinished proof. The build stays green (Admitted elaborates with
    exit 0); only the assumptions audit refutes it, naming the goal."""
    original = _splice_proof_body(cfg, cfg.tamper_admitted_decl,
                                  "Proof.\nAdmitted.")
    print(f"Admitted the proof of '{cfg.tamper_admitted_decl}' in "
          f"{cfg.proofs_rel} (statement untouched — the build will PASS)")
    return original


def tamper_axiom(cfg: RocqExampleConfig) -> bytes:
    """The headline tamper: smuggle an Axiom asserting exactly the goal,
    then 'prove' the theorem by it. Every file elaborates cleanly — no
    Admitted, no sorry-analogue, nothing structural moved — and the
    assumptions audit still refutes the goal, naming the smuggled axiom."""
    original = _splice_proof_body(
        cfg, cfg.tamper_axiom_decl,
        f"Proof. exact {cfg.tamper_axiom_name}. Qed.",
        prelude=cfg.tamper_axiom_stmt)
    print(f"Smuggled '{cfg.tamper_axiom_stmt}' into {cfg.proofs_rel} and "
          f"discharged '{cfg.tamper_axiom_decl}' by it (elaborates CLEANLY)")
    return original


# ── the progress view (--status / --ready) ────────────────────────────────────

def _blessed_text(cfg: RocqExampleConfig, protocols: dict) -> str:
    import base64
    for args in protocols[cfg.model_id].asp_args.get("readfile", {}).values():
        if args.get("filepath") == str(cfg.props_file) and args.get("golden_b64"):
            return base64.b64decode(args["golden_b64"]).decode()
    raise SystemExit(f"{cfg.model_id}: {cfg.props_rel} is not blessed — "
                     "run --provision first")


def _checklist(cfg: RocqExampleConfig, protocols: dict, verdict):
    return rocq_goal_checklist(
        _blessed_text(cfg, protocols), verdict, cfg.build_targ,
        cfg.assumptions_targ, cfg.audit_goals, cfg.binding_goal,
        cfg.proofs_file, cfg.package_root / cfg.audit_rel)


def status_flow(cfg: RocqExampleConfig, protocols: dict, ready: bool,
                status: bool) -> None:
    """The goals progress view, same semantics as the Lean driver's:
    QUICK by default (one verification run — the checklist rows come
    from the blessed Spec's signed bytes, the cells from the audit's
    per-goal sections, downgrade-only). --ready additionally runs the
    readiness gate first — alone it just prints the report; combined
    with --status a failure poisons every cell to '?'."""
    report = None
    if ready:
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
    if not status:
        return
    verdict = make_attestation_predicate(CvmSubprocessClient(), protocols)(
        attestation_request(cfg.verification_id))
    checklist = _checklist(cfg, protocols, verdict)
    if ready and not report:
        problems = "; ".join((*report.problems, *report.baseline_problems))
        checklist = checklist.poison(f"readiness failed: {problems[:200]}")
    elif ready:
        checklist = checklist.model_copy(update={"trusted": True})
    print(render_checklist(checklist))


# ── goal-directed synthesis (--synthesize) ────────────────────────────────────

def _stub_proofs(cfg: RocqExampleConfig,
                 kinds: tuple = ("Theorem", "Lemma")) -> bytes:
    """Snapshot the live proofs file, then stub every named proof body
    of the given declaration kinds to `Admitted.` (statements kept —
    the goal-directed starting state: goals blessed, nothing proved;
    every stub COMPILES, only the audit refutes it). The impl-first arc
    widens `kinds` to the Example vectors too: they are kernel-COMPUTED
    (`reflexivity` through the implementation), so they cannot elaborate
    over an admitted-axiom impl — and the arc's premise is that nothing
    exists beyond the blessed properties. Returns the snapshot."""
    path = cfg.proofs_file
    original = path.read_bytes()
    text = original.decode()
    names = [n for k, n, _s, _e in rocq_decl_spans(text)
             if k in kinds and n]
    for n in names:
        text = splice_proof_rocq(text, n, "Admitted.")
    path.write_text(text)
    print(f"Stubbed {len(names)} proofs to Admitted in {cfg.proofs_rel} "
          "(the build stays green — the audit is what refutes them)")
    return original


def _stub_impl(cfg: RocqExampleConfig) -> bytes:
    """Snapshot the implementation file, then stub the implementation to
    the impl-as-axiom form — `Definition <name> ... : T.` +
    `Proof. Admitted.` (signature kept; the body becomes an axiom:
    "unimplemented" and "unprovable" are the same kernel judgment).
    Returns the snapshot.

    Paired with _stub_proofs this is the impl-first starting state: the
    administrator has blessed WHAT MUST HOLD and nothing else exists."""
    path = cfg.package_root / cfg.impl_rel
    original = path.read_bytes()
    path.write_text(stub_impl_axiom(original.decode(), cfg.impl_name))
    print(f"Stubbed the implementation '{cfg.impl_name}' to an admitted "
          f"axiom in {cfg.impl_rel} (signature kept)")
    return original


def _break_proof(cfg: RocqExampleConfig) -> bytes:
    """Snapshot the proofs file, then corrupt ONE seed proof body with a
    wrong-but-well-formed tactic script (statement untouched, no
    Admitted) — the repair starting state: the BUILD fails with real
    error positions. Returns the snapshot."""
    path = cfg.proofs_file
    original = path.read_bytes()
    path.write_text(splice_proof_rocq(original.decode(), cfg.break_proof_decl,
                                      "  intros. reflexivity."))
    print(f"Broke the proof of '{cfg.break_proof_decl}' in "
          f"{cfg.proofs_rel} (wrong tactic — statement untouched)")
    return original


def _closing_verdict(cfg: RocqExampleConfig, protocols: dict, verdict,
                     escalated: bool):
    """The verdict the closing report should be read from.

    A synthesis KS spends a restart only once the whole audit is
    locally clean, so a run that ends short — escalated with goals
    still open — leaves accepted candidates no attestation ever saw.
    The Rocq audit's args disclose only Assumptions.v (which never
    moves), so the Lean driver's digest-staleness test cannot see
    proofs-file motion here: an escalated entry re-measures instead
    (one warm run), buying a closing report that describes the tree
    the operator is actually left with."""
    audit = next((c for c in verdict.components
                  if c.targ_id == cfg.assumptions_targ), None)
    if not escalated and (audit is None or not stale_files(audit)):
        return verdict
    print("\nre-measuring for the closing report: the last attested verdict "
          "may predate accepted candidates")
    return make_attestation_predicate(CvmSubprocessClient(), protocols)(
        attestation_request(cfg.verification_id))


def synthesize_flow(cfg: RocqExampleConfig, protocols: dict,
                    keep: bool, engines: list = None,
                    stub: str = "admits",
                    impl_engines: list = None,
                    package_engines: list = None,
                    pause: bool = False, gate=None) -> BlackboardController:
    """The step-4 loop, Rocq edition: stub the seeds, put
    :model/:contracts/:verification on the board, and let
    RocqProofSynthesisKS work the open goals — engines splice inner
    tactic scripts, bare dune + the assumptions audit judge locally
    (free), and each locally-clean state spends ONE restart to be
    judged by fresh measurement. Ends in good standing or escalates
    with the checklist of what remains.

    stub="impl" is the IMPL-FIRST arc: the implementation becomes an
    admitted axiom alongside the admitted proofs, and
    RocqImplSynthesisKS is chained ahead of the proof rung — the
    blessed properties alone must yield first an implementation, then
    proofs about it. stub="package" starts from the same stubs but
    routes ONE RocqPackageSynthesisKS instead of the two-rung chain:
    a single black box writes the implementation and the proofs
    together, judged by the same local senses and the same restart.
    stub="break" corrupts one seed proof instead (the repair arc)."""
    proofs_path = cfg.proofs_file
    impl_path = cfg.package_root / cfg.impl_rel if cfg.impl_rel else None
    impl_original = _stub_impl(cfg) if stub in ("impl", "package") else None
    original = _break_proof(cfg) if stub == "break" else _stub_proofs(
        cfg, kinds=(("Theorem", "Lemma", "Example")
                    if stub in ("impl", "package")
                    else ("Theorem", "Lemma")))
    context_rels = [r for r in (cfg.props_rel, cfg.impl_rel) if r]
    try:
        controller = BlackboardController()
        client = CvmSubprocessClient()
        controller.register_predicate(
            "attestation", make_attestation_predicate(client, protocols,
                                                      archive_dir=EVIDENCE_DIR))
        controller.register_predicate(
            "protocol_check", make_readiness_predicate(
                protocols, baseline_root=GOLDEN_ROOT, client=client))
        if stub == "package":
            chain = [RocqPackageSynthesisKS(
                engines=package_engines or [],
                blessed=lambda: _blessed_text(cfg, protocols),
                package_root=str(cfg.package_root),
                impl_rel=cfg.impl_rel, proofs_rel=cfg.proofs_rel,
                impl_name=cfg.impl_name,
                spec_rel=cfg.props_rel,
                theory_name=cfg.theory_name,
                audit_rel=cfg.audit_rel,
                audit_goals=list(cfg.audit_goals),
                rocq=str(WORKSPACE_BIN / "rocq"),
                dune=str(WORKSPACE_BIN / "dune"))]
        else:
            synth = RocqProofSynthesisKS(
                engines=(engines if engines is not None
                         else cfg.synthesis_engines),
                blessed=lambda: _blessed_text(cfg, protocols),
                package_root=str(cfg.package_root),
                proofs_rel=cfg.proofs_rel,
                theory_name=cfg.theory_name,
                audit_rel=cfg.audit_rel,
                audit_goals=list(cfg.audit_goals),
                build_targ=cfg.build_targ,
                audit_targ=cfg.assumptions_targ,
                binding_witness=cfg.binding_witness,
                impl_name=cfg.impl_name,
                context_rels=context_rels,
                rocq=str(WORKSPACE_BIN / "rocq"),
                dune=str(WORKSPACE_BIN / "dune"))
            impl_synth = RocqImplSynthesisKS(
                engines=impl_engines or [],
                blessed=lambda: _blessed_text(cfg, protocols),
                package_root=str(cfg.package_root),
                impl_rel=cfg.impl_rel, impl_name=cfg.impl_name,
                spec_rel=cfg.props_rel,
                theory_name=cfg.theory_name,
                audit_rel=cfg.audit_rel,
                audit_goals=list(cfg.audit_goals),
                rocq=str(WORKSPACE_BIN / "rocq"),
                dune=str(WORKSPACE_BIN / "dune")) if stub == "impl" else None
            chain = [ks for ks in (impl_synth, synth) if ks is not None]
        if pause:
            # the human rung before escalation: engines first, then the
            # operator (or an interactive agent session) on whatever
            # remains open — judged by the same restart
            chain = [*chain, _pause_rung(cfg, gate)]
        episodes = {cfg.entry("model"): cfg.model_id,
                    cfg.entry("contracts"): cfg.contracts_id,
                    cfg.entry("verification"): cfg.verification_id}
        starter = StartAttestationKS(episodes=episodes)
        for ks in (*chain, starter):
            controller.add_ks(ks)
        controller.route(cfg.entry("model"), on_pass=[], on_fail=[])
        controller.route(cfg.entry("contracts"), on_pass=[], on_fail=[])
        controller.route(cfg.entry("verification"), on_pass=[], on_fail=chain)
        controller.blackboard.write_entry(
            key=cfg.entry("ready"), predicate="protocol_check",
            measurement=readiness_request(list(protocols)))
        controller.route(cfg.entry("ready"), on_pass=[starter], on_fail=[])
        controller.run()
        print(trust_summary(controller.blackboard,
                            semantic=[cfg.verification_id]))
        key = cfg.entry("verification")
        entry = controller.blackboard.entries.get(key) \
            or controller.blackboard.escalate.get(key)
        if entry is not None and entry.result is not None:
            verdict = _closing_verdict(
                cfg, protocols, entry.result,
                escalated=key in controller.blackboard.escalate)
            print(render_checklist(_checklist(cfg, protocols, verdict)))
        return controller
    finally:
        if keep:
            print(f"\n--keep: synthesized proofs left in {cfg.proofs_rel}")
            if impl_original is not None:
                print(f"--keep: synthesized implementation left in "
                      f"{cfg.impl_rel}")
        else:
            proofs_path.write_bytes(original)
            print(f"\nRestored seed proofs in {cfg.proofs_rel}")
            if impl_original is not None:
                impl_path.write_bytes(impl_original)
                print(f"Restored the seed implementation in {cfg.impl_rel}")


# ── episodes ──────────────────────────────────────────────────────────────────

def _pause_rung(cfg: RocqExampleConfig, gate=None) -> RocqOutOfBandRepairKS:
    """The audit-aware pause rung for the :verification chain: blocks for
    out-of-band repair (editor, interactive agent session), lets the
    operator iterate for free against the live audit, and spends a
    restart only on a locally-clean tree."""
    return RocqOutOfBandRepairKS(
        gate=gate, package_root=str(cfg.package_root),
        theory_name=cfg.theory_name, audit_rel=cfg.audit_rel,
        audit_goals=list(cfg.audit_goals),
        rocq=str(WORKSPACE_BIN / "rocq"), dune=str(WORKSPACE_BIN / "dune"))


def attest_episode(cfg: RocqExampleConfig, protocols: dict,
                   repair: bool, pause: bool = False,
                   gate=None) -> BlackboardController:
    """One attestation episode. The verification class is ALWAYS-RUN —
    the audit is cheap and it is the point of this example; its failures
    escalate directly (a refuted proof is not golden-restorable).

    pause=True inserts out-of-band repair rungs: on :model/:contracts a
    generic OutOfBandRepairKS ahead of the automatic golden restore (the
    operator gets first claim; skipping falls through to the restore),
    and on :verification the audit-aware rung — the one failure class
    with no automatic repair at all. Every out-of-band fix is judged
    by fresh measurement, never by the operator's word."""
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols,
                                                  archive_dir=EVIDENCE_DIR))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    restore = [WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                  refined_by=cfg.contracts_id)] if repair else []
    if repair and cfg.restart_budget:
        # judged-by-fresh-measurement repair: the chain ends by requesting a
        # fresh episode instead of escalating "pending next episode". The
        # verification entry rides along (`also`): it is ALWAYS-RUN, so a
        # blessed-file tamper fails it too — its verdict was measured over
        # the pre-repair tree, and without the sibling restart it would
        # stay escalated while model/contracts recover, leaving episode 2
        # only two-thirds good-standing.
        restore = [*restore, RestartEpisodeKS(
            budget=cfg.restart_budget, also=[cfg.entry("verification")])]
    oob = [OutOfBandRepairKS(gate=gate,
                             also=[cfg.entry("verification")])] if pause else []
    ver_chain = [_pause_rung(cfg, gate)] if pause else []
    model_fail = [TierKS(protocol_id=cfg.contracts_id), *oob, *restore]
    episodes = {cfg.entry("model"): cfg.model_id,
                cfg.entry("contracts"): cfg.contracts_id,
                cfg.entry("verification"): cfg.verification_id}
    starter = StartAttestationKS(episodes=episodes)
    for ks in (*model_fail, *ver_chain, starter):
        controller.add_ks(ks)
    controller.route(cfg.entry("model"), on_pass=[], on_fail=model_fail)
    controller.route(cfg.entry("contracts"), on_pass=[],
                     on_fail=[*oob, *restore])
    controller.route(cfg.entry("verification"), on_pass=[], on_fail=ver_chain)
    controller.blackboard.write_entry(
        key=cfg.entry("ready"), predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route(cfg.entry("ready"), on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard,
                        semantic=[cfg.verification_id]))
    return controller


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_cli(cfg: RocqExampleConfig, description: str) -> None:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--tamper", action="store_true",
                        help="corrupt one blessed statement slice live — "
                             "the contracts attribution names it")
    parser.add_argument("--tamper-admitted", action="store_true",
                        help="replace one proof with Admitted. — the build "
                             "passes, the assumptions audit refutes the goal")
    parser.add_argument("--tamper-axiom", action="store_true",
                        help="smuggle an Axiom asserting the goal and prove "
                             "by it — elaborates cleanly, the audit names "
                             "the axiom")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--pause", action="store_true",
                        help="on failure, pause the episode for out-of-band "
                             "repair (hand edit, interactive agent session, "
                             "...) instead of / ahead of the automatic "
                             "rungs; the fix is judged by fresh measurement, "
                             "never by the operator's word")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--ready", action="store_true")
    parser.add_argument("--synthesize", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--llm", choices=("anthropic", "openai"),
                        help="explicit confirmation: arm the LLM engine "
                             "against this provider (keys from the "
                             "environment only)")
    parser.add_argument("--llm-only", action="store_true",
                        help="leave the tactic portfolio off the ladder so "
                             "the LLM genuinely does the proving")
    parser.add_argument("--llm-model", metavar="ID",
                        help="override the provider's default model "
                             "(e.g. gpt-5.1)")
    parser.add_argument("--llm-max-tokens", type=int, metavar="N",
                        help="per-call completion budget (reasoning models "
                             "spend most of it on reasoning tokens)")
    parser.add_argument("--llm-effort",
                        choices=("none", "low", "medium", "high"),
                        help="OpenAI reasoning_effort: gpt-5* models do NOT "
                             "reason on this endpoint unless it is set — "
                             "this is the knob that buys thinking, and the "
                             "one that drives cost")
    parser.add_argument("--llm-dry-run", action="store_true",
                        help="predict the spend: run the flow with a "
                             "no-network stand-in that records every prompt "
                             "and yields no candidate, so the reported call "
                             "count is the worst-case ceiling")
    parser.add_argument("--break-proof", action="store_true",
                        help="repair arc: corrupt one seed proof body "
                             "(implies a synthesis episode)")
    parser.add_argument("--synthesize-impl", action="store_true",
                        help="impl-first arc: stub the implementation to an "
                             "admitted axiom AND every proof to Admitted, "
                             "then derive the implementation from the "
                             "blessed properties alone before proving "
                             "anything about it")
    parser.add_argument("--synthesize-package", action="store_true",
                        help="whole-package arc: same starting stubs as "
                             "--synthesize-impl, but ONE black box writes "
                             "the implementation and all proofs together "
                             "(complete file contents), instead of the "
                             "impl-then-proofs rung chain; requires --llm")
    cli = parser.parse_args()

    if sum((cli.tamper, cli.tamper_admitted, cli.tamper_axiom)) > 1:
        parser.error("pick one tamper arc per run")
    if cli.break_proof:
        cli.synthesize = True
    if cli.synthesize_impl:
        cli.synthesize = True
        if cli.break_proof:
            parser.error("--synthesize-impl and --break-proof are different "
                         "starting states; pick one")
        if not (cfg.impl_rel and cfg.impl_name):
            parser.error("--synthesize-impl: this scenario has no "
                         "implementation file configured (impl_rel/impl_name)")
    if cli.synthesize_package:
        cli.synthesize = True
        if cli.synthesize_impl or cli.break_proof:
            parser.error("--synthesize-package, --synthesize-impl and "
                         "--break-proof are different arcs; pick one")
        if not (cfg.impl_rel and cfg.impl_name):
            parser.error("--synthesize-package: this scenario has no "
                         "implementation file configured (impl_rel/impl_name)")
    if cli.keep and not cli.synthesize:
        parser.error("--keep retains --synthesize's proofs; use them together")
    if cli.llm_only and not cli.llm:
        parser.error("--llm-only requires --llm (the explicit LLM opt-in)")
    for flag in ("llm_model", "llm_max_tokens", "llm_dry_run", "llm_effort"):
        if getattr(cli, flag) and not cli.llm:
            parser.error(f"--{flag.replace('_', '-')} tunes the armed LLM "
                         "engine; use it with --llm")
    if cli.llm and not cli.synthesize:
        parser.error("--llm arms the synthesis engines; use it with "
                     "--synthesize or --break-proof")
    if cli.synthesize:
        if cfg.synthesis_engines is None:
            parser.error("--synthesize: this scenario has no synthesis "
                         "engines configured")
        if cli.synthesize_impl and not cli.llm:
            parser.error("--synthesize-impl currently has only the LLM "
                         "implementation engine; use it with --llm")
        if cli.synthesize_package and not cli.llm:
            parser.error("--synthesize-package currently has only the LLM "
                         "package engine; use it with --llm")
        engines = None
        impl_engines = None
        package_engines = None
        backend = None
        if cli.llm:
            from pybb.attestation.llm_backends import arm_llm_engines
            from pybb.attestation.rocq_synthesis import (
                RocqLlmEngine, RocqLlmImplEngine, RocqLlmPackageEngine)
            engines, impl_engines, backend = arm_llm_engines(
                cli, cfg.synthesis_engines, RocqLlmEngine, RocqLlmImplEngine)
            if cli.synthesize_package:
                package_engines = [RocqLlmPackageEngine(complete=backend,
                                                        attempts=3)]
        stub = ("package" if cli.synthesize_package
                else "impl" if cli.synthesize_impl
                else "break" if cli.break_proof else "admits")
        try:
            synthesize_flow(cfg, load_protocols(cfg), keep=cli.keep,
                            engines=engines, stub=stub,
                            impl_engines=impl_engines,
                            package_engines=package_engines,
                            pause=cli.pause)
        finally:
            report = getattr(backend, "report", None) or getattr(
                getattr(backend, "usage", None), "report", None)
            if report is not None:
                print(f"\n{report()}")
        return
    if cli.status or cli.ready:
        status_flow(cfg, load_protocols(cfg), ready=cli.ready,
                    status=cli.status)
        return

    if cli.provision:
        protocols = build_protocol_dirs(cfg)
        provision_flow(cfg, protocols)
        return

    protocols = load_protocols(cfg)
    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in cfg.protocol_ids}, GOLDEN_ROOT)
    pristine_proofs = None
    if cli.tamper:
        tamper(cfg, protocols)
    elif cli.tamper_admitted:
        pristine_proofs = tamper_admitted(cfg)
    elif cli.tamper_axiom:
        pristine_proofs = tamper_axiom(cfg)
    try:
        attest_episode(cfg, protocols, repair=cli.repair, pause=cli.pause)
        if cli.repair and not cfg.restart_budget:
            # without a restart budget, verification arrives in a fresh run
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(cfg, protocols, repair=cli.repair)
    finally:
        if pristine_proofs is not None:
            cfg.proofs_file.write_bytes(pristine_proofs)
            print(f"\nRestored pristine {cfg.proofs_rel}")
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")
