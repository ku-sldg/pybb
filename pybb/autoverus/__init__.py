"""
AutoVerus proof repair on the blackboard: a standalone repair rung.

A Rust file carries a Verus contract whose proof fails. The blackboard
asks "does this file verify?", `AutoVerusRepairKS` answers the failure by
running AutoVerus in repair mode, and the same run re-verifies the result
— detect, repair, confirm, in one `controller.run()`.

There is no replay, recording, or offline mode, by design. Either a real
AutoVerus repairs a real file and a real Verus judges the result, or
`preflight()` reports what is missing and the caller refuses to run. A
demo that fabricates an episode is the same category of mistake this
codebase exists to prevent.

This package depends on nothing but pybb's core. It is a self-contained
repair workflow, not part of the attestation stack: no CVM, no Copland
protocols, no golden tree. `AutoVerusRepairKS` is a plain `KnowledgeSource`
and can later be dropped into an attestation chain.

    config.py             where the tools are; edit the paths there
    bridge.py             running Verus and AutoVerus out-of-process
    knowledge_sources.py  the predicate and the repair rung
    shell.py              the subprocess boundary (reached by full path)
"""

from .bridge import AutoVerusError
from .config import AutoVerusConfig, preflight
from .knowledge_sources import (
    AutoVerusRepairKS,
    VerusResult,
    file_digest,
    find_cheat,
    make_verus_predicate,
    parse_verus_output,
    source_measurement,
)

__all__ = [
    "AutoVerusConfig",
    "AutoVerusError",
    "AutoVerusRepairKS",
    "VerusResult",
    "file_digest",
    "find_cheat",
    "make_verus_predicate",
    "parse_verus_output",
    "preflight",
    "source_measurement",
]
