"""Run context (plan section O): stack and config bundles, blessings, pins,
and the reader's derivation. Unit tests use a fake installation (temp files
standing in for the CVM, summarizer, ASPs and key) and a canned client that
hashes whatever the generated term names; the real-CVM path, including the
audits, lives in test_integration_ledger.py."""

import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pybb.attestation import FileLedger, ProtocolDir, make_attestation_predicate
from pybb.attestation.ledger import (
    BlessingRecord,
    BundleRecord,
    ConfigInfo,
    LedgerConfig,
    LedgerError,
    StackInfo,
    canonical_json,
    key_for,
    parse_record,
    sha256_hex,
)
from pybb.attestation.ledger_context import (
    CONSTRUCTORS,
    bless,
    constructor_inputs,
    context_goldens,
    context_session,
    derive_context,
    input_hashes,
    input_targ,
    materialize_inputs,
    measure_config,
    measure_stack,
    stack_files,
    stack_goldens,
)
from pybb.attestation.ledger_runs import (
    NONCE_ARGS,
    NONCE_ASP,
    audit_session,
    inject_goldens,
    MISSING_GOLDEN_B64,
)

from test_ledger_runs import L1A, CannedClient


# ── a fake installation and a canned client that measures it ─────────────────


@pytest.fixture
def fake_stack(tmp_path):
    asp_bin = tmp_path / "asps"
    asp_bin.mkdir()
    for name in ("hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr",
                 "hashevidence", "magic_appr"):
        p = asp_bin / name
        p.write_bytes(b"binary " + name.encode())
        p.chmod(0o755)
    (asp_bin / "README.txt").write_text("not executable\n")  # skipped: not an executable
    cvm = tmp_path / "cvm"; cvm.write_bytes(b"cvm binary"); cvm.chmod(0o755)
    summ = tmp_path / "copland_evidence_tools"; summ.write_bytes(b"summarizer"); summ.chmod(0o755)
    key = tmp_path / "pub.pem"; key.write_bytes(b"-----BEGIN PUBLIC KEY-----\nabc\n")
    return SimpleNamespace(cvm_binary=str(cvm), asp_bin=str(asp_bin), summarizer=str(summ), key=str(key),
                           log_level="Info", timeout_s=10, path_prepend=[])


@pytest.fixture
def config(tmp_path, fake_stack):
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-ctx", evidence_repo="",
                        verify_key_path=fake_stack.key, golden_root=str(tmp_path / "golden"))


def _hashfile_nodes(term) -> list:
    """The hashfile events of a term in DFS order: (targ id, filepath)."""
    out = []

    def walk(t):
        if not isinstance(t, dict):
            return
        body = t.get("TERM_BODY")
        if t.get("TERM_CONSTRUCTOR") == "asp" and isinstance(body, dict):
            ab = body.get("ASP_BODY") or {}
            if ab.get("ASP_ID") == "hashfile":
                args = ab.get("ASP_ARGS") or {}
                out.append((args.get("asp_targid") or ab.get("ASP_TARG_ID"), args.get("filepath")))
            return
        for x in (body if isinstance(body, list) else []):
            walk(x)

    walk(term)
    return out


