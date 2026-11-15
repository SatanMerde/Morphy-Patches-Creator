"""
Apktool Adapter
Credits to Connor Tumbleson (@iBotPeaches) and Ryszard Wiśniewski (@brutall)
https://github.com/iBotPeaches/Apktool
"""
import subprocess
import logging
from pathlib import Path
from morphy_creator.core.subprocess_utils import run_command

logger = logging.getLogger("morphy.apktool")

class ApktoolAdapter:
    """Wrapper interfacing directly with the Apktool extraction & disassembly pipeline."""

    def __init__(self, executable: str = "apktool"):
        self.executable = executable

    def decode(self, apk_path: Path, output_dir: Path, force: bool = True) -> bool:
        cmd = [self.executable, "d", str(apk_path), "-o", str(output_dir)]
        if force:
            cmd.append("-f")
        logger.info(f"Executing Apktool: {' '.join(cmd)}")
        try:
            run_command(cmd)
            logger.info("Apktool decode completed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Apktool decoding failed: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error("Apktool executable not found. Install it or add it to PATH (morphy-creator doctor).")
            return False

    def build(self, project_dir: Path, output_apk: Path) -> bool:
        cmd = [self.executable, "b", str(project_dir), "-o", str(output_apk)]
        logger.info(f"Rebuilding APK via Apktool: {' '.join(cmd)}")
        try:
            run_command(cmd)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Apktool build failed: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error("Apktool executable not found. Install it or add it to PATH (morphy-creator doctor).")
            return False
