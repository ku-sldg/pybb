"""
Copland data model and term utilities for the CVM attestation stack.

Typed Pydantic models mirror the JSON wire format accepted by the Rocq CVM
binary (ku-sldg/cvm) as exercised by cvm-mcp and rust-am-clients. The models
are adapted from HEAL-demo's cvm_headers.py (ku-sldg/HEAL-demo), updated for
the current CVM JSON schema:

- lseq/att/bseq/bpar TERM_BODY values are JSON lists
- bseq/bpar splits are strings ("both_paths" | "left_path" | "right_path")
- ASPC bodies sent to the CVM carry only ASP_ID and ASP_ARGS; ASP_TARG_ID
  appears in authored term files purely to reference asp_args entries and is
  stripped by normalize_term before execution
- session ASP_Types entries use the {"FWD": {...}, "ATTRS": [...]} shape

The dict-level term utilities (inject_asp_args, normalize_term) operate on
plain parsed JSON, since protocol assembly is defined over authored files
whose shape may drift ahead of the typed models.
inject_asp_args and normalize_term are adapted from cvm-mcp's
protocol_loader.py, the reference integration for this CVM build.
"""

from __future__ import annotations

import copy
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

# Type aliases
Plc = str
ASP_ID = str
TARG_ID = str


class ASP_PARAMS(BaseModel):
    ASP_ID: ASP_ID
    ASP_ARGS: Optional[Any] = None
    ASP_TARG_ID: Optional[TARG_ID] = None
    ASP_PLC: Optional[Plc] = None


class ASP_NULL(BaseModel):
    ASP_CONSTRUCTOR: Literal["NULL"] = "NULL"


class ASP_CPY(BaseModel):
    ASP_CONSTRUCTOR: Literal["CPY"] = "CPY"


class ASP_ASPC(BaseModel):
    ASP_CONSTRUCTOR: Literal["ASPC"] = "ASPC"
    ASP_BODY: ASP_PARAMS


class ASP_SIG(BaseModel):
    ASP_CONSTRUCTOR: Literal["SIG"] = "SIG"


class ASP_HSH(BaseModel):
    ASP_CONSTRUCTOR: Literal["HSH"] = "HSH"


class ASP_ENC(BaseModel):
    ASP_CONSTRUCTOR: Literal["ENC"] = "ENC"
    ASP_BODY: Plc


class ASP_APPR(BaseModel):
    ASP_CONSTRUCTOR: Literal["APPR"] = "APPR"


ASP = Annotated[
    Union[ASP_NULL, ASP_CPY, ASP_ASPC, ASP_SIG, ASP_HSH, ASP_ENC, ASP_APPR],
    Field(discriminator="ASP_CONSTRUCTOR"),
]

SplitStr = Literal["both_paths", "left_path", "right_path"]


class Term_asp(BaseModel):
    TERM_CONSTRUCTOR: Literal["asp"] = "asp"
    TERM_BODY: ASP


class Term_att(BaseModel):
    TERM_CONSTRUCTOR: Literal["att"] = "att"
    TERM_BODY: Tuple[Plc, "Term"]


class Term_lseq(BaseModel):
    TERM_CONSTRUCTOR: Literal["lseq"] = "lseq"
    TERM_BODY: Tuple["Term", "Term"]


class Term_bseq(BaseModel):
    TERM_CONSTRUCTOR: Literal["bseq"] = "bseq"
    TERM_BODY: Tuple[SplitStr, "Term", "Term"]


class Term_bpar(BaseModel):
    TERM_CONSTRUCTOR: Literal["bpar"] = "bpar"
    TERM_BODY: Tuple[SplitStr, "Term", "Term"]


Term = Annotated[
    Union[Term_asp, Term_att, Term_lseq, Term_bseq, Term_bpar],
    Field(discriminator="TERM_CONSTRUCTOR"),
]


class EvidenceT_mt_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["mt_evt"] = "mt_evt"


class EvidenceT_nonce_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["nonce_evt"] = "nonce_evt"
    EvidenceT_BODY: Any = None


class EvidenceT_asp_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["asp_evt"] = "asp_evt"
    EvidenceT_BODY: Tuple[Plc, ASP_PARAMS, "EvidenceT"]


class EvidenceT_left_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["left_evt"] = "left_evt"
    EvidenceT_BODY: "EvidenceT"


class EvidenceT_right_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["right_evt"] = "right_evt"
    EvidenceT_BODY: "EvidenceT"


class EvidenceT_split_evt(BaseModel):
    EvidenceT_CONSTRUCTOR: Literal["split_evt"] = "split_evt"
    EvidenceT_BODY: Tuple["EvidenceT", "EvidenceT"]


EvidenceT = Annotated[
    Union[
        EvidenceT_mt_evt,
        EvidenceT_nonce_evt,
        EvidenceT_asp_evt,
        EvidenceT_left_evt,
        EvidenceT_right_evt,
        EvidenceT_split_evt,
    ],
    Field(discriminator="EvidenceT_CONSTRUCTOR"),
]


