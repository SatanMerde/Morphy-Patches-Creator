import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine
from morphy_creator.core.pipeline import PatchWorkbenchPipeline
from morphy_creator.core.agent import AutonomousPatchAgent

def test_patch_template_engine():
    res = PatchTemplateEngine.render_unlock_patch(
        package_name="test",
        patch_name="TestPatch",
        class_name="TestPatch",
        description="A test patch",
        strings=["testString"],
        opcodes=["const/4"]
    )
    assert "TestPatch : BytecodePatch" in res
    assert "testString" in res
    assert "const/4" in res

def test_pipeline_build_bundle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        patches_dir = tmp_path / "patches"
        patches_dir.mkdir()
        (patches_dir / "SamplePatch.kt").write_text("// Sample Kotlin", encoding="utf-8")

        output_bundle = tmp_path / "build" / "output.mpp"
        pipeline = PatchWorkbenchPipeline()
        res = pipeline.build_bundle(patches_dir, output_bundle)

        assert res.exists()
        assert "Morphe Compiled Patch Bundle" in res.read_text(encoding="utf-8")
        assert "SamplePatch" in res.read_text(encoding="utf-8")

def test_autonomous_agent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        fake_apk = tmp_path / "test.apk"
        fake_apk.write_bytes(b"PK\x03\x04") # Minimal zip header

        agent = AutonomousPatchAgent()
        res = agent.auto_create_patch(fake_apk, "remove ads and banners", tmp_path / "out")

        assert res["status"] == "success"
        assert res["feature_name"] == "AdBlock"
        assert Path(res["patch_file"]).exists()
        assert Path(res["bundle_file"]).exists()

if __name__ == "__main__":
    test_patch_template_engine()
    test_pipeline_build_bundle()
    test_autonomous_agent()
    print("All tests passed.")
