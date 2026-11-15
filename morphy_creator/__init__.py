"""
Morphy Patches Creator: build Morphe patches without writing code.

The engine reads the app's own bytecode (DEX) and binary manifest (AXML), turns
a plain-English goal into ranked, evidence-backed hook candidates, and emits
Kotlin that targets the current ``app.morphe.patcher`` API.
"""

__version__ = "2.1.0"
__author__ = "SatanMerde"
