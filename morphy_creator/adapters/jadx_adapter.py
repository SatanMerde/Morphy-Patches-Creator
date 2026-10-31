"""
JADX Adapter
Credits to skylot (@skylot)
https://github.com/skylot/jadx

Decompiles Dalvik bytecode directly into readable high-level Java/Kotlin source code,
enabling AI agents and LLMs to understand application semantics effortlessly.
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("morphy.jadx")

class JadxAdapter:
    """Wrapper interfacing directly with JADX for high-level Java decompilation."""

    def __init__(self, executable: str = "jadx"):
        self.executable = executable

    def decompile(self, apk_path: Path, output_dir: Path, deobfuscate: bool = True) -> bool:
        """Decompiles an APK to Java source code for semantic AI analysis."""
        cmd = [self.executable, "-d", str(output_dir), str(apk_path)]
        if deobfuscate:
            cmd.append("--deobf")
        logger.info(f"Executing JADX decompilation: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info("JADX decompilation completed successfully.")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f"JADX invocation note (will fallback to Smali if JADX CLI not present): {e}")
            output_dir.mkdir(parents=True, exist_ok=True)
            return False
