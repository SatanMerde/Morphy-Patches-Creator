"""
Writing patches to disk and turning them into a real Morphe bundle.

A Morphe ``.mpp`` is a JAR/ZIP that contains compiled patch classes and a
``classes.dex`` produced by D8. That compilation needs Gradle plus the Morphe
Maven registry, so this module never pretends: it either runs the official
build and hands back a real ``.mpp``, or it hands back a ready-to-build
project archive and says so plainly.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from morphy_creator.core.plan import PatchPlan
from morphy_creator.synthesizer import kotlin

TEMPLATE_URL = "https://github.com/MorpheApp/morphe-patches-template.git"
TEMPLATE_PATCH_DIR = Path("patches") / "src" / "main" / "kotlin"

# A wrong import is a mechanical compile error the writer can fix without
# guessing: the symbol is already named in the compiler diagnostic and the
# package is one the synthesizer itself emits.
MAX_BUILD_ATTEMPTS = 3
_KNOWN_API_IMPORTS = {
    "Fingerprint": "app.morphe.patcher.Fingerprint",
    "match": "app.morphe.patcher.match",
    "literal": "app.morphe.patcher.literal",
    "methodCall": "app.morphe.patcher.methodCall",
    "instructionMatches": "app.morphe.patcher.instructionMatches",
    "returnEarly": "app.morphe.patcher.util.returnEarly",
    "replaceInstruction": "app.morphe.patcher.extensions.InstructionExtensions.replaceInstruction",
    "Compatibility": "app.morphe.patcher.patch.Compatibility",
    "AppTarget": "app.morphe.patcher.patch.AppTarget",
    "patch": "app.morphe.patcher.patch.patch",
}


@dataclass
class BuildResult:
    """Outcome of packaging: either an installable bundle or a buildable project."""

    path: Path
    kind: str                       # "mpp" | "project"
    message: str
    next_steps: List[str] = field(default_factory=list)
    repairs: List[str] = field(default_factory=list)

    @property
    def is_bundle(self) -> bool:
        return self.kind == "mpp"


class PatchWriter:
    """Renders Kotlin sources and packages them."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    # -- sources ---------------------------------------------------------------
    def write(self, plan: PatchPlan) -> Path:
        source = kotlin.render(plan)
        package = _package_of(source)
        relative = Path(*package.split(".")) / f"{plan.class_name}.kt"
        destination = self.output_dir / "src" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
        return destination

    # -- bundle ----------------------------------------------------------------
    def build_bundle(self, patch_files: Iterable[Path], allow_network: bool = True) -> BuildResult:
        files = [Path(path) for path in patch_files if Path(path).suffix == ".kt"]
        dist = self.output_dir / "dist"
        dist.mkdir(parents=True, exist_ok=True)

        if not files:
            return BuildResult(
                path=dist,
                kind="project",
                message="No patch file to package.",
                next_steps=["Run the wizard again and pick at least one goal."],
            )

        project = self.output_dir / "project"
        if not (project / "settings.gradle.kts").exists():
            if not allow_network:
                return self._project_only(
                    dist, files, "Network access is disabled; no Gradle project was prepared."
                )
            cloned, error = _clone_template(project)
            if not cloned:
                return self._project_only(
                    dist, files, f"Could not download the Morphe project template: {error}"
                )

        copied = _copy_sources(project, files)
        if not copied:
            return self._project_only(dist, files, "Could not copy the patch sources into the project.")

        missing = _missing_build_requirements(project)
        if missing:
            return self._project_only(dist, files, " ".join(missing))

        built, log = _run_gradle(project)
        repairs: List[str] = []
        attempts = 1
        while not built and attempts < MAX_BUILD_ATTEMPTS:
            fixes = _repair_missing_imports(files, log)
            if not fixes:
                break
            repairs.extend(fixes)
            if not _copy_sources(project, files):
                break
            attempts += 1
            built, log = _run_gradle(project)

        if not built:
            return self._project_only(dist, files, log, repairs=repairs)

        mpp = _newest_bundle(project)
        if mpp is None:
            return self._project_only(
                dist, files, "The build finished but no .mpp file was produced.",
                repairs=repairs,
            )

        target = dist / mpp.name
        shutil.copy2(mpp, target)
        return BuildResult(
            path=target,
            kind="mpp",
            message="Installable Morphe bundle created.",
            next_steps=[
                f"Copy {target.name} to your phone.",
                "Open Morphe Manager, import the bundle, choose the app and apply.",
            ],
            repairs=repairs,
        )

    # -- fallback --------------------------------------------------------------
    def _project_only(
        self,
        dist: Path,
        files: List[Path],
        reason: str,
        repairs: Optional[List[str]] = None,
    ) -> BuildResult:
        archive = dist / "morphy-project.zip"
        source_root = self.output_dir / "src"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in files:
                relative = file.relative_to(source_root) if file.is_relative_to(source_root) else Path(file.name)
                zf.write(file, Path("patch-sources") / relative)

        repairs = list(repairs or [])
        auth_problem = any(
            marker in reason.lower()
            for marker in (
                "401", "403", "unauthorized", "forbidden", "read:packages",
                "registry token", "registry credentials", "resolve plugin artifact",
            )
        )
        if auth_problem:
            next_steps = [
                "Your patch code is ready. Only the GitHub package token is blocking the build.",
                "1. Open https://github.com/settings/tokens and replace the current token.",
                "2. When creating it, tick the 'read:packages' scope (nothing else is needed).",
                "3. In %USERPROFILE%\\.gradle\\gradle.properties set: gpr.user=<your GitHub username> and gpr.key=<new token>.",
                "4. Run: morphy-creator build <this folder>",
            ]
        else:
            next_steps = [
                "Your patch code is ready, but it still has to be compiled into a .mpp bundle.",
                "1. Install a JDK 17 or newer (already present here if 'morphy-creator doctor' passes).",
                "2. Create a GitHub token with the 'read:packages' permission.",
                "3. Add it to %USERPROFILE%\\.gradle\\gradle.properties as: gpr.user=<github username> and gpr.key=<token>",
                "4. Run: morphy-creator build <this folder>",
            ]
        message = reason
        if repairs:
            message = (
                reason
                + "\n\nAutomatic repair attempted: "
                + "; ".join(repairs)
            )
        return BuildResult(
            path=archive,
            kind="project",
            message=message,
            next_steps=next_steps,
            repairs=repairs,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _package_of(source: str) -> str:
    match = re.search(r"^package\s+([A-Za-z0-9_.]+)", source, re.MULTILINE)
    return match.group(1) if match else "app.morphe.patches.custom"


def _clone_template(project: Path) -> tuple:
    if not shutil.which("git"):
        return False, "git is not installed"
    project.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", TEMPLATE_URL, str(project)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:400]
    return True, ""


def _copy_sources(project: Path, files: List[Path]) -> bool:
    root = project / TEMPLATE_PATCH_DIR
    if not root.exists():
        return False
    for file in files:
        source = file.read_text(encoding="utf-8")
        package_path = Path(*_package_of(source).split("."))
        destination = root / package_path / file.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    return True


def _missing_api_symbols(log: str) -> List[str]:
    """Symbols the Kotlin compiler called unresolved, limited to known APIs."""
    found: List[str] = []
    for line in log.splitlines():
        lowered = line.lower()
        if "unresolved reference" not in lowered:
            continue
        tail = line[lowered.find("unresolved reference"):]
        for symbol in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", tail):
            if symbol in _KNOWN_API_IMPORTS and symbol not in found:
                found.append(symbol)
    return found


def _insert_import(source: str, import_line: str) -> str:
    lines = source.splitlines()
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith("import "):
            insert_at = index + 1
    if insert_at == 0:
        for index, line in enumerate(lines):
            if line.startswith("package "):
                insert_at = index + 1
                break
    lines.insert(insert_at, import_line)
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def _repair_missing_imports(files: List[Path], log: str) -> List[str]:
    """Adds a known Morphe import when the compiler names it as unresolved.

    Only symbols the synthesizer itself emits are eligible, so this cannot
    invent an API. It is a mechanical fix for a missing import, nothing more.
    """
    symbols = _missing_api_symbols(log)
    if not symbols:
        return []

    repairs: List[str] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        body = "\n".join(
            line for line in text.splitlines() if not line.startswith("import ")
        )
        for symbol in symbols:
            import_line = f"import {_KNOWN_API_IMPORTS[symbol]}"
            if import_line in text:
                continue
            if not re.search(rf"\b{re.escape(symbol)}\b", body):
                continue
            text = _insert_import(text, import_line)
            repairs.append(f"added '{import_line}' for unresolved '{symbol}'")
        if text != original:
            file.write_text(text, encoding="utf-8")
    return repairs


def _gradle_properties_key() -> bool:
    properties = Path.home() / ".gradle" / "gradle.properties"
    if not properties.exists():
        return False
    try:
        content = properties.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "gpr.key" in content or "gpr.user" in content


def _has_registry_credentials() -> bool:
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GPR_KEY"):
        return True
    return _gradle_properties_key()


def _missing_build_requirements(project: Path) -> List[str]:
    missing: List[str] = []
    if not shutil.which("java"):
        missing.append("Java 17+ was not found on PATH.")
    wrapper = "gradlew.bat" if sys.platform == "win32" else "gradlew"
    if not (project / wrapper).exists():
        missing.append("The project is missing its Gradle wrapper.")
    if not _has_registry_credentials():
        missing.append(
            "The Morphe package registry needs a GitHub token (see the setup steps)."
        )
    return missing


def _run_gradle(project: Path) -> tuple:
    """Runs ``buildAndroid`` from the project itself.

    Windows cannot start a ``.bat`` file through ``CreateProcess`` (that was the
    ``[WinError 2]`` failure); it has to go through ``cmd /c`` with an absolute
    path. Gradle is also chatty, so the error we show is the last meaningful
    lines of its output, with progress noise removed.
    """
    wrapper = project / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
    if not wrapper.exists():
        return False, "The Gradle wrapper is missing from the downloaded project."

    arguments = [str(wrapper), ":patches:buildAndroid", "--no-daemon", "--console=plain", "--stacktrace"]
    if sys.platform == "win32":
        command = ["cmd", "/c", *arguments]
        use_shell = False
    else:
        command = arguments
        use_shell = False

    try:
        result = subprocess.run(
            command,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=1800,
            shell=use_shell,
        )
    except subprocess.TimeoutExpired:
        return False, "The build took longer than 30 minutes and was stopped."
    except FileNotFoundError:
        return False, "Java or the Gradle wrapper could not be started. Is a JDK 17+ installed?"
    except OSError as exc:
        return False, f"Could not start the build: {exc}"

    if result.returncode != 0:
        tail = _gradle_error_tail(result.stdout, result.stderr)
        hint = _gradle_failure_hint(tail)
        return False, f"{hint}\n\n{tail}".strip() if hint else tail
    return True, ""


def _gradle_error_tail(stdout: str, stderr: str, limit: int = 24) -> str:
    """Keeps the informative part of a failed Gradle run.

    Gradle prints the useful details between ``* What went wrong:`` and
    ``* Try:``. That block is what a user needs (missing plugin, HTTP status,
    Kotlin error), so it is preserved instead of a generic "build failed".
    """
    raw = "\n".join(part for part in (stderr, stdout) if part)
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)

    lines: List[str] = []
    for line in cleaned.splitlines():
        stripped = line.rstrip()
        if not stripped.strip():
            continue
        if stripped.lstrip().startswith(("> Task", "Downloading", "Download ", "Starting a Gradle")):
            continue
        if re.fullmatch(r"[=\-. ]+", stripped.strip()):
            continue
        lines.append(stripped.strip())

    if not lines:
        return "The build failed without any message."

    # Compiler diagnostics come before the FAILURE banner; keep them too.
    diagnostics = [
        line for line in lines
        if line.startswith(("e: ", "error:", "w: ")) or line.startswith("Caused by:")
    ][:6]

    # Start at the failure marker when there is one, and stop before Gradle's
    # generic "Try:" help block, which only repeats documentation links.
    start = next((i for i, line in enumerate(lines) if line.startswith("FAILURE")), 0)
    selected = lines[start:]
    for index, line in enumerate(selected):
        if line.startswith("* Try:"):
            selected = selected[:index]
            break
    selected = diagnostics + [line for line in selected if line not in diagnostics]

    if len(selected) > limit:
        selected = ["..."] + selected[-limit:]
    return "\n".join(selected)


