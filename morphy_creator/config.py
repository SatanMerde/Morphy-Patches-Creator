"""Runtime paths used by the decompiler adapters.

Only the two external tools are configurable. Everything else (the DEX/AXML
readers, the analysis, the Kotlin writer) is pure Python and always available.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


def android_sdk_dir() -> Optional[Path]:
    """Returns an installed Android SDK folder, or ``None``.

    ``:patches:buildAndroid`` runs D8, which needs the SDK even though the patch
    module only targets Android. Android Studio installs it in a well-known
    place, so a missing ``ANDROID_HOME`` should not block a machine that has the
    tools: the writer writes ``local.properties`` from this value.
    """
    candidates = [
        os.environ.get("ANDROID_HOME"),
        os.environ.get("ANDROID_SDK_ROOT"),
        str(Path.home() / "AppData" / "Local" / "Android" / "Sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
        str(Path.home() / "Android" / "Sdk"),
        r"C:\Android\Sdk",
        r"C:\Program Files\Android\Sdk",
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if (path / "platform-tools").exists() and (path / "platforms").exists():
            return path
    return None


@dataclass
class MorphyConfig:
    apktool_path: str = os.environ.get("APKTOOL_PATH", "apktool")
    java_path: str = os.environ.get("JAVA_PATH", "java")
    workdir: Path = field(default_factory=lambda: Path(os.environ.get("MORPHY_WORKDIR", "./workspace")))
    output_dir: Path = field(default_factory=lambda: Path(os.environ.get("MORPHY_OUTPUT", "./morphy-output")))


config = MorphyConfig()
