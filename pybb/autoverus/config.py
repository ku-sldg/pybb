"""
SETUP: edit the two paths directly below, and set OPENAI_API_KEY in your
environment.
"""

from __future__ import annotations

import os
import shutil
from pathlib import PurePosixPath

from pydantic import BaseModel

from .shell import VIA_WSL, ShellError, run_shell, to_wsl_path

# ==========================================================================
# EDIT THESE PATHS to point at your own installation.
#
# On Windows they are paths *inside* WSL, because AutoVerus is Linux-only:
# run `wsl`, cd to each one, and paste what `pwd` prints.
#
# Absolute paths only -- no `~`, no `$HOME`. These are not only run as
# shell words; some are written into the config file handed to AutoVerus,
# and nothing expands a variable inside a JSON string. Preflight rejects
# them rather than letting that surface as a FileNotFoundError ten minutes
# into a repair.
# ==========================================================================

# The Verus binary itself, not a directory. It does NOT need to be on PATH
# -- this path is what puts it there for AutoVerus.
VERUS = "/Users/adampetz/Claude_workspace/verus-arm64-macos/verus"

# Your verus-proof-synthesis checkout. Point at the checkout root; if
# yours predates upstream's code/ -> autoverus/ rename, point at the
# code/ directory instead.
AUTOVERUS = "/Users/adampetz/Claude_workspace/verus-proof-synthesis"

# The Python that has AutoVerus's dependencies installed. Leave blank to
# use <checkout>/.venv/bin/python, which is where the setup instructions
# put it.
AUTOVERUS_PYTHON = ""

# ==========================================================================

# The OpenAI key is read from the
# environment at call time, in bridge._run_autoverus.


class AutoVerusConfig(BaseModel):
    """
    The tools this bridge invokes, and how long to wait for them.

    Field defaults are the module constants, so `AutoVerusConfig()` is the
    machine as configured; passing fields explicitly is for tests and for
    callers driving more than one installation. This mirrors `CvmConfig`
    in the attestation package, where the same pattern carries binary
    locations into predicate factories.
    """

    verus: str = VERUS
    autoverus: str = AUTOVERUS      # checkout root, or the dir holding main.py
    python: str = AUTOVERUS_PYTHON  # "" -> <checkout>/.venv/bin/python
    model: str = "gpt-4o"
    verus_timeout_s: int = 300
    autoverus_timeout_s: int = 1800

    def code_dir(self) -> str:
        """
        The AutoVerus module directory: the one holding main.py.

        Upstream `2f9aff36` renamed `code/` -> `autoverus/`. Rather than
        probe for which vintage is on disk, the current layout is assumed
        and an older checkout is named directly (`.../code`) -- so this
        stays a pure function and preflight can quote the exact path it
        expected main.py at.
        """
        path = PurePosixPath(str(self.autoverus).replace("\\", "/").rstrip("/"))
        if path.name == "main.py":
            return str(path.parent)
        if path.name in ("autoverus", "code"):
            return str(path)
        return str(path / "autoverus")

    def root(self) -> str:
        """The checkout root, whichever of its paths was given."""
        return str(PurePosixPath(self.code_dir()).parent)

    def python_bin(self) -> str:
        return self.python or f"{self.root()}/.venv/bin/python"

    def main_py(self) -> str:
        return f"{self.code_dir()}/main.py"

    def verus_dir(self) -> str:
        """
        The directory to prepend to PATH so AutoVerus can find Verus.

        AutoVerus resolves `verus` at import time via shutil.which, so it
        has to be on PATH for the tool to start at all. Deriving that from
        the binary's own location is what saves anyone from having to
        symlink their Verus build into ~/.cargo/bin.
        """
        return str(PurePosixPath(to_wsl_path(self.verus)).parent)


def preflight(config: AutoVerusConfig = None) -> list[str]:
    """
    Every unmet prerequisite for a live run, or [] when ready.

    Returns a problem list rather than a bool so a caller can tell someone
    exactly what to fix, and reports all failures at once rather than the
    first — the same shape as ReadinessReport.problems in the attestation
    package, where a missing binary is a configuration failure rather than
    an integrity failure.

    Each message names the path that was looked for and the constant that
    would change it, so fixing setup never requires reading this file.
    """
    config = config or AutoVerusConfig()
    problems = []
    if not os.environ.get("OPENAI_API_KEY"):
        problems.append(
            "OPENAI_API_KEY is not set (AutoVerus calls the OpenAI API)")
    # Caught here rather than at the shell, where it would "work": bash
    # expands $HOME in the script, but example_path and lemma_path also go
    # into AutoVerus's JSON config, where it stays a literal and fails
    # mid-repair with a path nobody typed.
    unexpanded = [f"{name} is {value!r} - use an absolute path; ~ and $HOME "
                  "are not expanded (run `pwd` there and paste that)"
                  for name, value in (("VERUS", config.verus),
                                      ("AUTOVERUS", config.autoverus),
                                      ("AUTOVERUS_PYTHON", config.python))
                  if value.startswith("~") or "$" in value]
    if unexpanded:
        return problems + unexpanded  # checking them below would test literals
    if VIA_WSL and shutil.which("wsl") is None:
        problems.append("wsl not found on PATH - WSL is required to run "
                        "AutoVerus, which is Linux-only")
        return problems  # nothing further is checkable

    # One round trip: three paths, three tokens back. `-x` rather than `-f`
    # on the binaries, since a non-executable file cannot be run either.
    script = (
        f'[ -x "{config.verus}" ] && echo verus\n'
        f'[ -f "{config.main_py()}" ] && echo main_py\n'
        f'[ -x "{config.python_bin()}" ] && echo python\n'
    )
    try:
        found = set(run_shell(script, 60).stdout.split())
    except ShellError as e:
        problems.append(f"could not check the tool paths: {e}")
        return problems

    if "verus" not in found:
        problems.append(
            f"no Verus binary at {config.verus} "
            "- edit VERUS at the top of pybb/autoverus/config.py")
    if "main_py" not in found:
        problems.append(
            f"no AutoVerus main.py at {config.main_py()} "
            "- edit AUTOVERUS to point at your verus-proof-synthesis checkout")
    if "python" not in found:
        problems.append(
            f"no Python at {config.python_bin()} - create the virtualenv "
            f"(cd {config.root()} && python3 -m venv .venv && "
            ".venv/bin/pip install -r requirements.txt) "
            "or set AUTOVERUS_PYTHON to the interpreter that has them")
    return problems
