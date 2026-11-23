"""Run context (plan sections O and P): stack and config bundles with
CVM-computed fingerprints, blessings, pins, the cache and the reader's
derivation. Unit tests use a fake installation (temp files standing in for
the CVM, summarizer, ASPs and key) and a canned client that SIMULATES the
CVM's evidence semantics for the context terms (hashfile, hashevidence,
nonce, SIG, lseq, bseq); protocol runs fall back to the canned l1a packages.
The real-CVM path, including the audits, lives in test_integration_ledger.py."""

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
    GoldenProvenance,
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
    SETTINGS,
    bless,
    constructor_inputs,
    context_goldens,
    context_session,
    derive_context,
    input_hashes,
    input_targ,
    load_cache,
    materialize_inputs,
    measure_config,
    measure_stack,
    read_context_package,
    refresh_due,
    refresh_if_due,
    stack_files,
    stack_goldens,
    verify_claim,
)
from pybb.attestation.ledger_runs import (
    NONCE_ASP,
    audit_session,
    has_lane,
    inject_goldens,
    lane_targ,
    ledger_protocol,
    measure,
    MISSING_GOLDEN_B64,
    needs_keep,
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


MT = {"EvidenceT_CONSTRUCTOR": "mt_evt"}


def _asp_ids(term) -> set:
    out = set()

    def walk(t):
        if not isinstance(t, dict):
            return
        body = t.get("TERM_BODY")
        if t.get("TERM_CONSTRUCTOR") == "asp" and isinstance(body, dict):
            out.add(body.get("ASP_CONSTRUCTOR") if body.get("ASP_CONSTRUCTOR") != "ASPC"
                    else (body.get("ASP_BODY") or {}).get("ASP_ID"))
            return
        for x in (body if isinstance(body, list) else []):
            walk(x)

    walk(term)
    return out


def simulate(term: dict, session: dict, nonce: bytes) -> dict:
    """The CVM's evidence semantics for context terms (cvm/theories/Monad.v):
    hashfile = sha256 of the file; hashevidence = sha256 over the flattened
    input RawEv; EXTEND prepends the output to its input, REPLACE replaces
    it; SIG signs; bseq splits the evidence by `left_path`/`right_path`/
    `both_paths`; RawEv newest first in DFS order."""
    types = session["Session_Context"]["ASP_Types"]

    def run(t, raws, et):
        c, b = t["TERM_CONSTRUCTOR"], t["TERM_BODY"]
        if c == "asp":
            ctor = b["ASP_CONSTRUCTOR"]
            if ctor == "NULL":
                return [], MT
            if ctor == "SIG":
                out, params, fwd = b"\x01" * 256, {"ASP_ID": "sig", "ASP_ARGS": {}}, "EXTEND"
            else:
                ab = b["ASP_BODY"]; aid = ab["ASP_ID"]; args = ab.get("ASP_ARGS") or {}
                if aid == "hashfile":
                    out = hashlib.sha256(Path(args["filepath"]).read_bytes()).digest()
                elif aid == NONCE_ASP:
                    out = nonce
                elif aid == "hashevidence":
                    out = hashlib.sha256(b"".join(raws)).digest()
                else:
                    out = bytes(32)
                params, fwd = {"ASP_ID": aid, "ASP_ARGS": args}, types[aid]["FWD"]["FWD"]
            node = {"EvidenceT_CONSTRUCTOR": "asp_evt", "EvidenceT_BODY": ["P0", params, et]}
            return ([out] + raws if fwd == "EXTEND" else [out]), node
        if c == "lseq":
            r, e = run(b[0], raws, et)
            return run(b[1], r, e)
        if c == "bseq":
            sp, a, bb = b
            la = (raws, et) if sp in ("left_path", "both_paths") else ([], MT)
            lb = (raws, et) if sp in ("right_path", "both_paths") else ([], MT)
            ra, ea = run(a, *la)
            rb, eb = run(bb, *lb)
            return ra + rb, {"EvidenceT_CONSTRUCTOR": "split_evt", "EvidenceT_BODY": [ea, eb]}
        raise NotImplementedError(c)

    raws, et = run(term, [], MT)
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
            "PAYLOAD": [{"RawEv": [base64.b64encode(r).decode() for r in raws]}, et]}


