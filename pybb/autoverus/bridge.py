"""
Invoking Verus and AutoVerus, out-of-process.

AutoVerus (github.com/microsoft/verus-proof-synthesis) is Linux-only and
needs a Verus build, so it is run as a subprocess (see shell.py) rather
than imported: its `veval.py` calls `shutil.which("verus")` at *module
import* and raises TypeError when Verus is absent from PATH, which would
take down the host process rather than just the knowledge source.

Two things stop a "repair" from passing by cheating rather than proving.
Vacuous proofs (`assume(`/`admit()`) are rejected in knowledge_sources.py,
before Verus even runs. Weakening the contract is caught upstream:
AutoVerus compares the pre- and post-repair specs via lynette in its own
`code_change_is_safe`, which is active unless `--disable-safe` is passed —
and this bridge never passes it.

Note that a repair legitimately changing the *count* of verified items is
not evidence of either: AutoVerus inserts
`#[verifier::loop_isolation(false)]`, which folds a loop into its
enclosing function, so "2 verified" can honestly become "1 verified" with
no obligation lost.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .config import AutoVerusConfig, preflight
from .shell import ShellError, run_shell, to_wsl_path


class AutoVerusError(ShellError):
    """AutoVerus or Verus failed before producing a usable result."""


def _run_verus(path, *, config: AutoVerusConfig = None) -> str:
    """
    Verify one file with Verus; returns the combined output.

    A non-zero exit is the normal way Verus reports a failing proof, so it
    is not an error here — only the absence of any output is.
    """
    config = config or AutoVerusConfig()
    target = to_wsl_path(path)
    result = run_shell(f'"{config.verus}" "{target}"', config.verus_timeout_s)
    output = (result.stdout or "") + (result.stderr or "")
    if not output.strip():
        raise AutoVerusError(
            f"verus produced no output (exit {result.returncode})")
    return output


def _autoverus_config(config: AutoVerusConfig) -> dict:
    """
    A config for this run. The checked-in config-artifact-openai.json points
    at the Docker image's layout (/home/appuser/...), which does not resolve
    anywhere else, so we generate one rather than editing the repo's. An
    empty aoai_api_key is intentional: AutoVerus falls back to the
    OPENAI_API_KEY environment variable.
    """
    return {
        "use_openai": True,
        "aoai_api_base": ["https://api.openai.com/v1/"],
        "aoai_api_version": "2024-12-01-preview",
        "aoai_api_key": [],
        "aoai_max_retries": 5,
        "max_token": 4096,
        "aoai_generation_model": config.model,
        "aoai_debug_model": config.model,
        "verus_path": config.verus,
        "example_path": f"{config.code_dir()}/examples",
        "lemma_path": f"{config.code_dir()}/lemmas",
        "util_path": f"{config.root()}/utils",
    }


def _run_autoverus(path, repair_steps: int = 5, *,
                   config: AutoVerusConfig = None, api_key: str = None,
                   keep_intermediate: bool = False) -> str:
    """
    Repair the proof in `path` with AutoVerus; returns the repaired source.
    Does not write the file — the knowledge source does that, so file
    mutation stays in one place and test doubles stay trivial.
    """
    config = config or AutoVerusConfig()
    api_key = api_key or os.environ.get("OPENAI_API_KEY")  # read at call time
    if not api_key:
        raise AutoVerusError("OPENAI_API_KEY is not set")

    # The key was just resolved above, possibly from an argument rather
    # than the environment, so preflight's verdict on it is not the one
    # that counts here.
    problems = [p for p in preflight(config) if "OPENAI_API_KEY" not in p]
    if problems:
        raise AutoVerusError(
            "AutoVerus environment is not usable: " + "; ".join(problems))

    scratch = Path(tempfile.mkdtemp(prefix="pybb_autoverus_"))
    try:
        src, out = scratch / "input.rs", scratch / "output.rs"
        cfg, marker = scratch / "config.json", scratch / ".start"
        shutil.copyfile(path, src)
        cfg.write_text(json.dumps(_autoverus_config(config), indent=2))
        marker.touch()

        # cwd must be the AutoVerus module directory: its lynette.py builds
        # `--manifest-path=../utils/lynette/source/Cargo.toml` and utils.py
        # defaults util_path="../utils", both relative to cwd. Running from
        # a scratch directory silently breaks the repair path.
        clean = "" if keep_intermediate else (
            f' && find . -maxdepth 1 -type d \\( -name "intermediate-*" -o '
            f'-name "output-intermediate-temp-*" \\) '
            f'-newer "{to_wsl_path(marker)}" -exec rm -rf {{}} +')
        script = (
            # veval.py resolves verus with shutil.which at import, so the
            # binary has to be on PATH before main.py is even loaded.
            f'export PATH="{config.verus_dir()}:$PATH" && '
            f'cd "{config.code_dir()}" && '
            f'"{config.python_bin()}" main.py --mode repair '
            f'--input "{to_wsl_path(src)}" --output "{to_wsl_path(out)}" '
            f'--config "{to_wsl_path(cfg)}" --repair {int(repair_steps)}'
            f'{clean}'
        )
        result = run_shell(script, config.autoverus_timeout_s,
                           extra_env={"OPENAI_API_KEY": api_key})
        if not out.is_file():
            detail = (result.stderr or result.stdout or "").strip()[-400:]
            raise AutoVerusError(
                f"AutoVerus produced no output (exit {result.returncode}): "
                f"{detail}")
        return out.read_text()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
