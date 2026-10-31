import pytest
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
    assert "class TestPatch : BytecodePatch" in res
    assert "testString" in res
    assert "const/4" in res