def fake_measure_package(targets: list, nonce: bytes) -> dict:
    """A `measure`-shaped package over hashfile targets [(targ, path, args)]:
    RawEv = [sig, nonce, h_1..h_n] with h_i = sha256(file), evidence type
    sig(split(nonce, chain)). What the CVM returns for `attestation_stack` /
    `attestation_config`."""
    raws = [base64.b64encode(b"\x01" * 256).decode(), base64.b64encode(nonce).decode()]
    chain = None
    for targ, path, args in targets:
        raws.append(base64.b64encode(hashlib.sha256(Path(path).read_bytes()).digest()).decode())
        node = {"EvidenceT_CONSTRUCTOR": "asp_evt",
                "EvidenceT_BODY": ["P0", {"ASP_ID": "hashfile", "ASP_ARGS": dict(args)},
                                   {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}
        chain = node if chain is None else {"EvidenceT_CONSTRUCTOR": "split_evt", "EvidenceT_BODY": [chain, node]}
    nonce_evt = {"EvidenceT_CONSTRUCTOR": "asp_evt",
                 "EvidenceT_BODY": ["P0", {"ASP_ID": NONCE_ASP, "ASP_ARGS": dict(NONCE_ARGS)},
                                    {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}
    et = {"EvidenceT_CONSTRUCTOR": "asp_evt",
          "EvidenceT_BODY": ["P0", {"ASP_ID": "sig", "ASP_ARGS": {}},
                             {"EvidenceT_CONSTRUCTOR": "split_evt", "EvidenceT_BODY": [nonce_evt, chain]}]}
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True, "PAYLOAD": [{"RawEv": raws}, et]}


class ContextClient(CannedClient):
    """Measurement requests whose term hashes files get a package hashing
    those files (fresh nonce each call); other requests fall back to the
    canned l1a packages (with fresh nonces too, so several runs coexist)."""

    n = 0

    def run_protocol(self, protocol: ProtocolDir) -> dict:
        req = protocol.prebuilt_request
        ContextClient.n += 1
        nonce = hashlib.sha256(f"ctx-{ContextClient.n}".encode()).digest()
        nodes = _hashfile_nodes(req["TERM"])
        if nodes and all(p for _t, p in nodes):
            self.requests.append(req)
            args_by = {}

            def collect(t):
                if not isinstance(t, dict):
                    return
                body = t.get("TERM_BODY")
                if t.get("TERM_CONSTRUCTOR") == "asp" and isinstance(body, dict):
                    ab = body.get("ASP_BODY") or {}
                    if ab.get("ASP_ID") == "hashfile":
                        args_by[(ab.get("ASP_ARGS") or {}).get("asp_targid")] = ab.get("ASP_ARGS") or {}
                for x in (body if isinstance(body, list) else []):
                    collect(x)

            collect(req["TERM"])
            return fake_measure_package([(t, p, args_by[t]) for t, p in nodes], nonce)
        resp = json.loads(json.dumps(super().run_protocol(protocol)))
        resp["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(nonce).decode()  # the nonce slot of both l1a packages
        return resp


# ── inputs: constructors, pins, materialization ──────────────────────────────


def test_run_pins_equal_the_constructor_inputs(tmp_path, config):
    """Plan O.3: a run bundle's term/session/manifest hashes are the hashes of
    the canonical inputs the CVM was handed — the bytes a config bundle
    measures — not of the raw protocol files."""
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    v = make_attestation_predicate(CannedClient(), {proto.protocol_id: proto}, ledger=ledger,
                                   ledger_config=config)({"protocol": proto.protocol_id})
    assert v.error == "", v.error
    want = input_hashes(proto)
    m = ledger.get(v.bid)
    assert (m.term_sha256, m.session_sha256, m.manifest_sha256) == tuple(
        want[input_targ("measure", n)] for n in ("term", "session", "manifest"))
    assert m.term_sha256 != sha256_hex(canonical_json(proto.term)), "the pin is the shaped term, not term.json"
    a = ledger.appraisals_of(v.bid)[0]
    assert (a.term_sha256, a.session_sha256, a.manifest_sha256) == tuple(
        want[input_targ("appraise", n)] for n in ("term", "session", "manifest"))


def test_audit_session_is_a_function_of_the_protocol(tmp_path):
    """The B.6 audit session no longer depends on which appraisers a package
    happens to carry (a subset of the protocol's), so `audit` is a static
    constructor a config bundle can measure."""
    proto = ProtocolDir.load(str(L1A))
    static = audit_session(proto.session)
    assert audit_session(proto.session, ["sig_appr", "nonce_appr", "goldenbytes_appr"]) == static
    comps = static["Session_Context"]["ASP_Comps"]
    assert comps["sig_appr"] == "magic_appr" and comps["nonce_appr"] == "magic_appr"
    term, session, manifest = constructor_inputs(proto, "audit")
    assert session == static and "magic_appr" in manifest["ASPS"]
    assert constructor_inputs(proto, "audit_combined")[1]["Session_Context"]["ASP_Types"]["hashevidence"]["FWD"]["FWD"] == "EXTEND"


def test_materialize_inputs_is_deterministic_and_content_addressed(tmp_path, config):
    proto = ProtocolDir.load(str(L1A))
    files = materialize_inputs(proto, config)
    assert set(files) == {input_targ(c, n) for c in CONSTRUCTORS for n in ("term", "session", "manifest")}
    want = input_hashes(proto)
    for targ, path in files.items():
        data = path.read_bytes()
        assert sha256_hex(data) == want[targ]
        assert (Path(config.state_dir) / "context" / "blobs" / f"{want[targ]}.json").read_bytes() == data
    again = materialize_inputs(proto, config)
    assert {t: p.read_bytes() for t, p in again.items()} == {t: p.read_bytes() for t, p in files.items()}


# ── stack ────────────────────────────────────────────────────────────────────


def test_stack_files_cover_the_installation_with_logical_ids(fake_stack, config):
    files = stack_files(fake_stack, config, fake_stack.summarizer)
    assert {"stack:cvm", "stack:summarizer", "stack:pubkey", "stack:invocation"} <= set(files)
    asps = {t for t in files if t.startswith("stack:asp:")}
    assert asps == {f"stack:asp:{n}" for n in ("hashfile", "sig", "sig_appr", "goldenbytes_appr",
                                                "generate_nonce", "nonce_appr", "hashevidence", "magic_appr")}
    assert "stack:asp:README.txt" not in files, "only executables"
    inv = json.loads(files["stack:invocation"].read_bytes())
    assert inv["asp_bin"] == fake_stack.asp_bin and inv["cvm_binary"] == fake_stack.cvm_binary


def test_measure_stack_commits_a_stack_bundle_always(tmp_path, fake_stack, config):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    m = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert m, m.error
    rec = ledger.get(m.bid)
    assert rec.role == "stack" and rec.shape == "measure" and rec.assurance == "signed+nonce"
    assert rec.protocol_id == "attestation_stack" and rec.stack == StackInfo(plc="P0", executables=10)
    assert rec.config is None and rec.inputs is None and rec.verdict is None
    assert m.targets == 12  # 10 executables + key + invocation
    # the term the CVM ran named every file; the package's values are the files' hashes
    targs = {t for t, _p in _hashfile_nodes(client.requests[-1]["TERM"])}
    assert targs == set(stack_files(fake_stack, config, fake_stack.summarizer, write_invocation=False)) | {"stack:invocation"}
    # unconditional: a second measure of an unchanged stack is a second bundle
    m2 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert m2 and m2.bid != m.bid and len(ledger.bundles(role="stack")) == 2


# ── config ───────────────────────────────────────────────────────────────────


def test_measure_config_files_one_bundle_under_the_protocol(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    m = measure_config(ContextClient(), proto, ledger, config)
    assert m, m.error
    rec = ledger.get(m.bid)
    assert rec.role == "config" and rec.protocol_id == proto.protocol_id and rec.stack is None
    assert rec.config.constructors == list(CONSTRUCTORS) and len(rec.config.files) == 18
    want = input_hashes(proto)
    for f in rec.config.files:
        assert f.blob.blob_sha256 == want[f.targ_id] and f.blob.encoding == "json"
        local = next(l.path for l in f.blob.locations if l.store == "local")
        assert sha256_hex(Path(local).read_bytes()) == f.blob.blob_sha256
    assert rec.config is not None and m.targets == 18


# ── blessing ─────────────────────────────────────────────────────────────────


def test_bless_reads_goldens_off_the_signed_package_once(tmp_path, fake_stack, config):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    archive_dir = tmp_path / "evidence"
    from pybb.attestation.ledger_runs import archiver
    m = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer,
                      archive=archiver(archive_dir))
    rec = bless(ledger, config, m.bid, note="first install")
    assert key_for(rec) == f"blessing/{m.bid}" and rec.note == "first install" and rec.appraiser_id == "ap-ctx"
    assert set(rec.targets) == set(rec.goldens) and len(rec.goldens) == 12
    cvm_hash = base64.b64encode(hashlib.sha256(Path(fake_stack.cvm_binary).read_bytes()).digest()).decode()
    assert rec.goldens["stack:cvm"] == cvm_hash
    assert ledger.blessing_of(m.bid) == rec and parse_record(rec.to_dict()) == rec
    with pytest.raises(LedgerError):
        bless(ledger, config, m.bid)  # one blessing per stack bundle
    cfg = measure_config(client, ProtocolDir.load(str(L1A)), ledger, config, archive=archiver(archive_dir))
    with pytest.raises(LedgerError):
        bless(ledger, config, cfg.bid)  # only stack bundles are blessed
    # audit expectations (plan O.6): stack -> the blessing; config -> its own file hashes
    goldens, key, err = context_goldens(ledger, ledger.get(m.bid), None)
    assert err == "" and key == f"blessing/{m.bid}" and goldens == rec.goldens
    goldens, key, err = context_goldens(ledger, ledger.get(cfg.bid), None)
    assert err == "" and key == "" and goldens[input_targ("measure", "term")] == base64.b64encode(
        bytes.fromhex(input_hashes(ProtocolDir.load(str(L1A)))[input_targ("measure", "term")])).decode()
    _g, _k, err = context_goldens(FileLedger(tmp_path / "empty.jsonl"), ledger.get(m.bid), None)
    assert "no blessing" in err


def test_inject_goldens_by_target_and_mark_unknown_ones():
    et = fake_measure_package([("stack:cvm", __file__, {"asp_targid": "stack:cvm"}),
                               ("stack:asp:x", __file__, {"asp_targid": "stack:asp:x"})], b"\0" * 32)["PAYLOAD"][1]
    out = inject_goldens(et, {"stack:cvm": "AAAA"})
    nodes = []

    def walk(n):
        if not isinstance(n, dict):
            return
        b = n.get("EvidenceT_BODY")
        if n.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
            if b[1]["ASP_ID"] == "hashfile":
                nodes.append(b[1]["ASP_ARGS"])
            walk(b[2])
        elif n.get("EvidenceT_CONSTRUCTOR") == "split_evt":
            walk(b[0]); walk(b[1])

    walk(out)
    assert [a["golden_b64"] for a in nodes] == ["AAAA", MISSING_GOLDEN_B64]
    assert "golden_b64" not in json.dumps(et), "the input type is untouched"


# ── the reader's derivation (plan O.7) ───────────────────────────────────────


def test_derive_context_joins_runs_by_writer_and_order(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    protocols = {proto.protocol_id: proto}
    predicate = make_attestation_predicate(client, protocols, ledger=ledger, ledger_config=config)

    # a run before any context evidence: nothing to derive
    v0 = predicate({"protocol": proto.protocol_id})
    assert v0.error == "", v0.error
    d0 = derive_context(ledger, ledger.get(v0.bid))
    assert d0.status == "none" and d0.stack_status == "none" and not d0

    s1 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    c1 = measure_config(client, proto, ledger, config)
    predicate.forget({"protocol": proto.protocol_id})
    v1 = predicate({"protocol": proto.protocol_id})
    assert v1.error == "", v1.error
    d1 = derive_context(ledger, ledger.get(v1.bid))
    assert d1 and d1.status == "measured" and d1.constructor == "measure"
    assert d1.stack_bid == s1.bid and d1.stack_status == "unblessed" and d1.config_bid == c1.bid
    assert d1.pins == {"term": True, "session": True, "manifest": True}
    da = derive_context(ledger, ledger.appraisals_of(v1.bid)[0])
    assert da.constructor == "appraise" and da.config_bid == c1.bid

    bless(ledger, config, s1.bid)
    predicate.forget({"protocol": proto.protocol_id})
    v2 = predicate({"protocol": proto.protocol_id})
    d2 = derive_context(ledger, ledger.get(v2.bid))
    assert d2.stack_status == "blessed" and d2.blessing_key == f"blessing/{s1.bid}"
    # the earlier run still derives the state at ITS transaction: unblessed then
    assert derive_context(ledger, ledger.get(v1.bid)).stack_status == "unblessed"

    # a protocol edit after the last `measure config`: the pins say stale
    edited = proto.model_copy(update={"asp_args": json.loads(json.dumps(proto.asp_args))})
    first_asp = next(iter(edited.asp_args))
    first_targ = next(iter(edited.asp_args[first_asp]))
    edited.asp_args[first_asp][first_targ]["metadata"] = "edited"
    v3 = make_attestation_predicate(client, {proto.protocol_id: edited}, ledger=ledger,
                                    ledger_config=config)({"protocol": proto.protocol_id})
    assert v3.error == "", v3.error
    d3 = derive_context(ledger, ledger.get(v3.bid))
    assert d3.status == "stale" and d3.config_bid == c1.bid and d3.pins["term"] is False and d3.pins["session"]

    # another writer's run derives nothing from this writer's evidence
    other = config.model_copy(update={"appraiser_id": "ap-other", "state_dir": str(tmp_path / "other")})
    v4 = make_attestation_predicate(client, protocols, ledger=ledger, ledger_config=other)(
        {"protocol": proto.protocol_id})
    assert v4.error == "", v4.error
    d4 = derive_context(ledger, ledger.get(v4.bid))
    assert d4.status == "none" and d4.stack_status == "none" and d4.writer == "ap-other"


# ── records ──────────────────────────────────────────────────────────────────


def _bundle(**kw) -> dict:
    nonce = b"\x07" * 32
    base = dict(kind="bundle", bid=sha256_hex(nonce), role="measurement", protocol_id="p", response_sha256="r",
                blob={"blob_sha256": "b", "blob_bytes": 1}, rawev_count=1, rawev_sha256="h",
                nonce={"asp": "generate_nonce", "b64": base64.b64encode(nonce).decode(), "bytes": 32},
                signature={"present": True, "asp": "sig"}, assurance="signed+nonce")
    base.update(kw)
    return base


def test_context_role_gates():
    BundleRecord.model_validate(_bundle(role="stack", stack={"plc": "P0", "executables": 3}))
    BundleRecord.model_validate(_bundle(role="config", config={"constructors": ["measure"], "files": []}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="measurement", stack={"plc": "P0"}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="stack", config={"constructors": []}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="measurement", baseline="blessing/x"))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="stack", verdict={"passed": True, "interpreter": {"kind": "legacy-walker"}}))
    # legacy `tooling` stays readable
    old = BundleRecord.model_validate(_bundle(tooling={"kind": "bundle", "ref": "abc"}))
    assert old.tooling.ref == "abc" and "tooling" in old.to_dict()


def test_blessing_record_key_relpath_and_mirror_row():
    from pybb.attestation.ledger_immudb import mirror_row
    from pybb.attestation.ledger_repo import record_relpath

    b = BlessingRecord(stack_bid="ab" * 32, targets=["stack:cvm"], goldens={"stack:cvm": "AA=="}, appraiser_id="ap")
    assert key_for(b) == f"blessing/{'ab' * 32}" and parse_record(b.to_dict()) == b
    assert record_relpath(key_for(b), b) == f"ledger/blessing/{'ab' * 32}.json"
    row = mirror_row(key_for(b), b)
    assert row["kind"] == "blessing" and row["baseline"] == "" and row["passed"] is None
    audit = BundleRecord.model_validate(_bundle(
        role="appraisal", inputs=[{"bid": "cd" * 32}], appraisal_kind="audit", baseline=key_for(b),
        verdict={"passed": True, "interpreter": {"kind": "verified-summary"}}))
    assert mirror_row(key_for(audit), audit)["baseline"] == key_for(b)
