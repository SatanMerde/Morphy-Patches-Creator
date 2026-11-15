"""
APK container inspection: manifest, DEX list, native libraries, packers.

Everything here works directly on the ``.apk`` / ``.apkm`` zip, so a user gets
real information (package, version, protections) before any decompilation
step runs.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from morphy_creator.core.axml import AxmlError, XmlElement, parse_axml
from morphy_creator.core.dex import DexFile

# Commercial packers / protectors detectable from class or library names.
KNOWN_PACKERS: Dict[str, str] = {
    "com/tencent/StubShell": "Tencent Legu / StubShell",
    "com/tencent/StubApp": "Tencent Legu / StubApp",
    "com/qihoo/util": "Qihoo 360 Jiagu",
    "com/secneo/apkwrapper": "SecNeo",
    "com/baidu/protect": "Baidu Protector",
    "com/ali/mobisecenhance": "Alibaba MHO / SecNeo",
    "libjiagu": "Qihoo 360 Jiagu (native)",
    "libnemesis": "Nemesis protector",
    "libmobisec": "Alibaba MHO (native)",
    "libpairipcore": "Google Play Integrity / PairIP",
    "libDexHelper": "Bangcle DexHelper",
    "libexec.so": "Bangcle / SecShell (native)",
    "libSecShell": "SecShell (native)",
    "libshell": "Generic dex shell",
    "libtup.so": "Tencent packer (native)",
}

ANTI_TAMPER_HINTS = (
    "frida", "xposed", "substrate", "ptrace", "magisk", "su/bin",
    "isRooted", "checkRoot", "RootBeer", "SafetyNet", "PlayIntegrity",
)


@dataclass
class ApkInfo:
    """Facts about the APK, gathered without decompiling it."""

    path: Path
    package: str = ""
    version_name: str = ""
    version_code: str = ""
    min_sdk: str = ""
    target_sdk: str = ""
    app_class: str = ""
    permissions: List[str] = field(default_factory=list)
    activities: int = 0
    services: int = 0
    receivers: int = 0
    providers: int = 0
    dex_files: List[str] = field(default_factory=list)
    native_libs: Dict[str, List[str]] = field(default_factory=dict)
    packers: List[str] = field(default_factory=list)
    anti_tamper: List[str] = field(default_factory=list)
    signed_v1: bool = False
    signed_v2_plus: bool = False
    size_mb: float = 0.0

    @property
    def is_protected(self) -> bool:
        return bool(self.packers)


@dataclass
class ApkContainer:
    """Opened APK with lazy DEX loading."""

    info: ApkInfo
    _zip: zipfile.ZipFile = field(repr=False, default=None)

    @classmethod
    def open(cls, apk_path: Path) -> "ApkContainer":
        apk_path = Path(apk_path)
        if not apk_path.exists():
            raise FileNotFoundError(f"APK not found: {apk_path}")

        archive = zipfile.ZipFile(apk_path)
        info = ApkInfo(path=apk_path)
        info.size_mb = round(apk_path.stat().st_size / (1024 * 1024), 1)

        names = archive.namelist()
        info.dex_files = sorted(n for n in names if n.startswith("classes") and n.endswith(".dex"))

        manifest = _read_manifest(archive, info)
        if manifest is not None:
            _fill_from_manifest(manifest, info)
            _detect_packers(manifest, info)

        for name in names:
            if name.startswith("lib/") and name.endswith(".so"):
                abi = name.split("/")[1] if "/" in name else "?"
                info.native_libs.setdefault(abi, []).append(Path(name).name)

        info.permissions = sorted(set(info.permissions))
        info.anti_tamper = _anti_tamper_markers(archive, info)
        info.signed_v1 = any(n.startswith("META-INF/") and n.endswith((".RSA", ".DSA", ".EC")) for n in names)
        info.signed_v2_plus = _has_apk_sig_block(apk_path)

        return cls(info=info, _zip=archive)

    def dex_files(self) -> List[DexFile]:
        """Yields every DEX file; safe to call multiple times."""
        loaded: List[DexFile] = []
        for name in self.info.dex_files:
            try:
                loaded.append(DexFile(self._zip.read(name), name))
            except Exception:
                continue
        return loaded

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def __enter__(self) -> "ApkContainer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _read_manifest(archive: zipfile.ZipFile, info: ApkInfo) -> Optional[XmlElement]:
    try:
        doc = parse_axml(archive.read("AndroidManifest.xml"))
    except (KeyError, AxmlError, Exception):
        return None
    manifests = doc.find_all("manifest") or doc.children
    return manifests[0] if manifests else None


def _fill_from_manifest(manifest: XmlElement, info: ApkInfo) -> None:
    info.package = manifest.get("package")
    info.version_name = manifest.get("android:versionName")
    info.version_code = manifest.get("android:versionCode")

    for sdk in manifest.find_all("uses-sdk"):
        info.min_sdk = sdk.get("android:minSdkVersion") or info.min_sdk
        info.target_sdk = sdk.get("android:targetSdkVersion") or info.target_sdk

    info.permissions = [
        node.get("android:name") for node in manifest.find_all("uses-permission")
        if node.get("android:name")
    ]
    info.activities = len(manifest.find_all("activity"))
    info.services = len(manifest.find_all("service"))
    info.receivers = len(manifest.find_all("receiver"))
    info.providers = len(manifest.find_all("provider"))

    for app in manifest.find_all("application"):
        info.app_class = app.get("android:name")
        break


def _detect_packers(manifest: XmlElement, info: ApkInfo) -> None:
    candidates: List[str] = []
    app = info.app_class or ""
    candidates.append(app)
    for tag in ("activity", "service", "receiver", "provider"):
        for node in manifest.find_all(tag):
            candidates.append(node.get("android:name"))

    blob = " ".join(candidates)
    for marker, label in KNOWN_PACKERS.items():
        if marker.lower() in blob.lower() and label not in info.packers:
            info.packers.append(label)


def _anti_tamper_markers(archive: zipfile.ZipFile, info: ApkInfo) -> List[str]:
    found: List[str] = []
    libs = " ".join(name for names in info.native_libs.values() for name in names)
    lowered = libs.lower()
    if "frida" in lowered or "gum-js" in lowered:
        found.append("Frida gadget shipping with the app")

    for marker in ANTI_TAMPER_HINTS:
        if marker.lower() in lowered and marker not in found:
            found.append(marker)
    return found


def _has_apk_sig_block(apk_path: Path) -> bool:
    """APK Signature Scheme v2/v3 stores a magic string at the end of the file."""
    try:
        with apk_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 4096))
            tail = handle.read()
        return b"APK Sig Block 42" in tail
    except OSError:
        return False