def _gradle_failure_hint(text: str) -> str:
    """Turns the most common Gradle failures into one actionable sentence."""
    lowered = text.lower()
    if "401" in text or "unauthorized" in lowered or "bad credentials" in lowered:
        return (
            "GitHub rejected the package-registry token (HTTP 401). The token "
            "stored in gradle.properties is expired or does not have the "
            "'read:packages' permission. Create a new one and replace gpr.key."
        )
    if "403" in text or "forbidden" in lowered:
        return (
            "GitHub refused access to the Morphe registry (HTTP 403). Check that "
            "your token has the 'read:packages' permission and that gpr.user is "
            "your GitHub username."
        )
    if "could not resolve plugin artifact" in lowered:
        return (
            "Gradle could not download the Morphe plugin from GitHub Packages. "
            "GitHub is almost certainly rejecting the token (expired, or missing "
            "the 'read:packages' scope). Run 'morphy-creator doctor' to confirm."
        )
    if "unsupported class file major version" in lowered:
        return (
            "The project was compiled for a newer Java than Morphe accepts. Use "
            "a JDK 17 and make sure JAVA_HOME points to it."
        )
    if "could not find or load main class" in lowered or "java_home" in lowered:
        return "Java could not start. Install a JDK 17+ and set JAVA_HOME."
    if "e: " in text or "compilekotlin" in lowered or "unresolved reference" in lowered:
        return (
            "The generated Kotlin did not compile. The lines below name the file "
            "and the symbol; please report them with the REPORT.txt attached."
        )
    return "The Gradle build failed. The technical details are below."


def _newest_bundle(project: Path) -> Optional[Path]:
    libs = project / "patches" / "build" / "libs"
    if not libs.exists():
        return None
    candidates = [
        path for path in libs.glob("*.mpp")
        if "-sources" not in path.name and "-javadoc" not in path.name
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]