class ContextClient(CannedClient):
    """Context terms (hashfile chains under hashevidence) are simulated with a
    fresh nonce each call; other requests fall back to the canned l1a
    packages (with fresh nonces too, so several runs coexist)."""

    n = 0

    def run_protocol(self, protocol: ProtocolDir) -> dict:
        req = protocol.prebuilt_request
        ContextClient.n += 1
        nonce = hashlib.sha256(f"ctx-{ContextClient.n}".encode()).digest()
        ids = _asp_ids(req["TERM"])
        if ids <= {"hashfile", "hashevidence", NONCE_ASP, "SIG", "NULL"}:  # context terms and hashfile measurements
            self.requests.append(req)
            return simulate(req["TERM"], req["ATTESTATION_SESSION"], nonce)
        resp = json.loads(json.dumps(super().run_protocol(protocol)))
        resp["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(nonce).decode()  # the nonce slot of both l1a packages
        return resp


def _digest_b64(path) -> str:
    return base64.b64encode(hashlib.sha256(Path(path).read_bytes()).digest()).decode()


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
    want = input_hashes(proto, config)
    m = ledger.get(v.bid)
    assert (m.term_sha256, m.session_sha256, m.manifest_sha256) == tuple(
        want[input_targ("measure", n)] for n in ("term", "session", "manifest"))
    assert m.term_sha256 != sha256_hex(canonical_json(proto.term)), "the pin is the shaped term, not term.json"
    a = ledger.appraisals_of(v.bid)[0]
    assert (a.term_sha256, a.session_sha256, a.manifest_sha256) == tuple(
        want[input_targ("appraise", n)] for n in ("term", "session", "manifest"))


def test_audit_session_is_a_function_of_the_protocol(tmp_path, config):
    proto = ProtocolDir.load(str(L1A))
    static = audit_session(proto.session)
    assert audit_session(proto.session, ["sig_appr", "nonce_appr", "goldenbytes_appr"]) == static
    comps = static["Session_Context"]["ASP_Comps"]
    assert comps["sig_appr"] == "magic_appr" and comps["nonce_appr"] == "magic_appr"
    term, session, manifest = constructor_inputs(proto, "audit", config)
    assert session == static and "magic_appr" in manifest["ASPS"]
    assert constructor_inputs(proto, "audit_combined", config)[1]["Session_Context"]["ASP_Types"]["hashevidence"]["FWD"]["FWD"] == "EXTEND"


def test_materialize_inputs_is_deterministic_and_content_addressed(tmp_path, config):
    proto = ProtocolDir.load(str(L1A))
    files = materialize_inputs(proto, config)
    assert set(files) == {input_targ(c, n) for c in CONSTRUCTORS for n in ("term", "session", "manifest")}
    want = input_hashes(proto, config)
    for targ, path in files.items():
        data = path.read_bytes()
        assert sha256_hex(data) == want[targ]
        assert (Path(config.state_dir) / "context" / "blobs" / f"{want[targ]}.json").read_bytes() == data
    again = materialize_inputs(proto, config)
    assert {t: p.read_bytes() for t, p in again.items()} == {t: p.read_bytes() for t, p in files.items()}


# ── stack: the fingerprint is a CVM slot (plan P.1) ─────────────────────────


def test_stack_files_cover_the_installation_sorted_by_logical_id(fake_stack, config):
    files = stack_files(fake_stack, config, fake_stack.summarizer)
    assert {"stack:cvm", "stack:summarizer", "stack:pubkey"} <= set(files)
    asps = {t for t in files if t.startswith("stack:asp:")}
    assert asps == {f"stack:asp:{n}" for n in ("hashfile", "sig", "sig_appr", "goldenbytes_appr",
                                                "generate_nonce", "nonce_appr", "hashevidence", "magic_appr")}
    assert "stack:asp:README.txt" not in files, "only executables"
    assert "stack:invocation" not in files, "the invocation is a settings-lane target, not under H_bin"
    assert list(files) == sorted(files), "the chain order is the sorted target-id order"


def test_measure_stack_records_the_fingerprint_slot_and_the_settings_lane(tmp_path, fake_stack, config):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    m = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert m, m.error
    rec = ledger.get(m.bid)
    assert rec.role == "stack" and rec.shape == "measure" and rec.assurance == "signed+nonce"
    assert rec.protocol_id == "attestation_stack" and rec.stack.plc == "P0" and rec.stack.executables == 10
    assert m.targets == 11 + 4  # 10 executables + key, plus term/session/manifest/invocation
    assert rec.config is None and rec.inputs is None and rec.verdict is None
    # layout: [sig, nonce, H_bin, 11 digests, 4 settings]
    pkg = json.loads(open(m.evidence_ref, "rb").read().decode()) if not m.evidence_ref.endswith(".gz") else None
    import gzip
    pkg = json.loads(gzip.open(m.evidence_ref).read())["PAYLOAD"]
    reading = read_context_package(pkg, context_session())
    assert rec.rawev_count == 2 + 1 + 11 + 4
    assert reading.fingerprint == rec.stack.fingerprint == m.fingerprint
    assert list(reading.digests) == sorted(reading.digests) and len(reading.digests) == 11
    assert set(reading.settings) == {"stack:term", "stack:session", "stack:manifest", "stack:invocation"}
    assert rec.stack.invocation == reading.settings["stack:invocation"]
    # the CVM (simulated) hashed the files; pybb only copied slots — check against the files themselves
    assert reading.digests["stack:cvm"] == _digest_b64(fake_stack.cvm_binary)
    run_dir = Path(config.state_dir) / "context" / "stack"
    assert reading.settings["stack:term"] == _digest_b64(run_dir / "term.json")
    assert sha256_hex((run_dir / "term.json").read_bytes()) == rec.term_sha256, "the pin is the measured term file"
    assert json.loads((run_dir / "cvm_config.json").read_bytes())["asp_bin"] == fake_stack.asp_bin
    # the cache is a slot copy
    cache = load_cache(config)
    assert cache["writer"] == "ap-ctx" and cache["stack"]["bid"] == m.bid
    assert cache["stack"]["fingerprint"] == rec.stack.fingerprint and cache["stack"]["invocation"] == rec.stack.invocation


def test_fingerprint_is_canonical(tmp_path, fake_stack, config):
    """Plan P.1: H_bin depends on which file contents are measured and in which
    order, and on nothing else."""
    import shutil

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    s1 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    # same stack again: same fingerprint, fresh nonce and bundle
    s2 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert s1 and s2 and s1.bid != s2.bid and s1.fingerprint == s2.fingerprint
    assert ledger.get(s1.bid).rawev_sha256 != ledger.get(s2.bid).rawev_sha256  # nonce and signature differ
    # same binaries under another directory: same fingerprint, different settings digests (paths in the term)
    other = tmp_path / "elsewhere" / "asps"; other.parent.mkdir(); shutil.copytree(fake_stack.asp_bin, other)
    moved = SimpleNamespace(**{**vars(fake_stack), "asp_bin": str(other)})
    s3 = measure_stack(client, ledger, config, cvm_config=moved, summarizer_bin=fake_stack.summarizer)
    r1, r3 = ledger.get(s1.bid), ledger.get(s3.bid)
    assert s3.fingerprint == s1.fingerprint and r3.term_sha256 != r1.term_sha256 and r3.stack.invocation != r1.stack.invocation
    # an added executable or a renamed one changes it
    extra = Path(fake_stack.asp_bin) / "zz_extra"; extra.write_bytes(b"#!/bin/sh\n"); extra.chmod(0o755)
    s4 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert s4.fingerprint != s1.fingerprint and ledger.get(s4.bid).stack.executables == 11
    extra.unlink()
    (Path(fake_stack.asp_bin) / "magic_appr").rename(Path(fake_stack.asp_bin) / "aaa_magic_appr")
    s5 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    assert s5.fingerprint != s1.fingerprint and ledger.get(s5.bid).stack.executables == 10
    # the operator asked each time: five bundles, no dedup
    assert len(ledger.bundles(role="stack")) == 5


# ── config ───────────────────────────────────────────────────────────────────


def test_measure_config_files_one_bundle_under_the_protocol(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    m = measure_config(ContextClient(), proto, ledger, config, cvm_config=fake_stack)
    assert m, m.error
    rec = ledger.get(m.bid)
    assert rec.role == "config" and rec.protocol_id == proto.protocol_id and rec.stack is None
    assert rec.config.constructors == list(CONSTRUCTORS) and len(rec.config.files) == 18
    assert rec.config.fingerprint == m.fingerprint and m.targets == 18 + 4
    want = input_hashes(proto, config)
    for f in rec.config.files:
        assert f.blob.blob_sha256 == want[f.targ_id] and f.blob.encoding == "json"
        local = next(l.path for l in f.blob.locations if l.store == "local")
        assert sha256_hex(Path(local).read_bytes()) == f.blob.blob_sha256
    assert load_cache(config)["configs"][proto.protocol_id]["fingerprint"] == m.fingerprint
    assert needs_keep(ledger, rec) and needs_keep(ledger, ledger.get(measure_stack(
        ContextClient(), ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer).bid))


# ── blessing ─────────────────────────────────────────────────────────────────


def test_bless_reads_goldens_and_fingerprint_off_the_signed_package_once(tmp_path, fake_stack, config):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    m = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    rec = bless(ledger, config, m.bid, note="first install")
    assert key_for(rec) == f"blessing/{m.bid}" and rec.note == "first install" and rec.appraiser_id == "ap-ctx"
    assert set(rec.targets) == set(rec.goldens) and len(rec.goldens) == 15  # 11 under H_bin + 4 settings
    assert rec.goldens["stack:cvm"] == _digest_b64(fake_stack.cvm_binary)
    assert rec.fingerprint == m.fingerprint
    assert ledger.blessing_of(m.bid) == rec and parse_record(rec.to_dict()) == rec
    with pytest.raises(LedgerError):
        bless(ledger, config, m.bid)  # one blessing per stack bundle
    cfg = measure_config(client, ProtocolDir.load(str(L1A)), ledger, config, cvm_config=fake_stack)
    with pytest.raises(LedgerError):
        bless(ledger, config, cfg.bid)  # only stack bundles are blessed
    # audit expectations (plan O.6 / P.5): stack -> the blessing's goldens and fingerprint
    goldens, fp, prov, err = context_goldens(ledger, ledger.get(m.bid), None)
    assert err == "" and goldens == rec.goldens and fp == rec.fingerprint
    assert prov == [GoldenProvenance(source="blessing", ref=f"blessing/{m.bid}", targets=["stack:*"]),
                    GoldenProvenance(source="blessing", ref=f"blessing/{m.bid}", asp="hashevidence")]
    # config -> its own archived files and recorded fingerprint
    goldens, fp, prov, err = context_goldens(ledger, ledger.get(cfg.bid), None)
    assert err == "" and fp == cfg.fingerprint
    assert prov[0] == GoldenProvenance(source="bundle", ref=f"bundle/{cfg.bid}", targets=["input:*", "config:*"])
    assert set(ledger.get(cfg.bid).config.settings) == {"config:term", "config:session", "config:manifest", "config:invocation"}
    assert goldens["config:invocation"] == ledger.get(cfg.bid).config.settings["config:invocation"]
    assert goldens[input_targ("measure", "term")] == base64.b64encode(
        bytes.fromhex(input_hashes(ProtocolDir.load(str(L1A)), config)[input_targ("measure", "term")])).decode()
    _g, _f, _p, err = context_goldens(FileLedger(tmp_path / "empty.jsonl"), ledger.get(m.bid), None)
    assert "no blessing" in err


def test_inject_goldens_by_target_and_mark_unknown_ones(tmp_path):
    f1 = tmp_path / "a"; f1.write_bytes(b"a")
    f2 = tmp_path / "b"; f2.write_bytes(b"b")
    from pybb.attestation.ledger_context import fingerprint_term, hashfile_targets
    from pybb.attestation.ledger_runs import ledger_protocol, measurement_request
    term = fingerprint_term(hashfile_targets({"stack:cvm": f1, "stack:asp:x": f2}, "t"), {})
    lp = ledger_protocol(ProtocolDir(protocol_id="attestation_stack", path="", term=term, session=context_session(),
                                     manifest={"ASPS": ["hashfile", "sig"], "ASP_FS_MAP": {}, "POLICY": []},
                                     asp_args={"hashfile": hashfile_targets({"stack:cvm": f1, "stack:asp:x": f2}, "t")}))
    lp = lp.model_copy(update={"session": context_session()})
    et = simulate(measurement_request(lp)["TERM"], lp.session, b"\0" * 32)["PAYLOAD"][1]
    out = inject_goldens(et, {"stack:cvm": "AAAA"})
    out = inject_goldens(out, {"": "HHHH"}, "hashevidence")
    found = {}

    def walk(n):
        if not isinstance(n, dict):
            return
        b = n.get("EvidenceT_BODY")
        if n.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
            p = b[1]
            if p["ASP_ID"] in ("hashfile", "hashevidence"):
                found[p["ASP_ARGS"].get("asp_targid", p["ASP_ID"])] = p["ASP_ARGS"].get("golden_b64")
            walk(b[2])
        elif n.get("EvidenceT_CONSTRUCTOR") == "split_evt":
            walk(b[0]); walk(b[1])

    walk(out)
    assert found == {"stack:cvm": "AAAA", "stack:asp:x": MISSING_GOLDEN_B64, "hashevidence": "HHHH"}
    assert "golden_b64" not in json.dumps(et), "the input type is untouched"


# ── the reader's derivation (plan O.7) ───────────────────────────────────────


def test_derive_context_joins_runs_by_writer_and_order(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = ContextClient()
    protocols = {proto.protocol_id: proto}
    predicate = make_attestation_predicate(client, protocols, ledger=ledger, ledger_config=config)

    v0 = predicate({"protocol": proto.protocol_id})
    assert v0.error == "", v0.error
    d0 = derive_context(ledger, ledger.get(v0.bid))
    assert d0.status == "none" and d0.stack_status == "none" and not d0

    s1 = measure_stack(client, ledger, config, cvm_config=fake_stack, summarizer_bin=fake_stack.summarizer)
    c1 = measure_config(client, proto, ledger, config, cvm_config=fake_stack)
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
    assert derive_context(ledger, ledger.get(v1.bid)).stack_status == "unblessed"

    edited = proto.model_copy(update={"asp_args": json.loads(json.dumps(proto.asp_args))})
    first_asp = next(iter(edited.asp_args))
    first_targ = next(iter(edited.asp_args[first_asp]))
    edited.asp_args[first_asp][first_targ]["metadata"] = "edited"
    v3 = make_attestation_predicate(client, {proto.protocol_id: edited}, ledger=ledger,
                                    ledger_config=config)({"protocol": proto.protocol_id})
    assert v3.error == "", v3.error
    d3 = derive_context(ledger, ledger.get(v3.bid))
    assert d3.status == "stale" and d3.config_bid == c1.bid and d3.pins["term"] is False and d3.pins["session"]

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
    BundleRecord.model_validate(_bundle(role="stack", stack={"plc": "P0", "executables": 3, "fingerprint": "AA=="}))
    BundleRecord.model_validate(_bundle(role="config", config={"constructors": ["measure"], "files": [], "fingerprint": "AA=="}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="measurement", stack={"plc": "P0"}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="stack", config={"constructors": []}))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="measurement", golden_provenance=[{"source": "protocol"}]))
    with pytest.raises(ValueError):
        BundleRecord.model_validate(_bundle(role="stack", verdict={"passed": True, "interpreter": {"kind": "legacy-walker"}}))


def test_blessing_record_key_relpath_and_mirror_row():
    from pybb.attestation.ledger_immudb import mirror_row
    from pybb.attestation.ledger_repo import record_relpath

    b = BlessingRecord(stack_bid="ab" * 32, targets=["stack:cvm"], goldens={"stack:cvm": "AA=="},
                       fingerprint="HH==", appraiser_id="ap")
    assert key_for(b) == f"blessing/{'ab' * 32}" and parse_record(b.to_dict()) == b
    assert record_relpath(key_for(b), b) == f"ledger/blessing/{'ab' * 32}.json"
    row = mirror_row(key_for(b), b)
    assert row["kind"] == "blessing" and row["passed"] is None
    audit = BundleRecord.model_validate(_bundle(
        role="appraisal", inputs=[{"bid": "cd" * 32}],
        golden_provenance=[{"source": "blessing", "ref": key_for(b), "targets": ["stack:*"]},
                           {"source": "blessing", "ref": key_for(b), "asp": "hashevidence"}],
        verdict={"passed": True, "interpreter": {"kind": "verified-summary"}}))
    assert audit.golden_provenance[1].asp == "hashevidence" and mirror_row(key_for(audit), audit)["input_bid"] == "cd" * 32


# ── stage 3: the measured claim lane, claims, refresh (plan P.2–P.5) ─────────


def _ctx_client(fake_stack) -> ContextClient:
    c = ContextClient()
    c.config = fake_stack  # the CvmConfig the lane's cvm_config.json records
    return c


def test_run_carries_the_claim_measured_into_its_lane(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = _ctx_client(fake_stack)
    from pybb.attestation.ledger_runs import archiver
    archive = archiver(tmp_path / "evidence")
    # no cache yet: the lane is there and its files are archived, but the claim names nothing
    m0 = measure(client, proto, ledger, config, archive=archive)
    assert m0, m0.error
    r0 = ledger.get(m0.bid)
    assert r0.claim is not None and r0.claim.stack_bid == "" and r0.claim.config_bid == "" and len(r0.claim.files) == 5
    import gzip
    pkg0 = json.loads(gzip.open(m0.evidence_ref).read())["PAYLOAD"]
    lp = ledger_protocol(proto)
    assert has_lane(pkg0, lp.session)
    lane_dir = Path(config.state_dir) / "context" / "runs" / proto.protocol_id / "measure"
    assert json.loads((lane_dir / "claim.json").read_bytes()) == {}
    assert json.loads((lane_dir / "cvm_config.json").read_bytes())["asp_bin"] == fake_stack.asp_bin
    # the term file is the fixed point: its bytes are the request's TERM, which names it
    assert sha256_hex((lane_dir / "term.json").read_bytes()) == r0.term_sha256
    assert str(lane_dir / "term.json") in (lane_dir / "term.json").read_text()

    # with a cache, the run claims its context and the lane measures the claim file
    s1 = measure_stack(client, ledger, config, summarizer_bin=fake_stack.summarizer)
    c1 = measure_config(client, proto, ledger, config)
    m1 = measure(client, proto, ledger, config, archive=archive)
    assert m1, m1.error
    r1 = ledger.get(m1.bid)
    assert r1.claim is not None
    assert r1.claim.stack_bid == s1.bid and r1.claim.stack_fingerprint == s1.fingerprint
    assert r1.claim.config_bid == c1.bid and r1.claim.config_fingerprint == c1.fingerprint
    assert r1.claim.fresh == "none" and r1.claim.policy == "manual"
    assert {f.targ_id for f in r1.claim.files} == {lane_targ(n) for n in ("term", "session", "manifest", "invocation", "claim")}
    for f in r1.claim.files:
        local = next(l.path for l in f.blob.locations if l.store == "local")
        assert sha256_hex(Path(local).read_bytes()) == f.blob.blob_sha256 and f.blob.encoding == "json"
    claim_file = json.loads((lane_dir / "claim.json").read_bytes())
    assert claim_file["stack"]["bid"] == s1.bid and claim_file["config"]["bid"] == c1.bid
    # the package's lane slots are the CVM's digests of exactly those files (simulated here)
    pkg1 = json.loads(gzip.open(m1.evidence_ref).read())["PAYLOAD"]
    from pybb.attestation.ledger import slot_layout
    lane = {sp.asp_targid: pkg1[0]["RawEv"][sp.start] for sp in slot_layout(pkg1[1], lp.session) if sp.asp_targid and sp.asp_targid.startswith("claim:")}
    assert [sp.start for sp in slot_layout(pkg1[1], lp.session) if sp.asp_targid and sp.asp_targid.startswith("claim:")] == [2, 3, 4, 5, 6]
    for f in r1.claim.files:
        assert lane[f.targ_id] == base64.b64encode(bytes.fromhex(f.blob.blob_sha256)).decode()
    # the run's term digest in the lane equals the config bundle's input digest: run→config by CVM digests
    cfg_files = {f.targ_id: f.blob.blob_sha256 for f in ledger.get(c1.bid).config.files}
    assert cfg_files[input_targ("measure", "term")] == base64.b64decode(lane["claim:term"]).hex()

    # the reader's check (plan P.5)
    v = verify_claim(ledger, r1)
    assert v and v.stack_ok and v.config_ok and v.times_ok and v.stack_is_latest and v.pins_match
    assert v.constructor == "measure" and v.problems == []
    assert not verify_claim(ledger, r0).has_claim
    # a claim that names a fingerprint the stack bundle does not have is reported
    bad = r1.model_copy(update={"claim": r1.claim.model_copy(update={"stack_fingerprint": "AAAA"})})
    vb = verify_claim(ledger, bad)
    assert not vb and any("fingerprint" in p for p in vb.problems) and vb.stack_ok is False


def test_refresh_policies(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = _ctx_client(fake_stack)
    pid = proto.protocol_id

    def with_policy(p):
        return config.model_copy(update={"context": config.context.model_copy(update={"refresh": p})})

    assert refresh_due(with_policy("manual"), pid, {}) == (False, False)
    assert refresh_due(with_policy("manual"), pid, {}, demand=True) == (True, True)
    assert refresh_due(with_policy("every_run"), pid, {}) == (True, True)
    st = {}
    assert refresh_due(with_policy("every_episode"), pid, st) == (True, True)
    assert refresh_due(with_policy("every_episode"), pid, st) == (False, False)
    assert refresh_due(with_policy("every_episode"), "other", st) == (False, True)  # stack done, new protocol's config not
    assert refresh_due(with_policy("max_age:3600"), pid, {}) == (True, True)  # nothing cached yet
    measure_stack(client, ledger, config, summarizer_bin=fake_stack.summarizer)
    measure_config(client, proto, ledger, config)
    assert refresh_due(with_policy("max_age:3600"), pid, {}) == (False, False)
    assert refresh_due(with_policy("max_age:0"), pid, {}) == (True, True)
    with pytest.raises(LedgerError):
        refresh_due(with_policy("weekly"), pid, {})
    # refresh_if_due carries the policy out as ordinary measurements and labels the claim
    n_stack = len(ledger.bundles(role="stack"))
    assert refresh_if_due(client, proto, ledger, with_policy("every_run"), {}) == "both"
    assert len(ledger.bundles(role="stack")) == n_stack + 1
    assert refresh_if_due(client, proto, ledger, with_policy("manual"), {}) == "none"
    assert refresh_if_due(client, proto, ledger, with_policy("manual"), {}, demand=True) == "both"


def test_predicates_refresh_by_policy_and_on_demand(tmp_path, fake_stack, config):
    from pybb.attestation import make_measurement_predicate

    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = _ctx_client(fake_stack)
    cfg = config.model_copy(update={"context": config.context.model_copy(update={"refresh": "every_episode"})})
    predicate = make_measurement_predicate(client, {proto.protocol_id: proto}, ledger=ledger, ledger_config=cfg)
    m1 = predicate({"protocol": proto.protocol_id})
    assert m1, m1.error
    r1 = ledger.get(m1.bid)
    assert r1.claim is not None and r1.claim.fresh == "both" and r1.claim.policy == "every_episode"
    assert len(ledger.bundles(role="stack")) == 1 and len(ledger.bundles(role="config")) == 1
    assert r1.claim.stack_bid == ledger.bundles(role="stack")[0].bid
    # second run in the same episode: nothing re-measured, the claim names the same context
    predicate.forget({"protocol": proto.protocol_id})
    m2 = predicate({"protocol": proto.protocol_id})
    r2 = ledger.get(m2.bid)
    assert r2.claim.fresh == "none" and r2.claim.stack_bid == r1.claim.stack_bid and len(ledger.bundles(role="stack")) == 1
    # on demand: a measurement asking for fresh context re-measures both
    m3 = predicate({"protocol": proto.protocol_id, "context": "fresh"})
    r3 = ledger.get(m3.bid)
    assert r3.claim.fresh == "both" and r3.claim.stack_bid != r1.claim.stack_bid
    assert len(ledger.bundles(role="stack")) == 2 and verify_claim(ledger, r3)
