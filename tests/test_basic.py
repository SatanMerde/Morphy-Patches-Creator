import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine
from morphy_creator.core.pipeline import PatchWorkbenchPipeline

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

if __name__ == "__main__":
    test_patch_template_engine()
    test_pipeline_build_bundle()
    print("All tests passed.")
