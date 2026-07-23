"""
End-to-end blackboard provisioning against the real CVM, asp-libs
extract_golden_slice, and the golden directory.

Provision requests for gumbo_l1/gumbo_l2 (in the provision partition) run
measurement-only terms over tmp copies of golden/, install fresh goldens
into tmp copies of the protocol dirs, and — in the same controller run —
the certify-partition attestation entry attests the live tree against the
freshly provisioned goldens.

The freshly extracted golden_b64 values must equal the committed fixture
values: golden/ holds byte-identical copies of the content the fixtures
were provisioned from.

Auto-skipped unless the CVM binary, ASP binaries (incl. extract_golden_slice),
temp-control-jvm, and golden/ are present.
"""

import shutil
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    make_provision_predicate,
    request_provision,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = Path(__file__).parent.parent / "golden"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")
PROTOCOL_IDS = ("gumbo_l1", "gumbo_l2")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (
            Path(DEFAULT_CVM_BINARY).is_file()
            and (Path(DEFAULT_ASP_BIN) / "extract_golden_slice").is_file()
            and TC_ROOT.is_dir()
            and GOLDEN_ROOT.is_dir()
        ),
        reason="requires CVM binary, asp-libs (extract_golden_slice), "
               "temp-control-jvm, and the golden directory",
    ),
]


def test_provision_from_golden_then_attest_live(tmp_path):
    # tmp copies: provisioning writes protocol dirs and the bundle area
    golden_tmp = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, golden_tmp)
    protocols = {}
    for pid in PROTOCOL_IDS:
        shutil.copytree(FIXTURES / pid, tmp_path / pid)
        protocols[pid] = ProtocolDir.load(str(tmp_path / pid))
    committed = {
        pid: {
            asp_id: {t: a["golden_b64"] for t, a in targets.items()}
            for asp_id, targets in protocols[pid].asp_args.items()
        }
        for pid in PROTOCOL_IDS
    }

    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate(
        "provision", make_provision_predicate(client, protocols, golden_tmp)
    )
    ctl.register_predicate(
        "attestation", make_attestation_predicate(client, protocols)
    )
    for pid in PROTOCOL_IDS:
        request_provision(ctl.blackboard, pid)
    ctl.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1"),
    )
    rungs = [TierKS(protocol_id="gumbo_l2")]
    for ks in rungs:
        ctl.add_ks(ks)
    ctl.route("gumbo", on_fail=rungs)

    bb = ctl.run()

    # provision records: both requests fulfilled, in good standing
    l1 = bb.provision["provision:gumbo_l1"].result
    l2 = bb.provision["provision:gumbo_l2"].result
    assert bb.provision["provision:gumbo_l1"].good_standing, l1
    assert bb.provision["provision:gumbo_l2"].good_standing, l2
    assert len(l1.provisioned) == 4 and len(l2.provisioned) == 28

    # freshly extracted goldens equal the committed fixture values
    for pid in PROTOCOL_IDS:
        for asp_id, targets in protocols[pid].asp_args.items():
            for targ_id, args in targets.items():
                assert args["golden_b64"] == committed[pid][asp_id][targ_id], (
                    f"{pid}/{asp_id}/{targ_id} diverged from committed golden"
                )

    # provisioning artifacts: bundle written, stale prebuilt gone
    assert (golden_tmp / "_bundles" / "gumbo_l1" / "provision_bundle.json").is_file()
    assert not (tmp_path / "gumbo_l1" / "cvm_request.json").exists()
    assert protocols["gumbo_l1"].prebuilt_request is None

    # attestation (same run, certify partition) attested the live tree
    # clean against the freshly provisioned goldens, without tier hops
    gumbo = bb.entries["gumbo"]
    assert gumbo.good_standing and gumbo.result.protocol == "gumbo_l1"
    assert gumbo.ks_history == {}
