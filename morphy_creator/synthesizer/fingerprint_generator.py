from typing import List, Dict

class FingerprintGenerator:
    """Produces obfuscation-tolerant fingerprints conforming to Morphe specifications."""

    @staticmethod
    def build_fingerprint(opcodes: List[str], strings: List[str]) -> str:
        ops_str = ", ".join(f'"{op}"' for op in opcodes)
        strs_str = ", ".join(f'"{s}"' for s in strings)
        return f"""
    val fingerprint = Fingerprint(
        opcodes = listOf({ops_str}),
        strings = listOf({strs_str})
    )
"""