class RawEv(BaseModel):
    RawEv: List[str]


Evidence = Tuple[RawEv, EvidenceT]


def empty_evidence() -> list:
    """Initial evidence for a run request, in wire format."""
    return [{"RawEv": []}, {"EvidenceT_CONSTRUCTOR": "mt_evt"}]


class GlobalContext(BaseModel):
    # ASP_Types values keep the raw {"FWD": {...}, "ATTRS": [...]} shape; its
    # inner field names (e.g. "_BODY") are not stable across CVM builds.
    ASP_Types: Dict[ASP_ID, Any]
    ASP_Comps: Dict[ASP_ID, ASP_ID]


class Attestation_Session(BaseModel):
    Session_Plc: Plc
    Plc_Mapping: Dict[Plc, str]
    PubKey_Mapping: Dict[Plc, str]
    Session_Context: GlobalContext


class ProtocolRunRequest(BaseModel):
    TYPE: str = "REQUEST"
    ACTION: str = "RUN"
    REQ_PLC: Plc
    TO_PLC: Optional[Plc] = None
    TERM: Term
    EVIDENCE: Evidence
    ATTESTATION_SESSION: Attestation_Session


class ProtocolRunResponse(BaseModel):
    TYPE: str
    ACTION: str
    SUCCESS: bool
    # [RawEv-dict, EvidenceT-dict] on success; kept lenient because response
    # evidence is walked as plain dicts by pybb.attestation.appraisal.
    PAYLOAD: Any = None


class Manifest(BaseModel):
    ASPS: List[ASP_ID]
    ASP_FS_MAP: Dict[str, str] = {}
    POLICY: List[Any] = []


for _m in (
    Term_asp, Term_att, Term_lseq, Term_bseq, Term_bpar,
    EvidenceT_asp_evt, EvidenceT_left_evt, EvidenceT_right_evt,
    EvidenceT_split_evt, ProtocolRunRequest,
):
    _m.model_rebuild()


# ── Dict-level term utilities ─────────────────────────────────────────────────

def with_asp_targids(targets: dict) -> dict:
    """Stamp each target's args with its own id under the dedicated key
    "asp_targid", making evidence self-describing: the id rides in
    ASP_ARGS through terms, CVM evidence trees, provisioning bundles, and
    appraisal summaries, so target attribution is a field read rather
    than arg-matching. Every target-creation site applies this
    (derivation-time injection — the committed artifact IS the wire
    truth); ProtocolDir.load rejects drift between the key and the dict
    key."""
    return {targ: {**args, "asp_targid": targ}
            for targ, args in targets.items()}


def iter_aspc_bodies(term: dict):
    """Yield every ASPC ASP_BODY dict in the term, in DFS order."""
    if not isinstance(term, dict):
        return
    body = term.get("TERM_BODY")
    if term.get("TERM_CONSTRUCTOR") == "asp":
        if isinstance(body, dict) and body.get("ASP_CONSTRUCTOR") == "ASPC":
            yield body.get("ASP_BODY", {})
        return
    if isinstance(body, list):
        for child in body:
            yield from iter_aspc_bodies(child)


def inject_asp_args(term: dict, asp_args_map: dict) -> dict:
    """
    Return a deep copy of term with ASP_ARGS filled in from asp_args_map,
    which has the rust-rodeo-client shape:

        {"<asp_id>": {"<targ_id>": {<args>}, ...}, ...}

    ASPC nodes with an ASP_TARG_ID match by target id; nodes with only
    inline args (legacy format, e.g. gumbo_l1) match the entry whose
    'filepath' equals the node's. Node args take precedence over map args.
    """
    term = copy.deepcopy(term)
    for asp_body in iter_aspc_bodies(term):
        asp_id = asp_body.get("ASP_ID", "")
        targ_id = asp_body.get("ASP_TARG_ID", "")
        mapped = None
        if asp_id and targ_id:
            mapped = asp_args_map.get(asp_id, {}).get(targ_id)
        elif asp_id:
            node_fp = (asp_body.get("ASP_ARGS") or {}).get("filepath", "")
            if node_fp:
                for entry in asp_args_map.get(asp_id, {}).values():
                    if entry.get("filepath") == node_fp:
                        mapped = entry
                        break
        if mapped:
            asp_body["ASP_ARGS"] = {**mapped, **(asp_body.get("ASP_ARGS") or {})}
    return term


_ASPC_BODY_KEYS = {"ASP_ID", "ASP_ARGS"}


def normalize_term(term: dict) -> dict:
    """
    Return a deep copy of term reduced to what the current CVM decoder
    accepts: ASPC bodies stripped to ASP_ID and ASP_ARGS.
    """
    term = copy.deepcopy(term)
    for asp_body in iter_aspc_bodies(term):
        for key in list(asp_body.keys()):
            if key not in _ASPC_BODY_KEYS:
                del asp_body[key]
    return term
