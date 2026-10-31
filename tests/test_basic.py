import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine

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

if __name__ == "__main__":
    test_patch_template_engine()
    print("All tests passed.")
