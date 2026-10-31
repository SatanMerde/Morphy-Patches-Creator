from dataclasses import dataclass
from pathlib import Path
import os

@dataclass
class MorphyConfig:
    apktool_path: str = os.environ.get("APKTOOL_PATH", "apktool")
    java_path: str = os.environ.get("JAVA_HOME", "java")
    workdir: Path = Path(os.environ.get("MORPHY_WORKDIR", "./workspace"))
    output_dir: Path = Path(os.environ.get("MORPHY_OUTPUT", "./output"))
    rea_rpc_endpoint: str = os.environ.get("REA_ENDPOINT", "http://localhost:8080")
    ai_model: str = os.environ.get("MORPHE_AI_MODEL", "gemini-1.5-pro")

config = MorphyConfig()
