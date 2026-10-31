"""
Split APK & Bundle Auto-Merger
Handles modern Android split bundles (.apkm, .xapk, .apks, and split directories),
reconstituting them for seamless ingestion into Apktool and Morphy.
"""
import zipfile
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("morphy.split_merger")

class SplitApkMerger:
    """Detects and handles split APK bundles (APKM, XAPK, APKS)."""

    SUPPORTED_EXTENSIONS = [".apkm", ".xapk", ".apks", ".zip"]

    @classmethod
    def is_split_bundle(cls, file_path: Path) -> bool:
        """Checks if a file is an archive containing multiple split APKs."""
        if file_path.suffix.lower() in cls.SUPPORTED_EXTENSIONS:
            return True
        if file_path.is_file() and zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, "r") as zf:
                apk_entries = [n for n in zf.namelist() if n.endswith(".apk")]
                return len(apk_entries) > 1
        return False

    @classmethod
    def extract_and_merge(cls, bundle_path: Path, output_dir: Path) -> Optional[Path]:
        """Extracts split bundle contents and identifies the primary base.apk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Extracting split APK bundle: {bundle_path} -> {output_dir}")

        with zipfile.ZipFile(bundle_path, "r") as zf:
            zf.extractall(output_dir)

        # Look for base.apk
        base_candidates = list(output_dir.glob("base.apk")) or list(output_dir.glob("*base*.apk"))
        if base_candidates:
            primary_base = base_candidates[0]
            logger.info(f"Identified primary base APK: {primary_base}")
            return primary_base

        # Fallback to the largest APK file in the bundle
        all_apks = list(output_dir.glob("*.apk"))
        if all_apks:
            all_apks.sort(key=lambda f: f.stat().st_size, reverse=True)
            primary_base = all_apks[0]
            logger.info(f"Selected largest APK as primary target: {primary_base}")
            return primary_base

        logger.error(f"No valid APK files found inside bundle: {bundle_path}")
        return None
