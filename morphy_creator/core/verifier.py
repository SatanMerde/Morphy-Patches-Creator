"""
Patch Verifier & Linter
Validates synthesized Morphe Kotlin patches before build time,
catching register overflow, invalid fingerprints, and syntax discrepancies early.
"""
import re
import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger("morphy.verifier")

class PatchVerifier:
    """Lints and validates synthesized Morphe Kotlin patch files."""

    @staticmethod
    def verify_patch_file(patch_path: Path) -> Dict[str, Any]:
        """Runs structural checks on a .kt Morphe patch file."""
        if not patch_path.exists():
            return {"valid": False, "errors": [f"File not found: {patch_path}"]}

        code = patch_path.read_text(encoding="utf-8")
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Check @Patch Annotation
        if "@Patch" not in code:
            errors.append("Missing @Patch annotation")
        else:
            if not re.search(r'name\s*=\s*"[^"]+"', code):
                warnings.append("Patch annotation missing explicit 'name'")
            if not re.search(r'description\s*=\s*"[^"]+"', code):
                warnings.append("Patch annotation missing explicit 'description'")

        # 2. Check Base Class Inheritance
        valid_bases = ["BytecodePatch", "ResourcePatch", "SettingsPatch"]
        if not any(f": {base}" in code for base in valid_bases):
            errors.append(f"Patch must inherit from one of: {', '.join(valid_bases)}")

        # 3. Check Fingerprint Definition
        if "BytecodePatch" in code:
            if "Fingerprint" not in code:
                warnings.append("BytecodePatch does not define any Fingerprints")
            else:
                has_strings = bool(re.search(r'strings\s*=\s*listOf\(.+?\)', code, re.DOTALL))
                has_opcodes = bool(re.search(r'opcodes\s*=\s*listOf\(.+?\)', code, re.DOTALL))
                if not (has_strings or has_opcodes):
                    errors.append("Fingerprint must define either 'strings' or 'opcodes'")

        # 4. Check for Register Overflow in replacement code
        invalid_registers = re.findall(r'v(\d{3,})', code)
        if invalid_registers:
            warnings.append(f"Unusually high register index detected: v{invalid_registers[0]}")

        is_valid = len(errors) == 0
        return {
            "file": str(patch_path),
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "score": 100 - (len(errors) * 40 + len(warnings) * 10)
        }
