"""
Patch verifier.

Checks that a generated file really uses the current Morphe Patcher API and
that its fingerprint is specific enough to survive an app update. This catches
the two mistakes that waste the most time: code written for the old ReVanced
API (``@Patch`` / ``replaceMethod``) and fingerprints built on a single generic
string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# Words that appear in thousands of methods and make a fingerprint fragile.
GENERIC_ANCHORS = {
    "true", "false", "null", "error", "success", "ok", "yes", "no", "none",
    "value", "data", "result", "string", "int", "void", "android", "com",
    "the", "and", "not", "for", "with", "test", "debug", "info", "warning",
}

_FINGERPRINT_RE = re.compile(r"object\s+(\w+)\s*:\s*Fingerprint\s*\(", re.MULTILINE)
_STRINGS_RE = re.compile(r"strings\s*=\s*(?:listOf|setOf)\(([^)]*)\)", re.DOTALL)
_NAME_RE = re.compile(r'\bname\s*=\s*"([^"]+)"')
_CLASS_RE = re.compile(r'\bdefiningClass\s*=\s*"([^"]+)"')


@dataclass
class CheckResult:
    file: str
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: int = 100

    def as_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "score": self.score,
        }


class PatchVerifier:
    """Structural and API checks for generated Kotlin patches."""

    @staticmethod
    def verify_patch_file(patch_path: Path) -> Dict[str, Any]:
        path = Path(patch_path)
        if not path.exists():
            return CheckResult(str(path), False, [f"File not found: {path}"], [], 0).as_dict()
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            return CheckResult(str(path), False, [f"Cannot read the file: {exc}"], [], 0).as_dict()
        return PatchVerifier.verify_source(source, str(path)).as_dict()

    @staticmethod
    def verify_source(source: str, name: str = "<memory>") -> CheckResult:
        result = CheckResult(file=name, valid=True)

        if not source.strip():
            result.errors.append("The file is empty.")
            return _finish(result)

        # 1. Deprecated / non-existent API ------------------------------------
        if "@Patch" in source:
            result.errors.append(
                "Uses '@Patch', which does not exist in the Morphe API. "
                "A patch is a public val created with patch(...)."
            )
        if "replaceMethod" in source:
            result.errors.append(
                "Uses 'replaceMethod', which does not exist. "
                "Use returnEarly(...) or replaceInstruction(...)."
            )
        if "bytecodePatch" in source or "resourcePatch" in source:
            result.warnings.append(
                "Uses a deprecated patch builder; patch(...) is the current API."
            )

        # 2. Patch definition --------------------------------------------------
        if not re.search(r"\bval\s+\w+\s*=\s*patch\s*\(", source):
            result.errors.append("No 'val <name> = patch(...)' definition found.")
        if not re.search(r"^\s*package\s+[\w.]+", source, re.MULTILINE):
            result.errors.append("Missing package declaration.")

        # 3. Fingerprint -------------------------------------------------------
        fingerprints = _FINGERPRINT_RE.findall(source)
        if not fingerprints:
            result.errors.append("No Fingerprint object found.")
        else:
            for block in re.finditer(r"object\s+\w+\s*:\s*Fingerprint\s*\((.*?)\n\)", source, re.DOTALL):
                body = block.group(1)
                anchors = _STRINGS_RE.search(body)
                has_strings = bool(anchors and anchors.group(1).strip())
                has_name = bool(_NAME_RE.search(body))
                has_class = bool(_CLASS_RE.search(body))

                strong = (1 if has_strings else 0) + (1 if has_name else 0) + (1 if has_class else 0)
                if strong == 0:
                    result.errors.append("A Fingerprint defines no class, name or strings.")
                elif strong == 1:
                    result.warnings.append(
                        "A Fingerprint relies on a single signal; it may stop matching "
                        "after an app update."
                    )

                if has_strings:
                    values = re.findall(r'"([^"]*)"', anchors.group(1))
                    weak = [v for v in values if v.strip().lower() in GENERIC_ANCHORS or len(v.strip()) < 3]
                    if weak:
                        result.warnings.append(
                            "Fingerprint uses very generic text: " + ", ".join(weak[:3])
                        )

        # 4. Behaviour change --------------------------------------------------
        if not re.search(r"\.(returnEarly|replaceInstruction|addInstructions|replaceInstructions)\s*\(", source):
            result.warnings.append("The patch does not seem to modify anything.")

        # 5. Safety net --------------------------------------------------------
        if "compatibleWith" not in source:
            result.warnings.append(
                "No compatibleWith(...): the patch will show up for every app."
            )

        if not _balanced(source):
            result.errors.append("Unbalanced brackets or parentheses: the file will not compile.")

        return _finish(result)


def _balanced(source: str) -> bool:
    stack: List[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    in_string = False
    in_block_comment = False
    in_line_comment = False
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""

        if in_block_comment:
            if char == "*" and nxt == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == "/" and nxt == "*":
            in_block_comment = True
            index += 2
            continue
        if char == "/" and nxt == "/":
            in_line_comment = True
            index += 2
            continue
        if char == '"':
            in_string = True
            index += 1
            continue
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != pairs[char]:
                return False
        index += 1
    return not stack


def _finish(result: CheckResult) -> CheckResult:
    result.valid = not result.errors
    result.score = max(0, 100 - len(result.errors) * 40 - len(result.warnings) * 8)
    return result
