import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine
from morphy_creator.core.pipeline import PatchWorkbenchPipeline
from morphy_creator.core.agent import AutonomousPatchAgent
from morphy_creator.core.verifier import PatchVerifier
from morphy_creator.core.split_merger import SplitApkMerger
from morphy_creator.presets.catalog import RecipeManager

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
        fake_apk.write_bytes(b"PK\x03\x04")

        agent = AutonomousPatchAgent()
        res = agent.auto_create_patch(fake_apk, "remove ads and banners", tmp_path / "out")

        assert res["status"] == "success"
        assert res["feature_name"] == "AdBlock"
        assert Path(res["patch_file"]).exists()
        assert Path(res["bundle_file"]).exists()

def test_patch_verifier():
    with tempfile.TemporaryDirectory() as tmp_dir:
        patch_file = Path(tmp_dir) / "ValidPatch.kt"
        patch_file.write_text(
            '@Patch(name = "Test", description = "Test Desc")\n'
            'object ValidPatch : BytecodePatch() {\n'
            '    object FP : Fingerprint(strings = listOf("foo"))\n'
            '}\n',
            encoding="utf-8"
        )
        res = PatchVerifier.verify_patch_file(patch_file)
        assert res["valid"] is True
        assert res["score"] >= 80

def test_split_merger():
    with tempfile.TemporaryDirectory() as tmp_dir:
        bundle_path = Path(tmp_dir) / "app.apkm"
        with zipfile.ZipFile(bundle_path, "w") as zf:
            zf.writestr("base.apk", b"PK\x03\x04")
            zf.writestr("split_config.fr.apk", b"PK\x03\x04")

        out_dir = Path(tmp_dir) / "extracted"
        base_apk = SplitApkMerger.extract_and_merge(bundle_path, out_dir)
        assert base_apk is not None
        assert base_apk.name == "base.apk"

def test_recipe_manager():
    recipes = RecipeManager.list_recipes()
    assert len(recipes) >= 4
    adblock = RecipeManager.get_recipe("ad_removal")
    assert "instructions" in adblock

if __name__ == "__main__":
    test_patch_template_engine()
    test_pipeline_build_bundle()
    test_autonomous_agent()
    test_patch_verifier()
    test_split_merger()
    test_recipe_manager()
    print("All 6 test suites passed successfully.")
