"""
Cross-platform subprocess helper.

On Windows, Apktool and JADX are distributed as ``.cmd`` / ``.bat`` wrappers.
Those cannot be launched through :func:`subprocess.run` without ``shell=True``,
so this helper resolves the executable on PATH and transparently handles the
Windows script case for every adapter.
"""
import os
import shutil
import subprocess
from typing import List


def resolve_executable(executable: str) -> str:
    """Returns the absolute path of an executable when it can be found on PATH."""
    return shutil.which(executable) or executable


def run_command(cmd: List[str]) -> subprocess.CompletedProcess:
    """Runs a command, raising CalledProcessError/FileNotFoundError like subprocess.run."""
    resolved = resolve_executable(cmd[0])
    args = [resolved, *cmd[1:]]

    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return subprocess.run(
            subprocess.list2cmdline(args),
            capture_output=True,
            text=True,
            check=True,
            shell=True,
        )

    return subprocess.run(args, capture_output=True, text=True, check=True)
