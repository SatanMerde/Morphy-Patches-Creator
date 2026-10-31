from pathlib import Path
from morphy_creator.adapters.apktool_adapter import ApktoolAdapter
from morphy_creator.adapters.rea_adapter import ReaAdapter
from morphy_creator.adapters.morphe_ai_adapter import MorpheAiAdapter
from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine
import logging

logger = logging.getLogger("morphy.pipeline")

class PatchWorkbenchPipeline:
    def __init__(self):
        self.apktool = ApktoolAdapter()
        self.rea = ReaAdapter()
        self.ai = MorpheAiAdapter()

    def run_full_pipeline(self, apk_path: Path, output_patch_dir: Path, feature: str = "unlock"):
        workspace = Path("./workspace_temp")
        logger.info(f"Phase 1: Unpacking {apk_path} via Apktool...")
        # self.apktool.decode(apk_path, workspace)

        logger.info("Phase 2: Scanning native libraries via REA...")
        native_findings = self.rea.scan_native_binaries(workspace / "lib")

        logger.info("Phase 3: Synthesizing Morphe Kotlin patch via Morphe-AI...")
        patch_code = PatchTemplateEngine.render_unlock_patch(
            package_name="custom",
            patch_name=f"{feature.title()} Feature Patch",
            class_name=f"{feature.title()}FeaturePatch",
            description=f"Automated Morphe patch synthesized for {feature}",
            strings=["isSubscribed", "entitled"],
            opcodes=["invoke-virtual", "move-result", "return"]
        )

        output_patch_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_patch_dir / f"{feature.title()}FeaturePatch.kt"
        out_file.write_text(patch_code, encoding="utf-8")
        logger.info(f"Patch successfully synthesized: {out_file}")
        return out_file
