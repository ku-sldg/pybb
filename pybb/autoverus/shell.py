"""
Running an external tool that a knowledge source cannot import.

A knowledge source whose tool is a verifier, a prover, or a build system
invokes it out-of-process rather than importing it. This module is that
boundary: a bash script goes in, a completed process comes out.

Where the script runs is decided by the platform, not by configuration.
On Linux and macOS it is a local bash. On Windows it is bash inside WSL.

Secrets cross this boundary through `extra_env`, never through the
command string: WSL does not inherit the Windows environment, so
variables are forwarded explicitly via WSLENV, and argv is world-readable
through /proc.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

# The distro used on Windows. Edit only if yours is not the default one;
# `wsl -l` lists the installed names.
DISTRO = "Ubuntu"

DEFAULT_TIMEOUT_S = 300

# Windows is the only platform that needs the hop: everything reached
# through here runs natively on Linux and macOS.
VIA_WSL = os.name == "nt"


class ShellError(RuntimeError):
    """A tool invocation failed before producing a usable result."""


def to_wsl_path(path) -> str:
    """
    Translate a Windows path to its WSL /mnt/<drive> equivalent.

    Paths that are already POSIX pass through unchanged, so this is a
    no-op when the caller is itself running on Linux and a no-op on a path
    that already names a location inside the distro.
    """
    text = str(path)
    drive, rest = os.path.splitdrive(text)
    rest = rest.replace("\\", "/")
    if not drive:
        return rest
    return f"/mnt/{drive[0].lower()}{rest}"


def run_shell(script: str, timeout_s: int = None,
              extra_env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """
    Run a bash script where the tools live and return the completed process.

    A non-zero exit is NOT an error here -- verifiers routinely use exit
    codes to report a failing proof, and that is a verdict, not a failure
    to run. Only an invocation that could not happen raises `ShellError`.

    `extra_env` entries reach the tool through the environment rather than
    argv. On Windows they additionally need WSLENV, which is the only way
    a variable crosses into the distro.
    """
    timeout_s = timeout_s or DEFAULT_TIMEOUT_S
    env = None
    if extra_env:
        env = dict(os.environ)
        env.update(extra_env)
        if VIA_WSL:
            existing = env.get("WSLENV", "")
            passthrough = list(extra_env)
            env["WSLENV"] = ":".join([existing] + passthrough) if existing \
                else ":".join(passthrough)
    command = ["wsl", "-d", DISTRO, "-e", "bash", "-lc", script] if VIA_WSL \
        else ["bash", "-lc", script]
    try:
        return subprocess.run(
            command,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout_s, env=env,
        )
    except FileNotFoundError:
        raise ShellError("wsl not found on PATH - WSL is required to reach "
                         "Linux-only tools from Windows" if VIA_WSL
                         else "bash not found on PATH")
    except subprocess.TimeoutExpired:
        raise ShellError(f"command timed out after {timeout_s}s")
    except OSError as e:
        raise ShellError(f"invocation failed: {e}")
