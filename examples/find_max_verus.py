"""
find-max_Verus — ATTESTED AutoVerus repair: apk's AutoVerusRepairKS as
the repair rung on an attestation entry, with the DEFINITIVE Verus run
performed by the CVM in a fresh episode (restart-episode primitive).

    find_max_verus:ready  readiness + signed-baseline verification
    find_max_verus:proof  eval find_max_verus_check: the CVM runs
                          `verus targets/find-max-verus/find_max.rs
                          --output-json` with the verus toolchain hashed
                          in the same term (measure-then-use), SIG, APPR
                          (run_command_verus_appr: errors == 0)
      fail -> AutoVerusRepairKS (reattest mode): AutoVerus iterates
              INTERNALLY (--repair-steps), writes the repaired source,
              cheat-gates it (assume(/admit() refuses re-attestation),
              then requests a restart — the fresh episode's attested
              Verus run is the only judge of the repair

The division of labor: repair repetition happens inside the knowledge
source (AutoVerus's own loop); attestation happens after, in-episode,
via restart. The repair's word is worthless; the fresh measurement rules.

LLM SAFETY: AutoVerus calls the OpenAI API. Nothing here does that
without the explicit --autoverus flag, which arms the KS's allow_llm
latch after printing what will run. The key is read from the
OPENAI_API_KEY environment variable ONLY — never accepted as an
argument, stored, or logged (the config handed to AutoVerus carries an
empty key field; the key crosses the subprocess boundary via env).

Usage:
    python examples/find_max_verus.py --provision   # tool goldens + blessing
    python examples/find_max_verus.py               # clean attested episode
    python examples/find_max_verus.py --tamper      # drift -> escalation
    python examples/find_max_verus.py --tamper --autoverus \\
        [--repair-steps N] [--keep]                 # drift -> LLM repair ->
                                                    # definitive attested run
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from pybb import BlackboardController  # noqa: E402
from pybb.attestation import (  # noqa: E402
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    make_attestation_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.copland import with_asp_targids  # noqa: E402
from pybb.attestation.snapshot import TargetSnapshot  # noqa: E402
from pybb.attestation.tools import (  # noqa: E402
    register_tool,
    weave_tool_measurements,
)
from pybb.autoverus import (  # noqa: E402
    AutoVerusConfig,
    AutoVerusRepairKS,
    preflight,
)

FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
EVIDENCE_DIR = REPO / "evidence"
TARGET = REPO / "targets" / "find-max-verus" / "find_max.rs"
PID = "find_max_verus_check"
KEY = "find_max_verus:proof"
READY = "find_max_verus:ready"

# --tamper deletes this loop-invariant conjunct, reproducing the
# tests/fixtures/autoverus/broken_proof.rs repair task (1 verified, 1 error)
TAMPER_LINE = "        exists |k: int| 0 <= k < i && nums@[k] == max,\n"

# The verus toolchain, measured in the same term as every invocation
# (measure-then-use). The wrapper is what CVM children resolve via PATH.
_DISTRO = Path.home() / "Claude_workspace" / "verus-arm64-macos"
register_tool("verus", [
    str(Path.home() / "Claude_workspace" / "bin" / "verus"),
    str(_DISTRO / "verus"),
    str(_DISTRO / "rust_verify"),
    str(_DISTRO / "z3"),
], used_by=["run_command_verus"])

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}

SESSION = {
    "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": {
            "run_command_verus": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "run_command_verus_appr": {
                # EXTEND: the appraiser retains the verus JSON it judged,
                # so the verification results survive into the episode
                # response (diagnostics / join material)
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
        },
        "ASP_Comps": {"run_command_verus": "run_command_verus_appr"},
    },
}
MANIFEST = {"ASPS": ["run_command_verus", "run_command_verus_appr"],
            "ASP_FS_MAP": {}, "POLICY": []}


def build_protocol_dir() -> ProtocolDir:
    """(Re)generate the find_max_verus_check protocol dir: one
    run_command_verus target over the committed source, verus toolchain
    hashes woven in measure-then-use."""
    import json

    targets = with_asp_targids({f"{PID}_targ": {
        "exe_args": [str(TARGET), "--output-json"]}})
    asp_args = {"run_command_verus": dict(targets)}
    body = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
        "ASP_CONSTRUCTOR": "ASPC",
        "ASP_BODY": {"ASP_ID": "run_command_verus",
                     "ASP_TARG_ID": f"{PID}_targ"}}}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [body, _APPR]}
    asp_args, term, session, manifest = weave_tool_measurements(
        asp_args, term, SESSION, MANIFEST)
    d = FIXTURES / PID
    d.mkdir(exist_ok=True)
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "name": "find_max attested Verus check",
        "description": "Definitive Verus verification of the find-max-verus "
                       "target: verus toolchain hashed measure-then-use, "
                       "`verus <file> --output-json`, appraised by "
                       "run_command_verus_appr (errors == 0), one SIG.",
    }, indent=2) + "\n")
    n_tools = len(asp_args.get("hashfile", {}))
    print(f"  {PID}: 1 verus target + {n_tools} woven tool measurements")
    return ProtocolDir.load(str(d))


def load_protocol() -> ProtocolDir:
    if not (FIXTURES / PID / "asp_args.json").is_file():
        print(f"{PID} protocol dir missing — generating")
        return build_protocol_dir()
    return ProtocolDir.load(str(FIXTURES / PID))


def provision_flow(protocol: ProtocolDir) -> None:
    """Provision the tool hash goldens: the signed bundle contains an
    actual (passing) verus run over the committed verified target."""
    measured = {PID: protocol}
    snapshot = TargetSnapshot.capture(measured, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files "
          "(tools are measure-in-place)")
    ctl = BlackboardController()
    ctl.register_predicate("provision", make_provision_predicate(
        CvmSubprocessClient(), measured, GOLDEN_ROOT))
    request_provision(ctl.blackboard, PID)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")


def attest_episode(protocol: ProtocolDir, repair_rung=None) -> BlackboardController:
    from pybb.attestation import attestation_request

    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate("attestation", make_attestation_predicate(
        client, {PID: protocol}, archive_dir=EVIDENCE_DIR))
    controller.register_predicate("protocol_check", make_readiness_predicate(
        {PID: protocol}, baseline_root=GOLDEN_ROOT, client=client))
    chain = [repair_rung] if repair_rung is not None else []
    for ks in chain:
        controller.add_ks(ks)
    starter = StartAttestationKS(episodes={KEY: PID})
    controller.add_ks(starter)
    controller.route(KEY, on_pass=[], on_fail=chain)
    controller.blackboard.write_entry(
        key=READY, predicate="protocol_check",
        measurement=readiness_request([PID]))
    controller.route(READY, on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=[PID]))
    return controller


def tamper() -> None:
    text = TARGET.read_text()
    assert TAMPER_LINE in text, "target shape changed — update TAMPER_LINE"
    TARGET.write_text(text.replace(TAMPER_LINE, ""))
    print(f"Tampered {TARGET.name}: deleted the exists loop-invariant "
          "conjunct (the broken_proof.rs repair task)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--autoverus", action="store_true",
                        help="explicit confirmation: the repair rung may "
                             "call the OpenAI API via AutoVerus (key read "
                             "from OPENAI_API_KEY only)")
    parser.add_argument("--repair-steps", type=int, default=5)
    parser.add_argument("--keep", action="store_true",
                        help="keep the repaired/tampered target (default: "
                             "restore the committed state)")
    cli = parser.parse_args()

    if cli.provision:
        provision_flow(build_protocol_dir())
        return

    protocol = load_protocol()
    rung = None
    if cli.autoverus:
        config = AutoVerusConfig()
        problems = preflight(config)
        if problems:
            print("cannot arm AutoVerus — the environment does not support "
                  "a real run:")
            for p in problems:
                print(f"  - {p}")
            raise SystemExit(1)
        print("AutoVerus armed (LLM calls confirmed by --autoverus):")
        print(f"  model:  {config.model}")
        print(f"  target: {TARGET}")
        print(f"  key:    OPENAI_API_KEY from the environment (never stored)")
        rung = AutoVerusRepairKS(
            target=str(TARGET), reattest=True, allow_llm=True,
            repair_steps=cli.repair_steps, config=config)
    elif cli.tamper:
        print("(no --autoverus: the failing episode will escalate — "
              "no repair, no LLM)")

    original = TARGET.read_bytes()
    if cli.tamper:
        tamper()
    try:
        attest_episode(protocol, repair_rung=rung)
    finally:
        if cli.keep:
            print(f"\n--keep: leaving {TARGET.name} as the run left it")
        else:
            TARGET.write_bytes(original)
            print(f"\nRestored committed {TARGET.name}")


if __name__ == "__main__":
    main()
