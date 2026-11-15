"""
Environment doctor.

Tells the user, in plain words, what is ready and what is missing. Nothing
here is decorative: every check corresponds to something the pipeline really
uses (Java for the bundle build, git for the project template, Apktool/JADX
for decompilation, a registry token for Morphe packages).
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(legacy_windows=False)


def _run(command: List[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return (result.stdout or result.stderr or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _java_version() -> Tuple[bool, str]:
    executable = shutil.which("java")
    if not executable:
        return False, "not installed"
    output = _run([executable, "-version"])
    match = re.search(r'version "?(\d+)', output)
    if not match:
        return False, output.splitlines()[0] if output else "unknown version"
    major = int(match.group(1))
    return major >= 17, f"version {major}"


REGISTRY_PROBE = (
    "https://maven.pkg.github.com/MorpheApp/registry/"
    "app/morphe/morphe-patcher/maven-metadata.xml"
)


def _registry_credentials() -> Tuple[str, str]:
    """Reads gpr.user / gpr.key without ever printing the secret."""
    user = key = ""
    properties = Path.home() / ".gradle" / "gradle.properties"
    if properties.exists():
        try:
            for line in properties.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("gpr.user"):
                    user = line.split("=", 1)[1].strip()
                elif line.startswith("gpr.key"):
                    key = line.split("=", 1)[1].strip()
        except OSError:
            pass

    user = user or os.environ.get("GITHUB_ACTOR") or os.environ.get("GPR_USER") or "token"
    key = key or os.environ.get("GITHUB_TOKEN") or os.environ.get("GPR_KEY") or ""
    return user, key


def _registry_check() -> Tuple[bool, str, bool]:
    """Returns ``(ok, description, blocking)``.

    Presence of a token is not proof: an expired token, or one without the
    ``read:packages`` scope, makes Gradle fail later with a cryptic 401. The
    probe is one cheap authenticated request; a network failure is reported as
    "not verified" instead of a false alarm.
    """
    user, key = _registry_credentials()
    if not key:
        return False, "missing (one-time setup)", False

    token = base64.b64encode(f"{user}:{key}".encode()).decode()
    request = urllib.request.Request(
        REGISTRY_PROBE,
        headers={
            "Authorization": f"Basic {token}",
            "Accept": "application/xml",
            "User-Agent": "morphy-creator-doctor",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status in (200, 206):
                return True, f"valid (user {user})", False
            return False, f"unexpected HTTP {response.status}", False
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, f"rejected (HTTP {exc.code}): expired or missing 'read:packages'", True
        if exc.code == 404:
            return True, "registry reachable (artifact listing unavailable)", False
        return False, f"registry answered HTTP {exc.code}", False
    except Exception as exc:  # noqa: BLE001 - offline is not an error
        return False, f"present, not verified ({type(exc).__name__})", False


class MorphyDoctor:
    """Checks the toolchain and explains what to do about gaps."""

    @staticmethod
    def run_diagnostics() -> bool:
        table = Table(title="Morphy environment check")
        table.add_column("Component", style="cyan")
        table.add_column("Needed for", style="magenta")
        table.add_column("Status")
        table.add_column("Details", style="dim")

        missing: List[str] = []

        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ok = sys.version_info >= (3, 10)
        table.add_row("Python", "Morphy itself", _status(ok), f"{version}")
        if not ok:
            missing.append("Install Python 3.10 or newer from python.org.")

        java_ok, java_details = _java_version()
        table.add_row("Java 17+", "compiling the .mpp bundle", _status(java_ok), java_details)
        if not java_ok:
            missing.append("Install a JDK 17 or newer (Adoptium Temurin is free).")

        git = shutil.which("git")
        table.add_row("Git", "downloading the Morphe project template", _status(bool(git)), git or "not found")
        if not git:
            missing.append("Install Git from git-scm.com.")

        apktool = shutil.which("apktool")
        table.add_row("Apktool", "decompiling apps (optional)", _status(bool(apktool), optional=True),
                      apktool or "not found - decompilation unavailable")
        jadx = shutil.which("jadx")
        table.add_row("JADX", "Java source view (optional)", _status(bool(jadx), optional=True),
                      jadx or "not found - not required")

        token_ok, token_details, token_blocking = _registry_check()
        if token_ok:
            token_status = "[green]OK[/green]"
        elif token_blocking:
            token_status = "[red]rejected[/red]"
        else:
            token_status = "[yellow]missing[/yellow]"
        table.add_row(
            "Morphe registry token",
            "building the installable .mpp",
            token_status,
            token_details,
        )
        if token_blocking:
            missing.append(
                "Replace the GitHub token in %USERPROFILE%\\.gradle\\gradle.properties: "
                "the current one is rejected by GitHub Packages. Create a classic token "
                "with the 'read:packages' scope."
            )

        console.print(table)

        console.print(Panel(
            "[bold]What actually happens[/bold]\n"
            "Morphy reads the APK itself (no external tool needed) and writes the "
            "patch code. Turning that code into an installable .mpp uses the official "
            "Morphe Gradle toolchain, which needs Java, Git, and a GitHub token with "
            "the 'read:packages' permission.",
            title="Good to know",
            border_style="cyan",
        ))

        if not token_ok and not token_blocking:
            console.print(
                "[yellow]Note:[/yellow] patch sources can be generated now. "
                "The GitHub token is only needed to compile an installable .mpp."
            )

        if missing:
            console.print("[bold yellow]To finish the installation:[/bold yellow]")
            for item in missing:
                console.print(f"  - {item}")
            return False

        console.print("[bold green]Everything needed is installed.[/bold green]")
        return True


def _status(ok: bool, optional: bool = False) -> str:
    if ok:
        return "[green]OK[/green]"
    return "[yellow]missing[/yellow]" if optional else "[red]missing[/red]"
