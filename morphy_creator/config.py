"""Runtime paths used by the decompiler adapters.

Only the two external tools are configurable. Everything else (the DEX/AXML
readers, the analysis, the Kotlin writer) is pure Python and always available.
"""
from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class MorphyConfig:
    apktool_path: str = os.environ.get("APKTOOL_PATH", "apktool")
    java_path: str = os.environ.get("JAVA_PATH", "java")
    workdir: Path = field(default_factory=lambda: Path(os.environ.get("MORPHY_WORKDIR", "./workspace")))
    output_dir: Path = field(default_factory=lambda: Path(os.environ.get("MORPHY_OUTPUT", "./morphy-output")))


config = MorphyConfig()
