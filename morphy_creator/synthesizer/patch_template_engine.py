from jinja2 import Template

KOTLIN_PATCH_TEMPLATE = """package app.morphe.patches.{{ package_name }}

import app.morphe.patcher.annotation.Patch
import app.morphe.patcher.patch.BytecodePatch
import app.morphe.patcher.fingerprint.Fingerprint

@Patch(
    name = "{{ patch_name }}",
    description = "{{ description }}",
    version = "1.0.0"
)
object {{ class_name }} : BytecodePatch(
    fingerprints = setOf(TargetFingerprint)
) {
    object TargetFingerprint : Fingerprint(
        strings = listOf({{ strings_joined }}),
        opcodes = listOf({{ opcodes_joined }})
    )

    override fun execute() {
        TargetFingerprint.result?.let { match ->
            match.method.replaceMethod {
                instructions = """
                    const/4 v0, 0x1
                    return v0
                """.trimIndent()
            }
        }
    }
}
"""

class PatchTemplateEngine:
    @staticmethod
    def render_unlock_patch(package_name: str, patch_name: str, class_name: str, description: str, strings: list, opcodes: list) -> str:
        tpl = Template(KOTLIN_PATCH_TEMPLATE)
        return tpl.render(
            package_name=package_name,
            patch_name=patch_name,
            class_name=class_name,
            description=description,
            strings_joined=", ".join(f'"{s}"' for s in strings),
            opcodes_joined=", ".join(f'"{o}"' for o in opcodes)
        )
